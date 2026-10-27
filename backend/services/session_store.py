"""Sessão in-memory com TTL. Conteúdo processual nunca vai ao disco nem ao banco.

O prazo conta a partir do último acesso (leitura ou gravação). Sessões expiradas
saem em toda leitura e, com o processo ocioso, na varredura do lifespan.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID

from core.config import settings
from schemas.extraction import ExtractionResult
from schemas.jobs import JobStatus

# Teto de sessões simultâneas: cada uma segura o JSON e os recortes da revisão.
MAX_JOB_SESSIONS = 8


class SessionCapacityError(Exception):
    """Não cabe mais uma sessão sem descartar outra que ainda está no prazo."""


@dataclass
class JobSession:
    job_id: UUID
    status: JobStatus
    created_at: datetime
    extraction: ExtractionResult | None = None
    error_code: str | None = None
    pipeline_note: str = "Processamento concluído."
    # Recortes de células do cartão para a revisão (id → PNG); morrem com a sessão.
    review_crops: dict[str, bytes] = field(default_factory=dict)
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

    def has_room(self) -> bool:
        with self._lock:
            self._purge_locked()
            return len(self._jobs) < MAX_JOB_SESSIONS

    def put(self, session: JobSession) -> None:
        with self._lock:
            self._purge_locked()
            self._touch(session)
            if session.job_id not in self._jobs and len(self._jobs) >= MAX_JOB_SESSIONS:
                raise SessionCapacityError()
            self._jobs[session.job_id] = session

    def get(self, job_id: UUID) -> JobSession | None:
        with self._lock:
            self._purge_locked()
            session = self._jobs.get(job_id)
            if session is None:
                return None
            self._touch(session)
            return session

    def delete(self, job_id: UUID) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def purge_expired(self) -> int:
        with self._lock:
            before = len(self._jobs)
            self._purge_locked()
            return before - len(self._jobs)

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()

    @staticmethod
    def _touch(session: JobSession) -> None:
        session.expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.job_ttl_seconds)

    def _purge_locked(self) -> None:
        expired = [key for key, job in self._jobs.items() if job.is_expired]
        for key in expired:
            del self._jobs[key]


session_store = SessionStore()
