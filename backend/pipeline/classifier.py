"""Camada 3: classificação e extração via Gemini.

Fundação: stub. Não instanciar o SDK e não enviar páginas.
Quando implementar: no máximo 2–5 chamadas por processo, só páginas candidatas.
"""

from __future__ import annotations

from core.logging import logger
from pipeline.extractor import ExtractionSignals
from schemas.extraction import DocumentType, PageClassification


class DocumentClassifier:
    def classify(self, signals: ExtractionSignals) -> list[PageClassification]:
        raise NotImplementedError


class StubDocumentClassifier(DocumentClassifier):
    """Não chama a Gemini API. Devolve lista vazia e gemini_call_count = 0."""

    def classify(self, signals: ExtractionSignals) -> list[PageClassification]:
        logger.info(
            "classifier.stub_skipped candidate_pages=%s document_types=%s",
            len(signals.candidate_pages),
            [member.value for member in DocumentType],
        )
        return []
