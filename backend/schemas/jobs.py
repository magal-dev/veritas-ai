from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from schemas.extraction import ExtractionResult, PayslipEntry, TimeCardEntry


class JobStatus(str, Enum):
    ACCEPTED = "accepted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DISCARDED = "discarded"
    EXPIRED = "expired"


class JobCreated(BaseModel):
    job_id: UUID
    status: JobStatus
    pdf_page_count: int
    message: str


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    pdf_page_count: int
    candidate_page_count: int
    gemini_call_count: int
    created_at: datetime
    error_code: str | None = None
    pipeline_note: str


class JobPreviewResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    extraction: ExtractionResult


class ExtractionUpdateRequest(BaseModel):
    """Corpo do PATCH de revisão: só listas editáveis pelo perito."""

    time_cards: list[TimeCardEntry]
    payslips: list[PayslipEntry]
