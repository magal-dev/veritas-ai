"""Camada 3: classificação e extração via Gemini.

Só páginas candidatas, agrupadas em lotes (PAGES_PER_CALL páginas por chamada) para
diluir o custo fixo do prompt e manter poucas chamadas; os lotes rodam em paralelo.
Cartão de ponto escaneado reconhecido pelo OCR local (pipeline/time_card_ocr.py) não vai
como página: só as faixas anônimas das colunas com célula duvidosa (STRIPS_PER_CALL por
chamada). Sem GEMINI_API_KEY: stub que marca candidatas como não classificadas.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf as fitz
from google import genai
from google.genai import types

from core.logging import logger
from pipeline.extractor import ExtractionSignals
from pipeline.time_card_ocr import (
    STRIP_PROMPT,
    LocalTimeCards,
    Strip,
    TimeCardReader,
    apply_gemini,
    build_strips,
    read_strip_answers,
    summary,
    to_entries,
)
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
MAX_PARALLEL_CALLS = 8
# Faixas por chamada: 4 = duas folhas (entrada e saída). Medido com 1 por chamada; reavalie
# com scripts/evaluate_cell_fallback.py ao mudar.
STRIPS_PER_CALL = 4
LOCAL_TIME_CARD_CONFIDENCE = 0.9

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
- Horário com algum dígito ilegível ou duvidoso: deixe o campo null e liste o nome em
  ambiguous_fields do registro. Um campo vazio é melhor que um horário errado.

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
    # Recortes das células de cartão para a revisão (id → PNG); só na sessão.
    review_crops: dict[str, bytes] = field(default_factory=dict)


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

    def __init__(
        self,
        api_key: str,
        model_name: str,
        time_card_reader: TimeCardReader | None = None,
    ) -> None:
        self._time_card_reader = time_card_reader
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
        # Faixas: transcrição pura, sem variação.
        self._strip_config = self._config.model_copy(update={"temperature": 0.0})

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
        candidates = set(signals.candidate_pages)
        visual = {
            signal.page_number
            for signal in signals.page_signals
            if signal.visual and signal.page_number in candidates
        }
        if self._time_card_reader is None:
            visual = set()

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as executor:
            # Páginas de texto seguem já; as visuais esperam o OCR local decidir se são
            # cartão reconhecido (só faixas) ou se vão como página.
            page_jobs = self._submit_pages(executor, pdf_path, sorted(candidates - visual))
            local = LocalTimeCards()
            if visual:
                local = self._time_card_reader.read(pdf_path, sorted(visual))  # type: ignore[union-attr]
            page_jobs += self._submit_pages(executor, pdf_path, local.unrecognized_pages)
            strips = build_strips(local.pages)
            strip_jobs = [
                (batch, executor.submit(self._call_strips, batch))
                for batch in (
                    strips[index : index + STRIPS_PER_CALL]
                    for index in range(0, len(strips), STRIPS_PER_CALL)
                )
            ]

            # Agrega na ordem das páginas para a saída ser determinística.
            for batch_pages, future in page_jobs:
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

            for batch, future in strip_jobs:
                try:
                    future.result()
                except Exception:
                    # Faixa sem resposta: as células duvidosas ficam para a revisão.
                    logger.warning("classifier.strip_batch_failed strips=%s", len(batch))
                    continue
                outcome.gemini_call_count += 1

        self._merge_local_time_cards(outcome, local)
        outcome.classifications.sort(key=lambda item: item.page_number)
        outcome.unclassified_candidate_pages.extend(failed_pages)
        outcome.unclassified_candidate_pages = sorted(set(outcome.unclassified_candidate_pages))

        # Sem classificação alguma a triagem local segue: as candidatas ficam
        # não classificadas, em vez de o processo inteiro ser descartado.
        logger.info(
            "classifier.complete gemini_call_count=%s classifications=%s failed=%s "
            "local_time_card_pages=%s strips=%s duration_ms=%s",
            outcome.gemini_call_count,
            len(outcome.classifications),
            len(failed_pages),
            len(local.pages),
            len(strips),
            int((time.perf_counter() - started) * 1000),
        )
        return outcome

    def _submit_pages(
        self,
        executor: ThreadPoolExecutor,
        pdf_path: Path,
        pages: list[int],
    ) -> list[tuple[list[int], Future[dict[int, dict[str, Any]]]]]:
        if not pages:
            return []
        # fitz.Document não é thread-safe: renderiza tudo antes de paralelizar as chamadas.
        document = fitz.open(pdf_path)
        try:
            rendered = [(page_number, _render_page(document, page_number)) for page_number in pages]
        finally:
            document.close()
        batches = [
            rendered[index : index + PAGES_PER_CALL]
            for index in range(0, len(rendered), PAGES_PER_CALL)
        ]
        return [
            ([page_number for page_number, _ in batch], executor.submit(self._call_model, batch))
            for batch in batches
        ]

    def _merge_local_time_cards(self, outcome: ClassificationOutcome, local: LocalTimeCards) -> None:
        if not local.pages:
            return
        cells = [cell for page in local.pages for cell in page.cells]
        apply_gemini(cells, local.schedule)
        entries, crops = to_entries(local.pages)
        outcome.time_cards.extend(entries)
        outcome.review_crops.update(crops)
        outcome.classifications.extend(
            PageClassification(
                page_number=page.page_number,
                document_type=DocumentType.CARTAO_PONTO,
                confidence=LOCAL_TIME_CARD_CONFIDENCE,
            )
            for page in local.pages
        )
        logger.info(
            "classifier.local_time_cards %s",
            " ".join(f"{key}={value}" for key, value in summary(local).items()),
        )

    def read_strips(self, strips: list[Strip]) -> int:
        """Lê as faixas em lotes paralelos (usado também pelo script de avaliação)."""
        batches = [
            strips[index : index + STRIPS_PER_CALL]
            for index in range(0, len(strips), STRIPS_PER_CALL)
        ]
        if not batches:
            return 0
        with ThreadPoolExecutor(max_workers=min(len(batches), MAX_PARALLEL_CALLS)) as executor:
            list(executor.map(self._call_strips, batches))
        return len(batches)

    def _call_strips(self, batch: list[Strip]) -> int:
        """Uma chamada para as faixas; grava a leitura em cada célula e devolve as aceitas."""
        contents: list[Any] = [STRIP_PROMPT]
        for strip in batch:
            contents.append(f"Faixa {strip.strip_id} ({len(strip.cells)} linhas):")
            contents.append(types.Part.from_bytes(data=strip.png(), mime_type="image/png"))
        response = self._client.models.generate_content(
            model=self._model_name,
            contents=contents,
            config=self._strip_config,
        )
        return read_strip_answers(_parse_response_text(response.text), batch)

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
                try:
                    results[page_number] = _payload_to_outcome(item, page_number)
                except (TypeError, ValueError):
                    logger.warning("classifier.invalid_page page_number=%s", page_number)
        return results


def build_classifier(
    api_key: str,
    model_name: str,
    time_card_reader: TimeCardReader | None = None,
) -> DocumentClassifier:
    if api_key.strip():
        return GeminiDocumentClassifier(
            api_key=api_key, model_name=model_name, time_card_reader=time_card_reader
        )
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
