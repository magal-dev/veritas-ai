"""Validação do JSON extraído: schema, formatos, coerência da jornada e conflitos entre páginas.

Não inventa nem escolhe valores: normaliza o que é inequívoco (ex.: `8:00` → `08:00`),
sinaliza o resto em `missing_fields`/`ambiguous_fields` e registra divergências entre
páginas em `conflicts` para a revisão humana decidir. Regras em docs/SCHEMA_EXTRACAO.md.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Callable, Hashable, Iterable
from datetime import date
from typing import Any, TypeVar

from core.logging import logger
from schemas.extraction import Conflict, ExtractionResult, PayslipEntry, TimeCardEntry

TIME_FIELDS = ("clock_in", "break_start", "break_end", "clock_out")
MINUTES_PER_DAY = 24 * 60

_TIME_RE = re.compile(r"(\d{1,2})\s*[:hH.]\s*(\d{2})")
_ISO_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_BR_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_ISO_COMPETENCE_RE = re.compile(r"(\d{4})-(\d{1,2})")
_BR_COMPETENCE_RE = re.compile(r"(\d{1,2})/(\d{4})")

Entry = TypeVar("Entry", TimeCardEntry, PayslipEntry)


def normalize_time(value: str) -> str | None:
    match = _TIME_RE.fullmatch(value.strip())
    if not match:
        return None
    hours, minutes = int(match[1]), int(match[2])
    if hours > 23 or minutes > 59:
        return None
    return f"{hours:02d}:{minutes:02d}"


def normalize_date(value: str) -> str | None:
    text = value.strip()
    if match := _ISO_DATE_RE.fullmatch(text):
        year, month, day = int(match[1]), int(match[2]), int(match[3])
    elif match := _BR_DATE_RE.fullmatch(text):
        day, month, year = int(match[1]), int(match[2]), int(match[3])
    else:
        return None
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_competence(value: str) -> str | None:
    text = value.strip()
    if match := _ISO_COMPETENCE_RE.fullmatch(text):
        year, month = int(match[1]), int(match[2])
    elif match := _BR_COMPETENCE_RE.fullmatch(text):
        month, year = int(match[1]), int(match[2])
    else:
        return None
    if not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}"


def _minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def is_chronological(times: dict[str, str | None]) -> bool:
    """Entrada ≤ início do intervalo ≤ fim do intervalo ≤ saída, com no máx. uma virada de dia."""
    values = [_minutes(times[name]) for name in TIME_FIELDS if times.get(name)]
    if len(values) < 2:
        return True
    wraps = 0
    unwrapped = [values[0]]
    for previous, value in zip(values, values[1:]):
        if value < previous:
            wraps += 1
        unwrapped.append(value + wraps * MINUTES_PER_DAY)
    return wraps <= 1 and unwrapped[-1] - unwrapped[0] < MINUTES_PER_DAY


def _append_unique(target: list[str], value: str) -> None:
    if value not in target:
        target.append(value)


def _ordered_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _normalize_label(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", stripped)


def _validate_time_card(entry: TimeCardEntry) -> TimeCardEntry:
    missing = list(entry.missing_fields)
    ambiguous = list(entry.ambiguous_fields)
    updates: dict[str, Any] = {}

    normalized_date = normalize_date(entry.date)
    if normalized_date is None:
        _append_unique(ambiguous, "date")
    else:
        updates["date"] = normalized_date

    if entry.competence is not None:
        competence = normalize_competence(entry.competence)
        if competence is None:
            _append_unique(ambiguous, "competence")
        updates["competence"] = competence

    times: dict[str, str | None] = {}
    for name in TIME_FIELDS:
        raw = getattr(entry, name)
        normalized = None if raw is None else normalize_time(raw)
        if raw is not None and normalized is None:
            _append_unique(ambiguous, name)
        times[name] = normalized
    updates.update(times)

    # Par incompleto (entrada sem saída, início sem fim de intervalo). Linha toda vazia
    # é DSR/feriado/folga e não gera pendência.
    for first, second in (("clock_in", "clock_out"), ("break_start", "break_end")):
        if (times[first] is None) != (times[second] is None):
            absent = first if times[first] is None else second
            if absent not in ambiguous:
                _append_unique(missing, absent)

    if not is_chronological(times):
        for name in TIME_FIELDS:
            if times[name] is not None:
                _append_unique(ambiguous, name)

    updates["missing_fields"] = missing
    updates["ambiguous_fields"] = ambiguous
    return entry.model_copy(update=updates)


def _validate_payslip(entry: PayslipEntry) -> PayslipEntry:
    ambiguous = list(entry.ambiguous_fields)
    updates: dict[str, Any] = {}

    competence = normalize_competence(entry.competence)
    if competence is None:
        _append_unique(ambiguous, "competence")
    else:
        updates["competence"] = competence

    item_name = entry.item_name.strip()
    if not item_name:
        _append_unique(ambiguous, "item_name")
    updates["item_name"] = item_name

    updates["ambiguous_fields"] = ambiguous
    return entry.model_copy(update=updates)


def _reconcile(
    entries: list[Entry],
    group_key: Callable[[Entry], Hashable],
    value_key: Callable[[Entry], Hashable],
    describe: Callable[[Entry], tuple[str, Any, str]],
) -> tuple[list[Entry], list[Conflict], int]:
    """Compara registros do mesmo grupo vindos de páginas diferentes.

    Mesmo valor em páginas diferentes: mantém só a página de maior confiança.
    Valores diferentes em páginas diferentes: mantém todos e registra um conflito.
    Repetições na mesma página são preservadas (ex.: duas linhas da mesma verba).
    """
    groups: dict[Hashable, list[Entry]] = {}
    for entry in entries:
        groups.setdefault(group_key(entry), []).append(entry)

    dropped: set[int] = set()
    conflicts: list[Conflict] = []
    for members in groups.values():
        if len({entry.source_page for entry in members}) < 2:
            continue

        by_value: dict[Hashable, list[Entry]] = {}
        for entry in members:
            by_value.setdefault(value_key(entry), []).append(entry)

        for same_value in by_value.values():
            best = max(same_value, key=lambda item: (item.confidence, -item.source_page))
            dropped.update(id(item) for item in same_value if item.source_page != best.source_page)

        survivors = [entry for entry in members if id(entry) not in dropped]
        if len(by_value) > 1 and len({entry.source_page for entry in survivors}) > 1:
            field, _, note = describe(survivors[0])
            values: list[Any] = []
            for entry in survivors:
                value = describe(entry)[1]
                if value not in values:
                    values.append(value)
            conflicts.append(
                Conflict(
                    field=field,
                    values=values,
                    source_pages=sorted({entry.source_page for entry in survivors}),
                    note=note,
                )
            )

    kept = [entry for entry in entries if id(entry) not in dropped]
    return kept, conflicts, len(entries) - len(kept)


def _time_card_values(entry: TimeCardEntry) -> tuple[str | None, ...]:
    return tuple(getattr(entry, name) for name in TIME_FIELDS)


def _describe_time_card(entry: TimeCardEntry) -> tuple[str, Any, str]:
    return (
        f"time_cards[{entry.date}]",
        {name: getattr(entry, name) for name in TIME_FIELDS},
        f"Horários diferentes para o dia {entry.date} em páginas distintas.",
    )


def _describe_payslip(entry: PayslipEntry) -> tuple[str, Any, str]:
    return (
        f"payslips[{entry.competence}|{entry.item_name}]",
        round(entry.amount, 2),
        f"Valores diferentes para \"{entry.item_name}\" na competência {entry.competence}.",
    )


def _base_salary_conflicts(payslips: list[PayslipEntry]) -> list[Conflict]:
    by_competence: dict[str, dict[float, set[int]]] = {}
    for entry in payslips:
        if entry.base_salary is None:
            continue
        values = by_competence.setdefault(entry.competence, {})
        values.setdefault(round(entry.base_salary, 2), set()).add(entry.source_page)

    conflicts: list[Conflict] = []
    for competence, values in by_competence.items():
        pages = set().union(*values.values())
        if len(values) > 1 and len(pages) > 1:
            conflicts.append(
                Conflict(
                    field=f"payslips[{competence}].base_salary",
                    values=list(values),
                    source_pages=sorted(pages),
                    note=f"Salário-base diferente entre páginas na competência {competence}.",
                )
            )
    return conflicts


class ExtractionValidator:
    def validate(self, result: ExtractionResult) -> ExtractionResult:
        raise NotImplementedError


class SchemaExtractionValidator(ExtractionValidator):
    """Schema Pydantic + formatos, coerência da jornada e conflitos entre páginas."""

    def validate(self, result: ExtractionResult) -> ExtractionResult:
        started = time.perf_counter()
        result = ExtractionResult.model_validate(result.model_dump())

        time_cards = [_validate_time_card(entry) for entry in result.time_cards]
        payslips = [_validate_payslip(entry) for entry in result.payslips]

        time_cards, time_card_conflicts, time_card_duplicates = _reconcile(
            time_cards,
            group_key=lambda entry: entry.date,
            value_key=_time_card_values,
            describe=_describe_time_card,
        )
        payslips, payslip_conflicts, payslip_duplicates = _reconcile(
            payslips,
            group_key=lambda entry: (entry.competence, _normalize_label(entry.item_name)),
            value_key=lambda entry: round(entry.amount, 2),
            describe=_describe_payslip,
        )
        conflicts = [
            *result.conflicts,
            *time_card_conflicts,
            *payslip_conflicts,
            *_base_salary_conflicts(payslips),
        ]

        # Ordem estável: dentro do mesmo dia/competência, preserva a ordem da página.
        time_cards.sort(key=lambda entry: (entry.date, entry.source_page))
        payslips.sort(key=lambda entry: (entry.competence, entry.source_page))

        records: list[TimeCardEntry | PayslipEntry] = [*time_cards, *payslips]
        missing = _ordered_unique(
            [*result.missing_fields, *(name for entry in records for name in entry.missing_fields)]
        )
        ambiguous = _ordered_unique(
            [
                *result.ambiguous_fields,
                *(name for entry in records for name in entry.ambiguous_fields),
            ]
        )

        validated = result.model_copy(
            update={
                "time_cards": time_cards,
                "payslips": payslips,
                "missing_fields": missing,
                "ambiguous_fields": ambiguous,
                "conflicts": conflicts,
            }
        )

        logger.info(
            "validator.complete time_cards=%s payslips=%s duplicates_removed=%s "
            "conflicts=%s flagged_records=%s duration_ms=%s",
            len(time_cards),
            len(payslips),
            time_card_duplicates + payslip_duplicates,
            len(conflicts),
            sum(1 for entry in records if entry.missing_fields or entry.ambiguous_fields),
            int((time.perf_counter() - started) * 1000),
        )
        return ExtractionResult.model_validate(validated.model_dump())
