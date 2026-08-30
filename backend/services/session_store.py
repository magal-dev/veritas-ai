"""Sessão in-memory com TTL. Conteúdo processual nunca vai ao disco nem ao banco."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from core.config import settings
from schemas.extraction import ExtractionResult
from schemas.jobs import JobStatus


@dataclass
class JobSession:
    job_id: UUID
    status: JobStatus
    created_at: datetime
    extraction: ExtractionResult | None = None
    error_code: str | None = None
    pipeline_note: str = (
        "Fundação: extração Gemini e triagem em camadas ainda não estão ligadas. "
        "O Excel sai no layout provisório, sem linhas de dados."
    )
    expires_at: datetime = field(init=False)

    def __post_init__(self) -> None:
        self.expires_at = self.created_at + timedelta(seconds=settings.job_ttl_seconds)

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at


class SessionStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[UUID, JobSession] = {}

    def put(self, session: JobSession) -> None:
        with self._lock:
            self._purge_locked()
            self._jobs[session.job_id] = session

    def get(self, job_id: UUID) -> JobSession | None:
        with self._lock:
            self._purge_locked()
            session = self._jobs.get(job_id)
            if session is None:
                return None
            if session.is_expired:
                self._jobs.pop(job_id, None)
                return None
            return session

    def delete(self, job_id: UUID) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def _purge_locked(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [key for key, job in self._jobs.items() if job.expires_at <= now]
        for key in expired:
            del self._jobs[key]


session_store = SessionStore()
