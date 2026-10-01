from uuid import uuid4

import pytest

from pipeline.validator import (
    SchemaExtractionValidator,
    is_chronological,
    normalize_competence,
    normalize_date,
    normalize_time,
)
from schemas.extraction import Conflict, ExtractionResult, PayslipEntry, TimeCardEntry


def _card(date: str = "2024-03-04", page: int = 1, confidence: float = 0.9, **times) -> TimeCardEntry:
    defaults = {
        "clock_in": "08:00",
        "break_start": "12:00",
        "break_end": "13:00",
        "clock_out": "17:00",
    }
    defaults.update(times)
    return TimeCardEntry(date=date, source_page=page, confidence=confidence, **defaults)


def _payslip(
    item: str = "Salário",
    amount: float = 3500.0,
    page: int = 1,
    competence: str = "2024-03",
    confidence: float = 0.9,
    **extra,
) -> PayslipEntry:
    return PayslipEntry(
        competence=competence,
        item_name=item,
        amount=amount,
        source_page=page,
        confidence=confidence,
        **extra,
    )


def _validate(**fields) -> ExtractionResult:
    return SchemaExtractionValidator().validate(ExtractionResult(job_id=uuid4(), **fields))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("08:00", "08:00"), ("8:00", "08:00"), ("8h00", "08:00"), (" 17.30 ", "17:30"), ("23:59", "23:59")],
)
def test_normalize_time_accepts_unambiguous_readings(raw, expected):
    assert normalize_time(raw) == expected


@pytest.mark.parametrize("raw", ["24:00", "08:60", "0800", "8", "oito", ""])
def test_normalize_time_rejects_invalid(raw):
    assert normalize_time(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("2024-03-04", "2024-03-04"), ("2024-3-4", "2024-03-04"), ("04/03/2024", "2024-03-04")],
)
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


@pytest.mark.parametrize("raw", ["2024-02-30", "31/04/2024", "março de 2024", "2024/03/04"])
def test_normalize_date_rejects_invalid(raw):
    assert normalize_date(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("2024-03", "2024-03"), ("2024-3", "2024-03"), ("03/2024", "2024-03"), ("3/2024", "2024-03")],
)
def test_normalize_competence(raw, expected):
    assert normalize_competence(raw) == expected


@pytest.mark.parametrize("raw", ["2024-13", "13/2024", "março/2024", "2024"])
def test_normalize_competence_rejects_invalid(raw):
    assert normalize_competence(raw) is None


def test_chronology_accepts_day_and_overnight_shifts():
    assert is_chronological(
        {"clock_in": "08:00", "break_start": "12:00", "break_end": "13:00", "clock_out": "17:00"}
    )
    assert is_chronological(
        {"clock_in": "22:00", "break_start": "02:00", "break_end": "03:00", "clock_out": "06:00"}
    )
    assert is_chronological({"clock_in": "08:00", "clock_out": None})


def test_chronology_rejects_break_outside_shift():
    assert not is_chronological(
        {"clock_in": "08:00", "break_start": "12:00", "break_end": "11:00", "clock_out": "17:00"}
    )
    assert not is_chronological(
        {"clock_in": "08:00", "break_start": "18:00", "break_end": "19:00", "clock_out": "17:00"}
    )


def test_valid_record_passes_untouched():
    result = _validate(time_cards=[_card()], payslips=[_payslip()])

    card = result.time_cards[0]
    assert (card.clock_in, card.break_start, card.break_end, card.clock_out) == (
        "08:00",
        "12:00",
        "13:00",
        "17:00",
    )
    assert card.missing_fields == [] and card.ambiguous_fields == []
    assert result.payslips[0].ambiguous_fields == []
    assert result.conflicts == []


def test_normalizes_unambiguous_formats():
    result = _validate(
        time_cards=[_card(date="04/03/2024", clock_in="8:00", clock_out="17h00", competence="03/2024")],
        payslips=[_payslip(competence="3/2024", item="  Salário  ")],
    )

    card = result.time_cards[0]
    assert card.date == "2024-03-04"
    assert card.competence == "2024-03"
    assert card.clock_in == "08:00"
    assert card.clock_out == "17:00"
    assert result.payslips[0].competence == "2024-03"
    assert result.payslips[0].item_name == "Salário"


def test_invalid_time_is_removed_and_flagged_without_guessing():
    result = _validate(time_cards=[_card(clock_in="25:00")])

    card = result.time_cards[0]
    assert card.clock_in is None
    assert "clock_in" in card.ambiguous_fields
    assert "clock_in" not in card.missing_fields
    assert "clock_in" in result.ambiguous_fields


def test_invalid_required_fields_are_kept_and_flagged():
    result = _validate(
        time_cards=[_card(date="30/02/2024")],
        payslips=[_payslip(competence="13/2024", item="   ")],
    )

    assert result.time_cards[0].date == "30/02/2024"
    assert "date" in result.time_cards[0].ambiguous_fields
    assert result.payslips[0].competence == "13/2024"
    assert {"competence", "item_name"} <= set(result.payslips[0].ambiguous_fields)


def test_invalid_optional_competence_on_time_card_is_removed():
    result = _validate(time_cards=[_card(competence="março")])

    assert result.time_cards[0].competence is None
    assert "competence" in result.time_cards[0].ambiguous_fields


def test_incomplete_pair_is_listed_as_missing():
    result = _validate(time_cards=[_card(clock_out=None, break_end=None)])

    assert {"clock_out", "break_end"} <= set(result.time_cards[0].missing_fields)
    assert {"clock_out", "break_end"} <= set(result.missing_fields)


def test_empty_day_off_row_has_no_pending_fields():
    result = _validate(
        time_cards=[_card(clock_in=None, break_start=None, break_end=None, clock_out=None)]
    )

    assert result.time_cards[0].missing_fields == []
    assert result.time_cards[0].ambiguous_fields == []


def test_out_of_order_times_are_flagged_but_kept():
    result = _validate(time_cards=[_card(break_start="12:00", break_end="11:00")])

    card = result.time_cards[0]
    assert card.break_end == "11:00"
    assert set(card.ambiguous_fields) == {"clock_in", "break_start", "break_end", "clock_out"}


def test_identical_time_card_on_two_pages_is_deduplicated_keeping_best_confidence():
    result = _validate(time_cards=[_card(page=3, confidence=0.6), _card(page=7, confidence=0.95)])

    assert len(result.time_cards) == 1
    assert result.time_cards[0].source_page == 7
    assert result.conflicts == []


def test_divergent_time_card_across_pages_becomes_conflict_and_keeps_both():
    result = _validate(time_cards=[_card(page=3), _card(page=7, clock_out="18:00")])

    assert len(result.time_cards) == 2
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.field == "time_cards[2024-03-04]"
    assert conflict.source_pages == [3, 7]
    assert [value["clock_out"] for value in conflict.values] == ["17:00", "18:00"]
    assert conflict.note


def test_same_page_repetition_is_preserved():
    result = _validate(
        payslips=[_payslip(item="Horas extras 50%", amount=100.0), _payslip(item="Horas extras 50%", amount=80.0)]
    )

    assert len(result.payslips) == 2
    assert result.conflicts == []


def test_payslip_duplicate_across_pages_matches_name_ignoring_case_and_accents():
    result = _validate(
        payslips=[_payslip(item="Salário", page=2), _payslip(item="SALARIO", page=9, confidence=0.5)]
    )

    assert len(result.payslips) == 1
    assert result.payslips[0].source_page == 2


def test_divergent_payslip_amount_across_pages_becomes_conflict():
    result = _validate(payslips=[_payslip(page=2), _payslip(page=9, amount=3600.0)])

    assert len(result.payslips) == 2
    assert result.conflicts[0].field == "payslips[2024-03|Salário]"
    assert result.conflicts[0].values == [3500.0, 3600.0]
    assert result.conflicts[0].source_pages == [2, 9]


def test_base_salary_divergence_across_pages_becomes_conflict():
    result = _validate(
        payslips=[
            _payslip(item="Salário", page=2, base_salary=3500.0),
            _payslip(item="INSS", amount=385.0, page=4, base_salary=3800.0),
        ]
    )

    fields = [conflict.field for conflict in result.conflicts]
    assert fields == ["payslips[2024-03].base_salary"]
    assert result.conflicts[0].source_pages == [2, 4]


def test_model_conflicts_are_preserved():
    original = Conflict(field="competence", values=["2024-03", "2024-04"], source_pages=[1, 2])
    result = _validate(conflicts=[original])

    assert result.conflicts == [original]


def test_records_are_sorted_by_date_and_competence():
    result = _validate(
        time_cards=[_card(date="2024-03-05", page=1), _card(date="2024-03-04", page=2)],
        payslips=[_payslip(competence="2024-04", page=1), _payslip(competence="2024-03", page=2)],
    )

    assert [card.date for card in result.time_cards] == ["2024-03-04", "2024-03-05"]
    assert [slip.competence for slip in result.payslips] == ["2024-03", "2024-04"]


def test_page_level_lists_are_deduplicated():
    result = _validate(
        missing_fields=["base_salary", "base_salary"],
        ambiguous_fields=["competence", "competence"],
    )

    assert result.missing_fields == ["base_salary"]
    assert result.ambiguous_fields == ["competence"]
