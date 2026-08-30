"""Execução operacional. Proibido: JSON extraído, trechos, nomes, CPF, path de arquivo."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class RunStatus(str, enum.Enum):
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    FAILED = "failed"
    DISCARDED = "discarded"


class ProcessingRun(Base):
    __tablename__ = "processing_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), nullable=False
    )
    pdf_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    candidate_page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gemini_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
