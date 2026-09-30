import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest

from pipeline.classifier import (
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


def _mock_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.text = json.dumps(payload)
    return response


def test_build_classifier_returns_stub_without_api_key():
    classifier = build_classifier(api_key="", model_name="gemini-1.5-flash")
    assert isinstance(classifier, StubDocumentClassifier)


def test_build_classifier_returns_gemini_with_api_key():
    classifier = build_classifier(api_key="test-key", model_name="gemini-1.5-flash")
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

    mock_models = MagicMock()
    mock_models.generate_content.return_value = _mock_response(
        {
            "document_type": "CARTAO_PONTO",
            "confidence": 0.9,
            "time_cards": [
                {
                    "date": "2024-03-01",
                    "clock_in": "08:00",
                    "clock_out": "17:00",
                    "source_page": 1,
                    "confidence": 0.85,
                    "missing_fields": [],
                    "ambiguous_fields": [],
                }
            ],
            "payslips": [],
            "missing_fields": [],
            "ambiguous_fields": [],
            "conflicts": [],
        }
    )
    mock_client_cls.return_value.models = mock_models

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-1.5-flash")
    signals = ExtractionSignals(pdf_page_count=1, candidate_pages=[1])

    outcome = classifier.classify(pdf_path, signals)

    assert outcome.gemini_call_count == 1
    assert len(outcome.classifications) == 1
    assert outcome.classifications[0].document_type.value == "CARTAO_PONTO"
    assert len(outcome.time_cards) == 1
    assert outcome.time_cards[0].date == "2024-03-01"
    assert outcome.payslips == []
    mock_models.generate_content.assert_called_once()


@patch("pipeline.classifier.genai.Client")
def test_gemini_irrelevante_produces_no_rows(mock_client_cls: MagicMock, tmp_path: Path):
    pdf_path = tmp_path / "irrelevant.pdf"
    pdf_path.write_bytes(_pdf_bytes("peticao inicial"))

    mock_models = MagicMock()
    mock_models.generate_content.return_value = _mock_response(
        {
            "document_type": "IRRELEVANTE",
            "confidence": 0.95,
            "time_cards": [],
            "payslips": [],
            "missing_fields": [],
            "ambiguous_fields": [],
            "conflicts": [],
        }
    )
    mock_client_cls.return_value.models = mock_models

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-1.5-flash")
    signals = ExtractionSignals(pdf_page_count=1, candidate_pages=[1])

    outcome = classifier.classify(pdf_path, signals)

    assert outcome.gemini_call_count == 1
    assert outcome.time_cards == []
    assert outcome.payslips == []


@patch("pipeline.classifier.genai.Client")
def test_gemini_raises_when_all_pages_fail(mock_client_cls: MagicMock, tmp_path: Path):
    pdf_path = tmp_path / "fail.pdf"
    pdf_path.write_bytes(_pdf_bytes())

    mock_models = MagicMock()
    mock_models.generate_content.side_effect = RuntimeError("api down")
    mock_client_cls.return_value.models = mock_models

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-1.5-flash")
    signals = ExtractionSignals(pdf_page_count=1, candidate_pages=[1])

    with pytest.raises(RuntimeError, match="GEMINI_ERROR"):
        classifier.classify(pdf_path, signals)


@patch("pipeline.classifier.genai.Client")
def test_gemini_only_processes_candidate_pages(mock_client_cls: MagicMock, tmp_path: Path):
    document = fitz.open()
    for index in range(1, 4):
        page = document.new_page()
        page.insert_text((72, 72), f"holerite pagina {index}")
    pdf_path = tmp_path / "multi.pdf"
    pdf_path.write_bytes(document.tobytes())
    document.close()

    mock_models = MagicMock()
    mock_models.generate_content.return_value = _mock_response(
        {
            "document_type": "HOLERITE",
            "confidence": 0.8,
            "time_cards": [],
            "payslips": [
                {
                    "competence": "2024-03",
                    "item_name": "Salario",
                    "amount": 1000.0,
                    "source_page": 2,
                    "confidence": 0.7,
                    "missing_fields": [],
                    "ambiguous_fields": [],
                }
            ],
            "missing_fields": [],
            "ambiguous_fields": [],
            "conflicts": [],
        }
    )
    mock_client_cls.return_value.models = mock_models

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-1.5-flash")
    signals = ExtractionSignals(pdf_page_count=3, candidate_pages=[2])

    outcome = classifier.classify(pdf_path, signals)

    assert outcome.gemini_call_count == 1
    mock_models.generate_content.assert_called_once()


def _multi_page_pdf(tmp_path: Path, pages: int) -> Path:
    document = fitz.open()
    for index in range(1, pages + 1):
        page = document.new_page()
        page.insert_text((72, 72), f"holerite pagina {index}")
    pdf_path = tmp_path / "paralelo.pdf"
    pdf_path.write_bytes(document.tobytes())
    document.close()
    return pdf_path


def _page_from_prompt(contents: list) -> int:
    prompt = contents[0]
    marker = "source_page="
    start = prompt.index(marker) + len(marker)
    return int(prompt[start:].split(" ")[0])


@patch("pipeline.classifier.genai.Client")
def test_gemini_processes_candidates_and_keeps_candidate_order(
    mock_client_cls: MagicMock, tmp_path: Path
):
    pdf_path = _multi_page_pdf(tmp_path, 3)

    def respond(*, contents, **kwargs):
        page_number = _page_from_prompt(contents)
        document_type = "HOLERITE" if page_number != 1 else "IRRELEVANTE"
        return _mock_response(
            {"document_type": document_type, "confidence": page_number / 10}
        )

    mock_models = MagicMock()
    mock_models.generate_content.side_effect = respond
    mock_client_cls.return_value.models = mock_models

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-1.5-flash")
    signals = ExtractionSignals(pdf_page_count=3, candidate_pages=[3, 1, 2])

    outcome = classifier.classify(pdf_path, signals)

    assert outcome.gemini_call_count == 3
    assert [item.page_number for item in outcome.classifications] == [3, 1, 2]
    assert outcome.classifications[1].document_type.value == "IRRELEVANTE"
    assert mock_models.generate_content.call_count == 3
    http_options = mock_client_cls.call_args.kwargs["http_options"]
    assert http_options.timeout == 90_000
    assert http_options.retry_options.attempts == 3
    assert 503 in http_options.retry_options.http_status_codes
    for call in mock_models.generate_content.call_args_list:
        assert call.kwargs["config"].response_mime_type == "application/json"


@patch("pipeline.classifier.genai.Client")
def test_gemini_partial_failure_marks_page_unclassified(
    mock_client_cls: MagicMock, tmp_path: Path
):
    pdf_path = _multi_page_pdf(tmp_path, 3)

    def respond(*, contents, **kwargs):
        if _page_from_prompt(contents) == 2:
            raise RuntimeError("timeout")
        return _mock_response({"document_type": "IRRELEVANTE", "confidence": 0.9})

    mock_models = MagicMock()
    mock_models.generate_content.side_effect = respond
    mock_client_cls.return_value.models = mock_models

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-1.5-flash")
    signals = ExtractionSignals(
        pdf_page_count=3, candidate_pages=[1, 2, 3], overflow_candidate_pages=[]
    )

    outcome = classifier.classify(pdf_path, signals)

    assert outcome.gemini_call_count == 2
    assert [item.page_number for item in outcome.classifications] == [1, 3]
    assert outcome.unclassified_candidate_pages == [2]


@patch("pipeline.classifier.genai.Client")
def test_gemini_receives_grayscale_jpeg(mock_client_cls: MagicMock, tmp_path: Path):
    pdf_path = tmp_path / "imagem.pdf"
    pdf_path.write_bytes(_pdf_bytes())

    mock_models = MagicMock()
    mock_models.generate_content.return_value = _mock_response(
        {"document_type": "IRRELEVANTE", "confidence": 0.9}
    )
    mock_client_cls.return_value.models = mock_models

    classifier = GeminiDocumentClassifier(api_key="test-key", model_name="gemini-1.5-flash")
    classifier.classify(pdf_path, ExtractionSignals(pdf_page_count=1, candidate_pages=[1]))

    image_part = mock_models.generate_content.call_args.kwargs["contents"][1]
    assert image_part.inline_data.mime_type == "image/jpeg"
    assert image_part.inline_data.data[:2] == b"\xff\xd8"
