import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf as fitz

from pipeline.classifier import (
    PAGES_PER_CALL,
    GeminiDocumentClassifier,
    StubDocumentClassifier,
    build_classifier,
)
from pipeline.extractor import ExtractionSignals, PageSignal


def _pdf_bytes(text: str = "holerite INSS") -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def _multi_page_pdf(tmp_path: Path, pages: int) -> Path:
    document = fitz.open()
    for index in range(1, pages + 1):
        page = document.new_page()
        page.insert_text((72, 72), f"holerite pagina {index}")
    pdf_path = tmp_path / "lote.pdf"
    pdf_path.write_bytes(document.tobytes())
    document.close()
    return pdf_path


def _mock_response(pages: list[dict]) -> MagicMock:
    response = MagicMock()
    response.text = json.dumps({"pages": pages})
    return response


def _pages_in_call(contents: list) -> list[int]:
    return [
        int(match[1])
        for item in contents
        if isinstance(item, str) and (match := re.fullmatch(r"Página (\d+) do PDF:", item))
    ]


def _client_with(mock_client_cls: MagicMock, respond) -> MagicMock:
    mock_models = MagicMock()
    mock_models.generate_content.side_effect = respond
    mock_client_cls.return_value.models = mock_models
    return mock_models


def test_build_classifier_returns_stub_without_api_key():
    classifier = build_classifier(api_key="", model_name="gemini-3.5-flash-lite")
    assert isinstance(classifier, StubDocumentClassifier)


def test_build_classifier_returns_gemini_with_api_key():
    classifier = build_classifier(api_key="test-key", model_name="gemini-3.5-flash-lite")
    assert isinstance(classifier, GeminiDocumentClassifier)


def test_stub_marks_candidates_as_unclassified(tmp_path: Path):
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(_pdf_bytes())
    signals = ExtractionSignals(
        pdf_page_count=1,
        candidate_pages=[1],
        overflow_candidate_pages=[2],
    )

    outcome = StubDocumentClassifier().classify(pdf_path, signals)

    assert outcome.gemini_call_count == 0
    assert outcome.classifications == []
    assert outcome.unclassified_candidate_pages == [1, 2]


@patch("pipeline.classifier.genai.Client")
def test_gemini_extracts_time_card(mock_client_cls: MagicMock, tmp_path: Path):
    pdf_path = tmp_path / "ponto.pdf"
    pdf_path.write_bytes(_pdf_bytes("cartao de ponto entrada saida"))
    mock_models = _client_with(
        mock_client_cls,
        lambda **kwargs: _mock_response(
            [
                {
                    "page_number": 1,
                    "document_type": "CARTAO_PONTO",
                    "confidence": 0.9,
                    "time_cards": [
                        {
                            "date": "2024-03-01",
                            "clock_in": "08:00",
                            "clock_out": "17:00",
                            "source_page": 1,
                            "confidence": 0.85,
                        }
                    ],
                }
            ]
        ),
    )

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-3.5-flash-lite")
    outcome = classifier.classify(pdf_path, ExtractionSignals(pdf_page_count=1, candidate_pages=[1]))

    assert outcome.gemini_call_count == 1
    assert outcome.classifications[0].document_type.value == "CARTAO_PONTO"
    assert outcome.time_cards[0].date == "2024-03-01"
    assert outcome.payslips == []
    mock_models.generate_content.assert_called_once()


@patch("pipeline.classifier.genai.Client")
def test_gemini_irrelevante_produces_no_rows(mock_client_cls: MagicMock, tmp_path: Path):
    pdf_path = tmp_path / "irrelevant.pdf"
    pdf_path.write_bytes(_pdf_bytes("peticao inicial"))
    _client_with(
        mock_client_cls,
        lambda **kwargs: _mock_response(
            [{"page_number": 1, "document_type": "IRRELEVANTE", "confidence": 0.95}]
        ),
    )

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-3.5-flash-lite")
    outcome = classifier.classify(pdf_path, ExtractionSignals(pdf_page_count=1, candidate_pages=[1]))

    assert outcome.gemini_call_count == 1
    assert outcome.time_cards == []
    assert outcome.payslips == []


@patch("pipeline.classifier.genai.Client")
def test_gemini_keeps_unclassified_when_all_calls_fail(mock_client_cls: MagicMock, tmp_path: Path):
    pdf_path = tmp_path / "fail.pdf"
    pdf_path.write_bytes(_pdf_bytes())

    def respond(**kwargs):
        raise RuntimeError("api down")

    _client_with(mock_client_cls, respond)

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-3.5-flash-lite")
    outcome = classifier.classify(
        pdf_path,
        ExtractionSignals(pdf_page_count=2, candidate_pages=[1], overflow_candidate_pages=[2]),
    )

    assert outcome.classifications == []
    assert outcome.gemini_call_count == 0
    assert outcome.unclassified_candidate_pages == [1, 2]


@patch("pipeline.classifier.genai.Client")
def test_gemini_invalid_page_does_not_drop_the_batch(mock_client_cls: MagicMock, tmp_path: Path):
    pdf_path = _multi_page_pdf(tmp_path, 3)
    _client_with(
        mock_client_cls,
        lambda **kwargs: _mock_response(
            [
                {"page_number": 1, "document_type": "NAO_EXISTE", "confidence": 0.9},
                {"page_number": 2, "document_type": "HOLERITE", "confidence": 2},
                {"page_number": 3, "document_type": "HOLERITE", "confidence": 0.8},
            ]
        ),
    )

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-3.5-flash-lite")
    outcome = classifier.classify(
        pdf_path, ExtractionSignals(pdf_page_count=3, candidate_pages=[1, 2, 3])
    )

    assert outcome.gemini_call_count == 1
    assert [item.page_number for item in outcome.classifications] == [3]
    assert outcome.unclassified_candidate_pages == [1, 2]


@patch("pipeline.classifier.genai.Client")
def test_gemini_batches_pages_and_keeps_page_order(mock_client_cls: MagicMock, tmp_path: Path):
    total = PAGES_PER_CALL * 2 + 1
    pdf_path = _multi_page_pdf(tmp_path, total)

    def respond(*, contents, **kwargs):
        return _mock_response(
            [
                {"page_number": page, "document_type": "HOLERITE", "confidence": 0.8}
                for page in reversed(_pages_in_call(contents))
            ]
        )

    mock_models = _client_with(mock_client_cls, respond)

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-3.5-flash-lite")
    candidates = list(range(total, 0, -1))
    outcome = classifier.classify(
        pdf_path, ExtractionSignals(pdf_page_count=total, candidate_pages=candidates)
    )

    assert mock_models.generate_content.call_count == 3
    assert outcome.gemini_call_count == 3
    assert [item.page_number for item in outcome.classifications] == list(range(1, total + 1))
    batch_sizes = sorted(
        len(_pages_in_call(call.kwargs["contents"]))
        for call in mock_models.generate_content.call_args_list
    )
    assert batch_sizes == [1, PAGES_PER_CALL, PAGES_PER_CALL]


@patch("pipeline.classifier.genai.Client")
def test_gemini_failed_batch_and_missing_page_become_unclassified(
    mock_client_cls: MagicMock, tmp_path: Path
):
    total = PAGES_PER_CALL + 2
    pdf_path = _multi_page_pdf(tmp_path, total)

    def respond(*, contents, **kwargs):
        pages = _pages_in_call(contents)
        if 1 in pages:
            # Modelo esquece a página 2 e inventa uma página fora do lote.
            answered = [page for page in pages if page != 2] + [99]
            return _mock_response(
                [{"page_number": page, "document_type": "IRRELEVANTE", "confidence": 0.9} for page in answered]
            )
        raise RuntimeError("timeout")

    _client_with(mock_client_cls, respond)

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-3.5-flash-lite")
    outcome = classifier.classify(
        pdf_path,
        ExtractionSignals(pdf_page_count=total, candidate_pages=list(range(1, total + 1))),
    )

    classified = [item.page_number for item in outcome.classifications]
    assert outcome.gemini_call_count == 1
    assert 99 not in classified
    assert classified == [page for page in range(1, PAGES_PER_CALL + 1) if page != 2]
    assert outcome.unclassified_candidate_pages == [2, *range(PAGES_PER_CALL + 1, total + 1)]


@patch("pipeline.classifier.genai.Client")
def test_gemini_client_config_and_jpeg(mock_client_cls: MagicMock, tmp_path: Path):
    pdf_path = tmp_path / "imagem.pdf"
    pdf_path.write_bytes(_pdf_bytes())
    mock_models = _client_with(
        mock_client_cls,
        lambda **kwargs: _mock_response(
            [{"page_number": 1, "document_type": "IRRELEVANTE", "confidence": 0.9}]
        ),
    )

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-3.5-flash-lite")
    classifier.classify(pdf_path, ExtractionSignals(pdf_page_count=1, candidate_pages=[1]))

    http_options = mock_client_cls.call_args.kwargs["http_options"]
    assert http_options.timeout == 90_000
    assert http_options.retry_options.attempts == 3
    assert 503 in http_options.retry_options.http_status_codes
    call = mock_models.generate_content.call_args
    assert call.kwargs["config"].response_mime_type == "application/json"
    image_part = call.kwargs["contents"][2]
    assert image_part.inline_data.mime_type == "image/jpeg"
    assert image_part.inline_data.data[:2] == b"\xff\xd8"


class _FakeReader:
    """Leitor local que reconhece só as páginas indicadas, com células já relidas."""

    def __init__(self, recognized: dict[int, list]) -> None:
        self.recognized = recognized
        self.calls: list[list[int]] = []

    def read(self, pdf_path, page_numbers):
        from pipeline.time_card_ocr import LocalTimeCards, observed_schedule, resolve_local

        self.calls.append(list(page_numbers))
        local = LocalTimeCards(
            pages=[page for number, page in self.recognized.items() if number in page_numbers],
            unrecognized_pages=[n for n in page_numbers if n not in self.recognized],
        )
        cells = [cell for page in local.pages for cell in page.cells]
        local.schedule = observed_schedule(cells)
        resolve_local(cells, local.schedule)
        return local


def _time_card_page(page_number: int):
    from PIL import Image

    from pipeline.time_card_ocr import Cell, Columns, TimeCardPage

    columns = Columns(entry_x=369, exit_x=465, width=76, height=21)
    cells = []
    for day in ("2025-07-21", "2025-07-28", "2025-08-04", "2025-08-11"):  # segundas
        for slot, value in ((0, "10:00"), (1, "17:00")):
            cell = Cell(day, slot, (369 if slot == 0 else 465, 0, 76, 21), first_read=value)
            cell.rereads = [value, value]
            cell.crop = Image.new("L", (84, 29), 0)
            cell.ink_ratio = 0.3
            cells.append(cell)
    doubtful = cells[-1]  # saída de 2025-08-11 sem consenso
    doubtful.rereads = [None, None]
    page = TimeCardPage(page_number=page_number, rows=31, columns=columns, cells=cells)
    page.work_days = sorted({cell.day for cell in cells})
    return page


def _strip_answer(contents: list, value: str | None) -> MagicMock:
    strips = [
        (match[1], int(match[2]))
        for item in contents
        if isinstance(item, str) and (match := re.fullmatch(r"Faixa (\w+) \((\d+) linhas\):", item))
    ]
    response = MagicMock()
    response.text = json.dumps(
        {"strips": [{"id": strip_id, "values": [value] * rows} for strip_id, rows in strips]}
    )
    return response


@patch("pipeline.classifier.genai.Client")
def test_recognized_scanned_time_card_sends_only_column_strips(mock_client_cls: MagicMock, tmp_path: Path):
    pdf_path = _multi_page_pdf(tmp_path, 3)
    reader = _FakeReader({2: _time_card_page(2)})

    def respond(*, contents, **kwargs):
        if any(isinstance(item, str) and item.startswith("Faixa ") for item in contents):
            # "17:00" para toda a coluna de saída (a de entrada já está resolvida e não vai).
            return _strip_answer(contents, "17:00")
        return _mock_response(
            [{"page_number": page, "document_type": "IRRELEVANTE", "confidence": 0.9}
             for page in _pages_in_call(contents)]
        )

    mock_models = _client_with(mock_client_cls, respond)
    signals = ExtractionSignals(
        pdf_page_count=3,
        candidate_pages=[1, 2, 3],
        page_signals=[PageSignal(page_number=2, visual=True), PageSignal(page_number=3, visual=True)],
    )
    classifier = GeminiDocumentClassifier("test-key", "gemini-3.5-flash-lite", time_card_reader=reader)

    outcome = classifier.classify(pdf_path, signals)

    assert reader.calls == [[2, 3]]  # só as visuais passam pelo OCR local
    pages_sent = sorted(
        page for call in mock_models.generate_content.call_args_list for page in _pages_in_call(call.kwargs["contents"])
    )
    assert pages_sent == [1, 3]  # a página 2 nunca sai inteira
    assert outcome.gemini_call_count == 3  # duas de página (ondas diferentes) + uma de faixas
    assert [(c.page_number, c.document_type.value) for c in outcome.classifications] == [
        (1, "IRRELEVANTE"), (2, "CARTAO_PONTO"), (3, "IRRELEVANTE"),
    ]
    by_day = {entry.date: entry for entry in outcome.time_cards}
    assert by_day["2025-08-11"].clock_out == "17:00"
    assert by_day["2025-08-11"].review_crops.keys() == {"clock_out"}
    assert set(outcome.review_crops) == set(by_day["2025-08-11"].review_crops.values())


@patch("pipeline.classifier.genai.Client")
def test_failed_strip_call_leaves_cells_for_review(mock_client_cls: MagicMock, tmp_path: Path):
    pdf_path = _multi_page_pdf(tmp_path, 1)

    def respond(**kwargs):
        raise RuntimeError("api down")

    _client_with(mock_client_cls, respond)
    signals = ExtractionSignals(
        pdf_page_count=1, candidate_pages=[1], page_signals=[PageSignal(page_number=1, visual=True)]
    )
    classifier = GeminiDocumentClassifier(
        "test-key", "gemini-3.5-flash-lite", time_card_reader=_FakeReader({1: _time_card_page(1)})
    )

    outcome = classifier.classify(pdf_path, signals)

    assert outcome.gemini_call_count == 0
    pending = [entry for entry in outcome.time_cards if entry.ambiguous_fields]
    assert [(entry.date, entry.clock_out) for entry in pending] == [("2025-08-11", None)]


@patch("pipeline.classifier.genai.Client")
def test_read_strips_batches_calls(mock_client_cls: MagicMock):
    from pipeline.classifier import STRIPS_PER_CALL
    from pipeline.time_card_ocr import Strip

    _client_with(mock_client_cls, lambda *, contents, **kwargs: _strip_answer(contents, None))
    page = _time_card_page(1)
    strips = [Strip(f"f{index}", page.cells[:2]) for index in range(STRIPS_PER_CALL + 1)]
    classifier = GeminiDocumentClassifier("test-key", "gemini-3.5-flash-lite")

    assert classifier.read_strips(strips) == 2
    assert classifier.read_strips([]) == 0
