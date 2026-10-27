"""Orquestra o pipeline e garante descarte do PDF em disco."""

from __future__ import annotations

import asyncio
import tempfile
import time
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import NoReturn

from fastapi import UploadFile

from core.config import settings
from core.logging import logger
from models.processing_run import RunStatus
from pipeline.classifier import DocumentClassifier, build_classifier
from pipeline.extractor import LocalDocumentExtractor
from pipeline.pjecalc_exporter import PjeCalcExporter
from pipeline.time_card_ocr import build_time_card_reader
from pipeline.validator import SchemaExtractionValidator, is_derived_conflict
from repositories.processing_run_repository import ProcessingRunRepository
from schemas.extraction import Conflict, ExtractionResult, PayslipEntry, TimeCardEntry
from schemas.jobs import JobStatus
from services.session_store import JobSession, SessionCapacityError, session_store


class JobError(Exception):
    def __init__(self, error_code: str, status_code: int = 400) -> None:
        super().__init__(error_code)
        self.error_code = error_code
        self.status_code = status_code


class InvalidPdfError(JobError):
    def __init__(self, error_code: str) -> None:
        super().__init__(error_code, 400)


@lru_cache(maxsize=1)
def _shared_stages() -> tuple[
    LocalDocumentExtractor,
    DocumentClassifier,
    SchemaExtractionValidator,
    PjeCalcExporter,
]:
    """Extrator, classificador, validador e exportador reutilizados entre requests.

    O cliente do Gemini e o leitor de cartão não precisam nascer de novo a cada
    rota. O repositório de metadados continua por request.
    """
    reader = build_time_card_reader(settings.time_card_ocr, settings.tesseract_cmd)
    return (
        LocalDocumentExtractor(),
        build_classifier(
            api_key=settings.gemini_api_key,
            model_name=settings.gemini_model,
            time_card_reader=reader,
        ),
        SchemaExtractionValidator(),
        PjeCalcExporter(),
    )


class JobService:
    def __init__(self, run_repository: ProcessingRunRepository | None) -> None:
        self._runs = run_repository
        extractor, classifier, validator, exporter = _shared_stages()
        self._extractor = extractor
        self._classifier = classifier
        self._validator = validator
        self._exporter = exporter

    async def create_from_upload(self, upload: UploadFile) -> JobSession:
        self._assert_pdf(upload)
        job_id = uuid.uuid4()
        started = time.perf_counter()
        tmp_path: Path | None = None

        try:
            if not session_store.has_room():
                raise JobError("SESSION_LIMIT", 429)
            tmp_path = await self._write_temp_pdf(upload)
            signals = await asyncio.to_thread(self._extractor.extract, tmp_path)
            outcome = await asyncio.to_thread(self._classifier.classify, tmp_path, signals)

            extraction = ExtractionResult(
                job_id=job_id,
                classifications=outcome.classifications,
                time_cards=outcome.time_cards,
                payslips=outcome.payslips,
                unclassified_candidate_pages=outcome.unclassified_candidate_pages,
                missing_fields=outcome.missing_fields,
                ambiguous_fields=outcome.ambiguous_fields,
                conflicts=outcome.conflicts,
                pdf_page_count=signals.pdf_page_count,
                candidate_page_count=len(signals.candidate_pages)
                + len(signals.overflow_candidate_pages),
                gemini_call_count=outcome.gemini_call_count,
            )
            extraction = self._validator.validate(extraction)
        except JobError:
            raise
        except ValueError as exc:
            if str(exc) == "INVALID_PDF":
                raise InvalidPdfError("INVALID_FILE_TYPE") from exc
            await self._fail_pipeline(job_id, started, exc)
        except Exception as exc:
            await self._fail_pipeline(job_id, started, exc)
        finally:
            await upload.close()
            self._unlink(tmp_path)

        pipeline_note = _build_pipeline_note(
            candidate_count=extraction.candidate_page_count,
            gemini_calls=extraction.gemini_call_count,
            classified_count=len(extraction.classifications),
            has_api_key=bool(settings.gemini_api_key.strip()),
        )

        session = JobSession(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            created_at=datetime.now(timezone.utc),
            extraction=extraction,
            pipeline_note=pipeline_note,
            review_crops=outcome.review_crops,
        )
        try:
            session_store.put(session)
        except SessionCapacityError as exc:
            raise JobError("SESSION_LIMIT", 429) from exc

        duration_ms = int((time.perf_counter() - started) * 1000)
        await self._record_run(
            run_id=job_id,
            status=RunStatus.COMPLETED,
            pdf_page_count=extraction.pdf_page_count,
            candidate_page_count=extraction.candidate_page_count,
            gemini_call_count=extraction.gemini_call_count,
            duration_ms=duration_ms,
            finished=True,
        )
        logger.info(
            "job.completed job_id=%s pdf_page_count=%s candidate_page_count=%s "
            "gemini_call_count=%s duration_ms=%s",
            job_id,
            extraction.pdf_page_count,
            extraction.candidate_page_count,
            extraction.gemini_call_count,
            duration_ms,
        )
        return session

    def get(self, job_id: uuid.UUID) -> JobSession | None:
        return session_store.get(job_id)

    def update_extraction(
        self,
        job_id: uuid.UUID,
        time_cards: list[TimeCardEntry],
        payslips: list[PayslipEntry],
        open_conflicts: list[Conflict],
    ) -> ExtractionResult | None:
        session = session_store.get(job_id)
        if session is None or session.extraction is None:
            return None

        # O validador soma `conflicts` aos que recalcula; se os antigos fossem mantidos,
        # nenhuma resolução da revisão teria efeito.
        draft = session.extraction.model_copy(
            update={
                "time_cards": time_cards,
                "payslips": payslips,
                "conflicts": [item for item in open_conflicts if not is_derived_conflict(item)],
                "missing_fields": [],
                "ambiguous_fields": [],
            }
        )
        validated = self._validator.validate(draft)
        session.extraction = validated
        session_store.put(session)
        logger.info(
            "job.extraction_updated job_id=%s time_cards=%s payslips=%s conflicts=%s",
            job_id,
            len(validated.time_cards),
            len(validated.payslips),
            len(validated.conflicts),
        )
        return validated

    def review_crop(self, job_id: uuid.UUID, crop_id: str) -> bytes | None:
        session = session_store.get(job_id)
        return None if session is None else session.review_crops.get(crop_id)

    def build_export(self, session: JobSession) -> bytes:
        if session.extraction is None:
            raise InvalidPdfError("EXTRACTION_MISSING")
        return self._exporter.build_zip(session.extraction)

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

    async def _fail_pipeline(self, job_id: uuid.UUID, started: float, exc: BaseException) -> NoReturn:
        duration_ms = int((time.perf_counter() - started) * 1000)
        await self._record_run(
            run_id=job_id,
            status=RunStatus.FAILED,
            error_code="PIPELINE_ERROR",
            duration_ms=duration_ms,
            finished=True,
        )
        logger.warning(
            "job.failed job_id=%s error_type=%s error_code=PIPELINE_ERROR",
            job_id,
            type(exc).__name__,
        )
        raise JobError("PIPELINE_ERROR", 500) from exc

    async def _record_run(self, **kwargs) -> None:
        if self._runs is None:
            return
        try:
            await self._runs.create(**kwargs)
        except Exception as exc:
            logger.warning("job.metadata_skipped error_type=%s", type(exc).__name__)

    @staticmethod
    def _unlink(path: Path | None) -> None:
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("job.tempfile_unlink_failed")


def _build_pipeline_note(
    *,
    candidate_count: int,
    gemini_calls: int,
    classified_count: int,
    has_api_key: bool,
) -> str:
    if not has_api_key:
        return (
            "Triagem local concluída. GEMINI_API_KEY ausente: páginas candidatas "
            "não foram classificadas. Configure a chave para extração com Gemini."
        )
    if candidate_count == 0:
        return (
            "Triagem local concluída sem páginas candidatas. Páginas escaneadas entram "
            "na triagem quando a imagem tem aspecto de tabela; páginas em branco ou sem "
            "estrutura tabular são ignoradas."
        )
    if classified_count == 0:
        return (
            "Triagem local concluída. Nenhuma página candidata foi classificada; "
            f"elas seguem na revisão como não classificadas ({gemini_calls} chamada(s) à API)."
        )
    return (
        f"Triagem local + Gemini concluídas. {candidate_count} página(s) candidata(s), "
        f"{gemini_calls} chamada(s) à API."
    )
