"""Camada 1–2: leitura local e heurísticas.

Fundação: conta páginas com PyMuPDF e devolve sinais vazios.
Não persiste texto. O tempfile do PDF é responsabilidade do service (unlink no finally).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import fitz

from core.logging import logger

LAYER1_KEYWORDS = [
    "cartão de ponto",
    "horas trabalhadas",
    "entrada",
    "saída",
    "holerite",
    "salário bruto",
    "inss",
    "fgts",
    "contracheque",
]


@dataclass
class PageSignal:
    page_number: int
    keyword_hits: list[str] = field(default_factory=list)
    text_density: float = 0.0
    table_hint: bool = False


@dataclass
class ExtractionSignals:
    """Sinais da triagem. text_by_page não deve ser logado nem gravado no banco."""

    pdf_page_count: int
    toc_titles: list[str] = field(default_factory=list)
    candidate_pages: list[int] = field(default_factory=list)
    page_signals: list[PageSignal] = field(default_factory=list)


class DocumentExtractor:
    """Contrato da extração local. Implementação real: pdfplumber + heurísticas."""

    def extract(self, pdf_path: Path) -> ExtractionSignals:
        raise NotImplementedError


class StubDocumentExtractor(DocumentExtractor):
    """Conta páginas; não extrai texto nem classifica candidatas."""

    def extract(self, pdf_path: Path) -> ExtractionSignals:
        try:
            document = fitz.open(pdf_path)
        except Exception as exc:
            raise ValueError("INVALID_PDF") from exc
        try:
            page_count = document.page_count
            toc = document.get_toc() or []
        finally:
            document.close()

        toc_titles = [str(entry[1]) for entry in toc if len(entry) > 1]
        logger.info(
            "extractor.stub_complete pdf_page_count=%s toc_entries=%s",
            page_count,
            len(toc_titles),
        )
        return ExtractionSignals(
            pdf_page_count=page_count,
            toc_titles=toc_titles,
            candidate_pages=[],
            page_signals=[],
        )
