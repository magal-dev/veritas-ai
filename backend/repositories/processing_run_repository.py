"""Persistência de metadados operacionais. Nunca receber payload de extração."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.processing_run import ProcessingRun, RunStatus


class ProcessingRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        run_id: uuid.UUID,
        status: RunStatus,
        pdf_page_count: int | None = None,
        candidate_page_count: int | None = None,
        gemini_call_count: int = 0,
        error_code: str | None = None,
        duration_ms: int | None = None,
        finished: bool = False,
    ) -> None:
        run = ProcessingRun(
            id=run_id,
            status=status,
            pdf_page_count=pdf_page_count,
            candidate_page_count=candidate_page_count,
            gemini_call_count=gemini_call_count,
            error_code=error_code,
            duration_ms=duration_ms,
            finished_at=datetime.now(timezone.utc) if finished else None,
        )
        self._session.add(run)
        await self._session.commit()

    async def mark_discarded(self, run_id: uuid.UUID) -> None:
        await self._session.execute(
            update(ProcessingRun)
            .where(ProcessingRun.id == run_id)
            .values(status=RunStatus.DISCARDED, finished_at=datetime.now(timezone.utc))
        )
        await self._session.commit()
