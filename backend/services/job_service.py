"""Orquestra o pipeline e garante descarte do PDF em disco."""

from __future__ import annotations

import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile

from core.config import settings
from core.logging import logger
from models.processing_run import RunStatus
from pipeline.classifier import StubDocumentClassifier
from pipeline.excel_builder import ProvisionalExcelBuilder
from pipeline.extractor import StubDocumentExtractor
from pipeline.validator import SchemaExtractionValidator
from repositories.processing_run_repository import ProcessingRunRepository
from schemas.extraction import ExtractionResult
from schemas.jobs import JobStatus
from services.session_store import JobSession, session_store


class InvalidPdfError(Exception):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


class JobService:
    def __init__(self, run_repository: ProcessingRunRepository | None) -> None:
        self._runs = run_repository
        self._extractor = StubDocumentExtractor()
        self._classifier = StubDocumentClassifier()
        self._validator = SchemaExtractionValidator()
        self._excel = ProvisionalExcelBuilder()

    async def create_from_upload(self, upload: UploadFile) -> JobSession:
        self._assert_pdf(upload)
        job_id = uuid.uuid4()
        started = time.perf_counter()
        tmp_path: Path | None = None

        try:
            tmp_path = await self._write_temp_pdf(upload)
            signals = self._extractor.extract(tmp_path)
            classifications = self._classifier.classify(signals)
            extraction = ExtractionResult(
                job_id=job_id,
                classifications=classifications,
                pdf_page_count=signals.pdf_page_count,
                candidate_page_count=len(signals.candidate_pages),
                gemini_call_count=0,
            )
            extraction = self._validator.validate(extraction)
        except InvalidPdfError:
            raise
        except ValueError as exc:
            raise InvalidPdfError("INVALID_FILE_TYPE") from exc
        except Exception:
            duration_ms = int((time.perf_counter() - started) * 1000)
            await self._record_run(
                job_id=job_id,
                status=RunStatus.FAILED,
                error_code="PIPELINE_STUB_ERROR",
                duration_ms=duration_ms,
                finished=True,
            )
            logger.exception("job.failed job_id=%s", job_id)
            raise
        finally:
            await upload.close()
            self._unlink(tmp_path)

        session = JobSession(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            created_at=datetime.now(timezone.utc),
            extraction=extraction,
        )
        session_store.put(session)

        duration_ms = int((time.perf_counter() - started) * 1000)
        await self._record_run(
            job_id=job_id,
            status=RunStatus.COMPLETED,
            pdf_page_count=extraction.pdf_page_count,
            candidate_page_count=extraction.candidate_page_count,
            gemini_call_count=0,
            duration_ms=duration_ms,
            finished=True,
        )
        logger.info(
            "job.completed job_id=%s pdf_page_count=%s duration_ms=%s",
            job_id,
            extraction.pdf_page_count,
            duration_ms,
        )
        return session

    def get(self, job_id: uuid.UUID) -> JobSession | None:
        return session_store.get(job_id)

    def build_excel(self, session: JobSession) -> bytes:
        if session.extraction is None:
            raise InvalidPdfError("EXTRACTION_MISSING")
        return self._excel.build(session.extraction)

    async def discard(self, job_id: uuid.UUID) -> bool:
        removed = session_store.delete(job_id)
        if removed and self._runs is not None:
            try:
                await self._runs.mark_discarded(job_id)
            except Exception:
                logger.warning("job.discard_metadata_failed job_id=%s", job_id)
        logger.info("job.discarded job_id=%s removed=%s", job_id, removed)
        return removed

    def _assert_pdf(self, upload: UploadFile) -> None:
        filename = (upload.filename or "").lower()
        content_type = (upload.content_type or "").lower()
        if not filename.endswith(".pdf") and content_type not in {
            "application/pdf",
            "application/x-pdf",
        }:
            raise InvalidPdfError("INVALID_FILE_TYPE")

    async def _write_temp_pdf(self, upload: UploadFile) -> Path:
        max_bytes = settings.max_upload_mb * 1024 * 1024
        handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        path = Path(handle.name)
        written = 0
        try:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise InvalidPdfError("FILE_TOO_LARGE")
                handle.write(chunk)
            handle.flush()
            if written == 0:
                raise InvalidPdfError("EMPTY_FILE")
            return path
        except Exception:
            handle.close()
            self._unlink(path)
            raise
        finally:
            handle.close()

    async def _record_run(self, **kwargs) -> None:
        if self._runs is None:
            return
        try:
            await self._runs.create(**kwargs)
        except Exception:
            logger.warning("job.metadata_skipped")

    @staticmethod
    def _unlink(path: Path | None) -> None:
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("job.tempfile_unlink_failed")
