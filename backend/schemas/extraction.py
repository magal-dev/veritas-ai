"""Contratos Pydantic da extração. Instâncias vivem só na sessão (memória)."""

from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


SCHEMA_VERSION = "extraction-schema-0.1"


class DocumentType(str, Enum):
    CARTAO_PONTO = "CARTAO_PONTO"
    HOLERITE = "HOLERITE"
    IRRELEVANTE = "IRRELEVANTE"


class Conflict(BaseModel):
    field: str
    values: list[Any]
    source_pages: list[int]
    note: str | None = None


class TimeCardEntry(BaseModel):
    date: str = Field(description="YYYY-MM-DD")
    competence: str | None = Field(default=None, description="YYYY-MM")
    clock_in: str | None = None
    clock_out: str | None = None
    break_start: str | None = None
    break_end: str | None = None
    source_page: int = Field(ge=1)
    source_excerpt: str | None = None
    confidence: float = Field(ge=0, le=1)
    missing_fields: list[str] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)


class PayslipEntry(BaseModel):
    competence: str = Field(description="YYYY-MM")
    item_name: str
    amount: float
    base_salary: float | None = None
    overtime_paid_hours: float | None = None
    source_page: int = Field(ge=1)
    source_excerpt: str | None = None
    confidence: float = Field(ge=0, le=1)
    missing_fields: list[str] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)


class PageClassification(BaseModel):
    page_number: int = Field(ge=1)
    document_type: DocumentType
    confidence: float = Field(ge=0, le=1)


class ExtractionResult(BaseModel):
    schema_version: str = SCHEMA_VERSION
    job_id: UUID
    time_cards: list[TimeCardEntry] = Field(default_factory=list)
    payslips: list[PayslipEntry] = Field(default_factory=list)
    unclassified_candidate_pages: list[int] = Field(default_factory=list)
    classifications: list[PageClassification] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    ambiguous_fields: list[str] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    pdf_page_count: int = 0
    candidate_page_count: int = 0
    gemini_call_count: int = 0
