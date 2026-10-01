from __future__ import annotations

import json
import uuid
from pathlib import Path

import pymupdf as fitz
import pytest

from pipeline.classifier import ClassificationOutcome, DocumentClassifier
from schemas.extraction import (
    DocumentType,
    ExtractionResult,
    PageClassification,
    PayslipEntry,
    TimeCardEntry,
)
from scripts import evaluate_extraction as evaluation
from scripts.evaluate_extraction import (
    format_report,
    main,
    parse_ground_truth,
    score_classification,
    score_payslips,
    score_time_cards,
    score_triage,
)

GABARITO = {
    "pages": {"2": "CARTAO_PONTO", "3": "HOLERITE"},
    "time_cards": [
        {"date": "2024-03-01", "clock_in": "08:00", "break_start": "12:00", "break_end": "13:00", "clock_out": "17:00"},
        {"date": "04/03/2024", "clock_in": "8h05", "break_start": "12:00",
         "break_end": "13:00", "clock_out": None},
    ],
    "payslips": [
        {"competence": "04/2024", "item_name": "Salário Base", "amount": 3200.0},
        {"competence": "2024-04", "item_name": "INSS", "amount": -412.47},
    ],
}


def _card(date: str, **times: str | None) -> TimeCardEntry:
    values = {"clock_in": "08:00", "break_start": "12:00", "break_end": "13:00", "clock_out": "17:00"} | times
    return TimeCardEntry(date=date, source_page=2, confidence=0.9, **values)


def _pay(competence: str, item_name: str, amount: float) -> PayslipEntry:
    return PayslipEntry(competence=competence, item_name=item_name, amount=amount, source_page=3, confidence=0.9)


def test_parse_ground_truth_normalizes_formats() -> None:
    truth = parse_ground_truth(GABARITO)
    assert truth.relevant_pages == {2, 3}
    assert truth.page_type(1) == "IRRELEVANTE"
    assert truth.time_cards[1].date == "2024-03-04"
    assert truth.time_cards[1].times == {
        "clock_in": "08:05", "break_start": "12:00", "break_end": "13:00", "clock_out": None,
    }
    assert [(row.competence, row.amount) for row in truth.payslips] == [("2024-04", 3200.0), ("2024-04", 412.47)]


@pytest.mark.parametrize(
    "payload",
    [
        {"pages": {"0": "HOLERITE"}},
        {"pages": {"1": "OUTRO"}},
        {"time_cards": [{"date": "31/02/2024"}]},
        {"time_cards": [{"date": "2024-03-01", "clock_in": "25:00"}]},
        {"payslips": [{"competence": "13/2024", "item_name": "x", "amount": 1}]},
    ],
)
def test_parse_ground_truth_rejects_invalid_values_without_echoing_them(payload: dict) -> None:
    with pytest.raises(ValueError) as error:
        parse_ground_truth(payload)
    assert "2024" not in str(error.value)


def test_score_triage_counts_recall_precision_and_overflow() -> None:
    truth = parse_ground_truth({"pages": {"2": "CARTAO_PONTO", "3": "HOLERITE", "9": "HOLERITE"}})
    metrics = score_triage(truth, candidates=[2, 3, 4, 5], overflow=[9])
    assert metrics.relevant_in_candidates == 2
    assert metrics.recall == pytest.approx(2 / 3, abs=1e-4)
    assert metrics.precision == 0.5
    assert metrics.relevant_in_overflow == 1


def test_score_triage_without_relevant_pages_has_no_ratio() -> None:
    metrics = score_triage(parse_ground_truth({}), candidates=[], overflow=[])
    assert metrics.recall is None
    assert metrics.precision is None


def test_score_classification() -> None:
    truth = parse_ground_truth(GABARITO)
    metrics = score_classification(
        truth,
        [
            PageClassification(page_number=1, document_type=DocumentType.IRRELEVANTE, confidence=0.9),
            PageClassification(page_number=2, document_type=DocumentType.HOLERITE, confidence=0.9),
            PageClassification(page_number=3, document_type=DocumentType.HOLERITE, confidence=0.9),
        ],
    )
    assert (metrics.correct, metrics.classified_pages) == (2, 3)
    assert metrics.relevant_missed == 1


def test_score_time_cards_fields_extras_and_hallucinations() -> None:
    truth = parse_ground_truth(GABARITO)
    metrics = score_time_cards(
        truth,
        [
            _card("2024-03-01", clock_out="17:10"),
            _card("2024-03-01", clock_out="17:00"),  # duplicata: vale a primeira
            _card("04/03/2024", clock_in="08:05", clock_out="17:00"),  # saída ausente no gabarito
            _card("2024-03-09"),
            _card("data ruim"),
        ],
    )
    assert (metrics.found_days, metrics.expected_days) == (2, 2)
    assert (metrics.fields_correct, metrics.fields_total) == (6, 8)
    assert metrics.per_field_accuracy["clock_out"] == 0.0
    assert metrics.per_field_accuracy["clock_in"] == 1.0
    assert metrics.extra_days == 1
    assert metrics.hallucinated_fields == 1


def test_score_time_cards_missing_day_counts_as_wrong() -> None:
    truth = parse_ground_truth(GABARITO)
    metrics = score_time_cards(truth, [_card("2024-03-01")])
    assert metrics.day_recall == 0.5
    # Dia ausente: só o horário que o gabarito também marca como ausente "acerta".
    assert metrics.fields_correct == 5


def test_score_payslips_matches_by_competence_and_amount() -> None:
    truth = parse_ground_truth(GABARITO)
    metrics = score_payslips(
        truth,
        [
            _pay("2024-04", "Sal. Base", 3200.004),
            _pay("04/2024", "inss", 412.47),
            _pay("2024-04", "INSS", 412.47),  # repetida: não casa duas vezes
            _pay("2024-05", "Salário Base", 3200.0),  # competência errada
        ],
    )
    assert (metrics.found_items, metrics.expected_items) == (2, 2)
    assert metrics.item_name_matches == 1
    assert metrics.extra_items == 2
    assert metrics.item_precision == 0.5


def _write_pdf(path: Path) -> None:
    document = fitz.open()
    document.new_page().insert_text((72, 72), "Petição inicial do reclamante.")
    page = document.new_page()
    page.insert_text((72, 72), "CARTAO DE PONTO - horas trabalhadas")
    for index in range(20):
        page.insert_text((72, 100 + index * 14), f"{index + 1:02d}/03/2024  08:00  12:00  13:00  17:00")
    page = document.new_page()
    page.insert_text((72, 72), "HOLERITE - contracheque - salario bruto")
    page.insert_text((72, 100), "Salario Base 3.200,00   INSS 412,47   Liquido 2.787,53")
    document.save(path)
    document.close()


class _FakeClassifier(DocumentClassifier):
    def classify(self, pdf_path, signals) -> ClassificationOutcome:
        return ClassificationOutcome(
            classifications=[
                PageClassification(page_number=page, document_type=DocumentType.CARTAO_PONTO if page == 2
                                   else DocumentType.HOLERITE, confidence=0.9)
                for page in signals.candidate_pages
            ],
            time_cards=[_card("2024-03-01"), _card("2024-03-04", clock_in="08:05", clock_out=None)],
            payslips=[_pay("2024-04", "Salário Base", 3200.0), _pay("2024-04", "INSS", 412.47)],
            gemini_call_count=1,
        )


def test_main_end_to_end_with_fake_gemini(tmp_path: Path, monkeypatch, capsys) -> None:
    pdf = tmp_path / "processo.pdf"
    _write_pdf(pdf)
    gabarito = tmp_path / "gabarito.json"
    gabarito.write_text(json.dumps(GABARITO), encoding="utf-8")
    output = tmp_path / "metricas.json"
    monkeypatch.setattr(evaluation, "build_classifier", lambda **_: _FakeClassifier())

    assert main([str(pdf), str(gabarito), "--json", str(output)]) == 0

    printed = capsys.readouterr().out
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["pdf_page_count"] == 3
    assert report["triage"]["recall"] == 1.0
    assert report["time_cards"]["field_accuracy"] == 1.0
    assert report["payslips"]["item_recall"] == 1.0
    assert report["gemini_call_count"] == 1
    # Só métricas: nenhum valor, data ou verba do gabarito vaza para a saída.
    for leaked in ("3200", "3.200", "2024-03", "Salário", "08:05"):
        assert leaked not in printed
        assert leaked not in output.read_text(encoding="utf-8")


def test_main_local_only_measures_only_triage(tmp_path: Path, capsys) -> None:
    pdf = tmp_path / "processo.pdf"
    _write_pdf(pdf)
    gabarito = tmp_path / "gabarito.json"
    gabarito.write_text(json.dumps(GABARITO), encoding="utf-8")

    assert main([str(pdf), str(gabarito), "--local-only"]) == 0

    printed = capsys.readouterr().out
    assert "só a triagem foi medida" in printed
    assert "Cartão de ponto" not in printed


def test_format_report_handles_empty_ratios() -> None:
    truth = parse_ground_truth({})
    report = evaluation.build_report(truth, ExtractionResult(job_id=uuid.uuid4()), [], [], {}, gemini_used=True)
    text = format_report(report)
    assert "acurácia: -" in text
    assert "recall: -" in text
