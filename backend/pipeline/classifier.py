"""Camada 3: classificação e extração via Gemini.

Só páginas candidatas, agrupadas em lotes (PAGES_PER_CALL páginas por chamada) para
diluir o custo fixo do prompt e manter poucas chamadas; os lotes rodam em paralelo.
Sem GEMINI_API_KEY: stub que marca candidatas como não classificadas.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf as fitz
from google import genai
from google.genai import types

from core.logging import logger
from pipeline.extractor import ExtractionSignals
from schemas.extraction import (
    Conflict,
    DocumentType,
    PageClassification,
    PayslipEntry,
    TimeCardEntry,
)

RENDER_DPI = 150
JPEG_QUALITY = 80
GEMINI_TIMEOUT_SECONDS = 90
GEMINI_RETRY_ATTEMPTS = 3
# Lote por chamada: cada página repete ~500 tokens de instrução se for sozinha.
# Com 5 por chamada e no máx. 5 chamadas, cabem 25 candidatas (MAX_CANDIDATE_PAGES).
PAGES_PER_CALL = 5

GEMINI_PROMPT = """Você é um assistente de extração de documentos trabalhistas brasileiros.

Você receberá uma ou mais imagens de páginas de um PDF, cada uma precedida pelo número
da página. Analise CADA página separadamente e responda SOMENTE com JSON válido no
formato abaixo, com um item em "pages" para cada página recebida.

Regras:
- Classifique como CARTAO_PONTO, HOLERITE ou IRRELEVANTE.
- Não invente valores. Se um campo não estiver visível, omita-o e liste o nome em missing_fields.
- Horários no formato HH:mm. Datas YYYY-MM-DD. Competência YYYY-MM.
- confidence entre 0 e 1 para a classificação da página.
- page_number e source_page devem ser o número informado antes da imagem da página.
- source_excerpt: trecho curto (máx. 120 caracteres) que sustenta o valor principal, se houver.

Formato JSON:
{
  "pages": [
    {
      "page_number": 1,
      "document_type": "CARTAO_PONTO" | "HOLERITE" | "IRRELEVANTE",
      "confidence": 0.0,
      "time_cards": [
        {
          "date": "YYYY-MM-DD",
          "competence": "YYYY-MM",
          "clock_in": "HH:mm",
          "clock_out": "HH:mm",
          "break_start": "HH:mm",
          "break_end": "HH:mm",
          "source_page": 1,
          "source_excerpt": "trecho opcional",
          "confidence": 0.0,
          "missing_fields": [],
          "ambiguous_fields": []
        }
      ],
      "payslips": [
        {
          "competence": "YYYY-MM",
          "item_name": "nome da verba",
          "amount": 0.0,
          "base_salary": 0.0,
          "overtime_paid_hours": 0.0,
          "source_page": 1,
          "source_excerpt": "trecho opcional",
          "confidence": 0.0,
          "missing_fields": [],
          "ambiguous_fields": []
        }
      ],
      "missing_fields": [],
      "ambiguous_fields": [],
      "conflicts": []
    }
  ]
}

Se document_type for IRRELEVANTE, time_cards e payslips devem ser listas vazias.
"""


@dataclass
class ClassificationOutcome:
    classifications: list[PageClassification] = field(default_factory=list)
    time_cards: list[TimeCardEntry] = field(default_factory=list)
    payslips: list[PayslipEntry] = field(default_factory=list)
    unclassified_candidate_pages: list[int] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    ambiguous_fields: list[str] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    gemini_call_count: int = 0


class DocumentClassifier:
    def classify(self, pdf_path: Path, signals: ExtractionSignals) -> ClassificationOutcome:
        raise NotImplementedError


class StubDocumentClassifier(DocumentClassifier):
    """Sem API key: candidatas ficam como não classificadas."""

    def classify(self, pdf_path: Path, signals: ExtractionSignals) -> ClassificationOutcome:
        unclassified = list(signals.candidate_pages) + list(signals.overflow_candidate_pages)
        logger.info(
            "classifier.stub_skipped candidate_pages=%s overflow_pages=%s",
            len(signals.candidate_pages),
            len(signals.overflow_candidate_pages),
        )
        return ClassificationOutcome(
            unclassified_candidate_pages=sorted(set(unclassified)),
            gemini_call_count=0,
        )


class GeminiDocumentClassifier(DocumentClassifier):
    """Classifica e extrai dados das páginas candidatas via Gemini (modelo em GEMINI_MODEL)."""

    def __init__(self, api_key: str, model_name: str) -> None:
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=GEMINI_TIMEOUT_SECONDS * 1000,
                # 429/5xx são frequentes em picos de demanda; tenta de novo com backoff.
                retry_options=types.HttpRetryOptions(
                    attempts=GEMINI_RETRY_ATTEMPTS,
                    initial_delay=2.0,
                    max_delay=15.0,
                    http_status_codes=[429, 500, 503],
                ),
            ),
        )
        self._model_name = model_name
        self._config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
            # Sem tools: desliga o function calling automático (evita overhead e warning).
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def classify(self, pdf_path: Path, signals: ExtractionSignals) -> ClassificationOutcome:
        if not signals.candidate_pages:
            return ClassificationOutcome(
                unclassified_candidate_pages=list(signals.overflow_candidate_pages),
                gemini_call_count=0,
            )

        started = time.perf_counter()
        outcome = ClassificationOutcome(
            unclassified_candidate_pages=list(signals.overflow_candidate_pages),
        )
        failed_pages: list[int] = []

        # fitz.Document não é thread-safe: renderiza tudo antes de paralelizar as chamadas.
        pages = sorted(signals.candidate_pages)
        document = fitz.open(pdf_path)
        try:
            rendered = [(page_number, _render_page(document, page_number)) for page_number in pages]
        finally:
            document.close()
        batches = [
            rendered[index : index + PAGES_PER_CALL]
            for index in range(0, len(rendered), PAGES_PER_CALL)
        ]

        with ThreadPoolExecutor(max_workers=len(batches)) as executor:
            futures = [executor.submit(self._call_model, batch) for batch in batches]
            # Agrega na ordem das páginas para a saída ser determinística.
            for batch, future in zip(batches, futures):
                batch_pages = [page_number for page_number, _ in batch]
                try:
                    page_outcomes = future.result()
                except Exception:
                    logger.warning("classifier.batch_failed pages=%s", len(batch_pages))
                    failed_pages.extend(batch_pages)
                    continue
                outcome.gemini_call_count += 1
                for page_number in batch_pages:
                    page_outcome = page_outcomes.get(page_number)
                    if page_outcome is None:
                        logger.warning("classifier.page_missing page_number=%s", page_number)
                        failed_pages.append(page_number)
                        continue
                    outcome.classifications.append(page_outcome["classification"])
                    outcome.time_cards.extend(page_outcome["time_cards"])
                    outcome.payslips.extend(page_outcome["payslips"])
                    outcome.missing_fields.extend(page_outcome["missing_fields"])
                    outcome.ambiguous_fields.extend(page_outcome["ambiguous_fields"])
                    outcome.conflicts.extend(page_outcome["conflicts"])

        outcome.unclassified_candidate_pages.extend(failed_pages)
        outcome.unclassified_candidate_pages = sorted(set(outcome.unclassified_candidate_pages))

        if not outcome.classifications:
            raise RuntimeError("GEMINI_ERROR")

        logger.info(
            "classifier.complete gemini_call_count=%s classifications=%s failed=%s duration_ms=%s",
            outcome.gemini_call_count,
            len(outcome.classifications),
            len(failed_pages),
            int((time.perf_counter() - started) * 1000),
        )
        return outcome

    def _call_model(self, batch: list[tuple[int, types.Part]]) -> dict[int, dict[str, Any]]:
        """Uma chamada para o lote; devolve o resultado por número de página."""
        contents: list[Any] = [GEMINI_PROMPT]
        for page_number, image_part in batch:
            contents.append(f"Página {page_number} do PDF:")
            contents.append(image_part)
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=contents,
            config=self._config,
        )
        payload = _parse_response_text(response.text)
        expected = {page_number for page_number, _ in batch}
        results: dict[int, dict[str, Any]] = {}
        for item in payload.get("pages", []):
            try:
                page_number = int(item.get("page_number"))
            except (TypeError, ValueError):
                continue
            if page_number in expected and page_number not in results:
                results[page_number] = _payload_to_outcome(item, page_number)
        return results


def build_classifier(api_key: str, model_name: str) -> DocumentClassifier:
    if api_key.strip():
        return GeminiDocumentClassifier(api_key=api_key, model_name=model_name)
    return StubDocumentClassifier()


def _render_page(document: fitz.Document, page_number: int) -> types.Part:
    """Escala de cinza + JPEG: payload bem menor que PNG colorido, mesma legibilidade."""
    page = document[page_number - 1]
    pixmap = page.get_pixmap(dpi=RENDER_DPI, colorspace=fitz.csGRAY)
    return types.Part.from_bytes(
        data=pixmap.tobytes("jpeg", jpg_quality=JPEG_QUALITY),
        mime_type="image/jpeg",
    )


def _parse_response_text(text: str | None) -> dict[str, Any]:
    if not text:
        raise ValueError("EMPTY_GEMINI_RESPONSE")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    return json.loads(cleaned)


def _payload_to_outcome(payload: dict[str, Any], page_number: int) -> dict[str, Any]:
    document_type = DocumentType(payload.get("document_type", "IRRELEVANTE"))
    confidence = float(payload.get("confidence", 0.0))

    classification = PageClassification(
        page_number=page_number,
        document_type=document_type,
        confidence=confidence,
    )

    time_cards: list[TimeCardEntry] = []
    payslips: list[PayslipEntry] = []

    if document_type == DocumentType.CARTAO_PONTO:
        for raw in payload.get("time_cards", []):
            raw["source_page"] = page_number
            try:
                time_cards.append(TimeCardEntry.model_validate(raw))
            except Exception:
                logger.warning("classifier.invalid_time_card page_number=%s", page_number)

    if document_type == DocumentType.HOLERITE:
        for raw in payload.get("payslips", []):
            raw["source_page"] = page_number
            try:
                payslips.append(PayslipEntry.model_validate(raw))
            except Exception:
                logger.warning("classifier.invalid_payslip page_number=%s", page_number)

    conflicts: list[Conflict] = []
    for raw in payload.get("conflicts", []):
        try:
            conflicts.append(Conflict.model_validate(raw))
        except Exception:
            continue

    return {
        "classification": classification,
        "time_cards": time_cards,
        "payslips": payslips,
        "missing_fields": list(payload.get("missing_fields", [])),
        "ambiguous_fields": list(payload.get("ambiguous_fields", [])),
        "conflicts": conflicts,
    }
