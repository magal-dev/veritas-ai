import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pymupdf as fitz
import pytest

from pipeline.classifier import (
    PAGES_PER_CALL,
    GeminiDocumentClassifier,
    StubDocumentClassifier,
    build_classifier,
)
from pipeline.extractor import ExtractionSignals


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
def test_gemini_raises_when_all_calls_fail(mock_client_cls: MagicMock, tmp_path: Path):
    pdf_path = tmp_path / "fail.pdf"
    pdf_path.write_bytes(_pdf_bytes())

    def respond(**kwargs):
        raise RuntimeError("api down")

    _client_with(mock_client_cls, respond)

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-3.5-flash-lite")
    with pytest.raises(RuntimeError, match="GEMINI_ERROR"):
        classifier.classify(pdf_path, ExtractionSignals(pdf_page_count=1, candidate_pages=[1]))


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
