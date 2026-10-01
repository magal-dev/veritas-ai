"""Mede o pipeline completo contra um gabarito feito à mão (resultados para a monografia).

Roda o mesmo caminho de produção (triagem local → Gemini nas candidatas → validador) num
PDF e compara com um gabarito JSON. Imprime só métricas agregadas: nenhuma data, horário,
valor, verba ou texto de página sai no terminal ou no arquivo de saída.

PDFs reais e gabaritos têm dados pessoais: guarde-os fora do repositório (ex.: em uma
pasta local cifrada) e nunca os commite. `*.pdf` já está no .gitignore e o CI bloqueia.

Formato do gabarito (páginas omitidas em "pages" contam como IRRELEVANTE):

    {
      "pages": {"3": "CARTAO_PONTO", "4": "CARTAO_PONTO", "7": "HOLERITE"},
      "time_cards": [
        {"date": "2024-03-01", "clock_in": "08:00", "break_start": "12:00",
         "break_end": "13:00", "clock_out": "17:00"},
        {"date": "2024-03-14", "clock_in": "08:02", "break_start": "12:01",
         "break_end": "13:00", "clock_out": null}
      ],
      "payslips": [
        {"competence": "2024-04", "item_name": "Salário Base", "amount": 3200.00}
      ]
    }

Dias sem jornada (DSR, feriado) ficam fora de "time_cards"; um horário `null` é marcação
ausente no documento, e extrair valor ali conta como alucinação.

Uso (a partir de backend/):
  python scripts/evaluate_extraction.py processo.pdf gabarito.json
  python scripts/evaluate_extraction.py processo.pdf gabarito.json --json metricas.json
  python scripts/evaluate_extraction.py processo.pdf gabarito.json --local-only

Sem GEMINI_API_KEY (ou com --local-only) só a triagem (camadas 1–2) é medida.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import settings  # noqa: E402
from pipeline.classifier import StubDocumentClassifier, build_classifier  # noqa: E402
from pipeline.extractor import LocalDocumentExtractor  # noqa: E402
from pipeline.validator import (  # noqa: E402
    SchemaExtractionValidator,
    _normalize_label,
    normalize_competence,
    normalize_date,
    normalize_time,
)
from schemas.extraction import (  # noqa: E402
    DocumentType,
    ExtractionResult,
    PageClassification,
    PayslipEntry,
    TimeCardEntry,
)

TIME_FIELDS = ("clock_in", "break_start", "break_end", "clock_out")
RELEVANT_TYPES = {DocumentType.CARTAO_PONTO.value, DocumentType.HOLERITE.value}
AMOUNT_TOLERANCE = 0.01


# ---------------------------------------------------------------- gabarito


@dataclass
class TimeCardTruth:
    date: str
    times: dict[str, str | None]


@dataclass
class PayslipTruth:
    competence: str
    item_name: str
    amount: float


@dataclass
class GroundTruth:
    pages: dict[int, str]
    time_cards: list[TimeCardTruth] = field(default_factory=list)
    payslips: list[PayslipTruth] = field(default_factory=list)

    @property
    def relevant_pages(self) -> set[int]:
        return {page for page, kind in self.pages.items() if kind in RELEVANT_TYPES}

    def page_type(self, page: int) -> str:
        return self.pages.get(page, DocumentType.IRRELEVANTE.value)


def _required(value: Any, normalizer, label: str) -> str:
    normalized = normalizer(str(value)) if value is not None else None
    if normalized is None:
        # Só o rótulo do campo vai na mensagem, nunca o valor do gabarito.
        raise ValueError(f"gabarito inválido: {label}")
    return normalized


def parse_ground_truth(payload: dict[str, Any]) -> GroundTruth:
    valid_types = {item.value for item in DocumentType}
    pages: dict[int, str] = {}
    for raw_page, kind in (payload.get("pages") or {}).items():
        page = int(raw_page)
        if page < 1 or kind not in valid_types:
            raise ValueError("gabarito inválido: pages")
        pages[page] = kind

    time_cards: list[TimeCardTruth] = []
    for row in payload.get("time_cards") or []:
        times: dict[str, str | None] = {}
        for name in TIME_FIELDS:
            value = row.get(name)
            times[name] = None if value in (None, "") else _required(value, normalize_time, name)
        time_cards.append(TimeCardTruth(date=_required(row.get("date"), normalize_date, "date"), times=times))

    payslips = [
        PayslipTruth(
            competence=_required(row.get("competence"), normalize_competence, "competence"),
            item_name=str(row.get("item_name") or ""),
            amount=round(abs(float(row["amount"])), 2),
        )
        for row in payload.get("payslips") or []
    ]
    return GroundTruth(pages=pages, time_cards=time_cards, payslips=payslips)


# ---------------------------------------------------------------- métricas


def _ratio(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


@dataclass
class TriageMetrics:
    relevant_pages: int
    candidate_pages: int
    overflow_pages: int
    relevant_in_candidates: int
    relevant_in_overflow: int
    recall: float | None
    precision: float | None


def score_triage(truth: GroundTruth, candidates: Iterable[int], overflow: Iterable[int]) -> TriageMetrics:
    relevant = truth.relevant_pages
    sent = set(candidates)
    skipped = set(overflow)
    hits = len(relevant & sent)
    return TriageMetrics(
        relevant_pages=len(relevant),
        candidate_pages=len(sent),
        overflow_pages=len(skipped),
        relevant_in_candidates=hits,
        relevant_in_overflow=len(relevant & skipped),
        recall=_ratio(hits, len(relevant)),
        precision=_ratio(hits, len(sent)),
    )


@dataclass
class ClassificationMetrics:
    classified_pages: int
    correct: int
    accuracy: float | None
    relevant_missed: int


def score_classification(truth: GroundTruth, classifications: Iterable[PageClassification]) -> ClassificationMetrics:
    items = list(classifications)
    correct = sum(1 for item in items if item.document_type.value == truth.page_type(item.page_number))
    # Relevante perdida: não classificada ou classificada com o tipo errado.
    recognized = {
        item.page_number for item in items if item.document_type.value == truth.page_type(item.page_number)
    }
    return ClassificationMetrics(
        classified_pages=len(items),
        correct=correct,
        accuracy=_ratio(correct, len(items)),
        relevant_missed=len(truth.relevant_pages - recognized),
    )


@dataclass
class TimeCardMetrics:
    expected_days: int
    found_days: int
    day_recall: float | None
    fields_total: int
    fields_correct: int
    field_accuracy: float | None
    per_field_accuracy: dict[str, float | None]
    extra_days: int
    hallucinated_fields: int


def score_time_cards(truth: GroundTruth, predicted: Iterable[TimeCardEntry]) -> TimeCardMetrics:
    by_date: dict[str, TimeCardEntry] = {}
    for entry in predicted:
        iso = normalize_date(entry.date)
        if iso is not None:
            by_date.setdefault(iso, entry)

    expected_dates = {row.date for row in truth.time_cards}
    per_field_ok = {name: 0 for name in TIME_FIELDS}
    per_field_total = {name: 0 for name in TIME_FIELDS}
    hallucinated = 0
    found = 0
    for row in truth.time_cards:
        entry = by_date.get(row.date)
        found += entry is not None
        for name in TIME_FIELDS:
            raw = getattr(entry, name) if entry is not None else None
            got = normalize_time(raw) if raw else None
            want = row.times[name]
            per_field_total[name] += 1
            if want is None:
                per_field_ok[name] += got is None
                hallucinated += got is not None
            else:
                per_field_ok[name] += got == want

    total = sum(per_field_total.values())
    correct = sum(per_field_ok.values())
    return TimeCardMetrics(
        expected_days=len(expected_dates),
        found_days=found,
        day_recall=_ratio(found, len(expected_dates)),
        fields_total=total,
        fields_correct=correct,
        field_accuracy=_ratio(correct, total),
        per_field_accuracy={name: _ratio(per_field_ok[name], per_field_total[name]) for name in TIME_FIELDS},
        extra_days=sum(1 for iso in by_date if iso not in expected_dates),
        hallucinated_fields=hallucinated,
    )


@dataclass
class PayslipMetrics:
    expected_items: int
    found_items: int
    item_recall: float | None
    item_name_matches: int
    extracted_items: int
    extra_items: int
    item_precision: float | None


def score_payslips(truth: GroundTruth, predicted: Iterable[PayslipEntry]) -> PayslipMetrics:
    """Casa verba por competência + valor (o nome varia entre "Sal. Base" e "Salário Base")."""
    remaining: list[tuple[str, float, str]] = []
    for entry in predicted:
        competence = normalize_competence(entry.competence) or entry.competence
        remaining.append((competence, round(abs(entry.amount), 2), _normalize_label(entry.item_name)))
    extracted = len(remaining)

    found = names = 0
    for row in truth.payslips:
        match = next(
            (
                index
                for index, (competence, amount, _) in enumerate(remaining)
                if competence == row.competence and abs(amount - row.amount) <= AMOUNT_TOLERANCE
            ),
            None,
        )
        if match is None:
            continue
        found += 1
        names += remaining[match][2] == _normalize_label(row.item_name)
        remaining.pop(match)

    return PayslipMetrics(
        expected_items=len(truth.payslips),
        found_items=found,
        item_recall=_ratio(found, len(truth.payslips)),
        item_name_matches=names,
        extracted_items=extracted,
        extra_items=len(remaining),
        item_precision=_ratio(found, extracted),
    )


@dataclass
class EvaluationReport:
    pdf_page_count: int
    gemini_call_count: int
    gemini_used: bool
    triage_seconds: float
    gemini_seconds: float
    validation_seconds: float
    triage: TriageMetrics
    classification: ClassificationMetrics | None
    time_cards: TimeCardMetrics | None
    payslips: PayslipMetrics | None
    open_conflicts: int | None


def build_report(
    truth: GroundTruth,
    extraction: ExtractionResult,
    candidates: list[int],
    overflow: list[int],
    timings: dict[str, float],
    gemini_used: bool,
) -> EvaluationReport:
    return EvaluationReport(
        pdf_page_count=extraction.pdf_page_count,
        gemini_call_count=extraction.gemini_call_count,
        gemini_used=gemini_used,
        triage_seconds=round(timings.get("triage", 0.0), 3),
        gemini_seconds=round(timings.get("gemini", 0.0), 3),
        validation_seconds=round(timings.get("validation", 0.0), 3),
        triage=score_triage(truth, candidates, overflow),
        classification=score_classification(truth, extraction.classifications) if gemini_used else None,
        time_cards=score_time_cards(truth, extraction.time_cards) if gemini_used else None,
        payslips=score_payslips(truth, extraction.payslips) if gemini_used else None,
        open_conflicts=len(extraction.conflicts) if gemini_used else None,
    )


# ---------------------------------------------------------------- execução


def run(pdf_path: Path, truth: GroundTruth, local_only: bool) -> EvaluationReport:
    timings: dict[str, float] = {}

    started = time.perf_counter()
    signals = LocalDocumentExtractor().extract(pdf_path)
    timings["triage"] = time.perf_counter() - started

    classifier = (
        StubDocumentClassifier()
        if local_only
        else build_classifier(api_key=settings.gemini_api_key, model_name=settings.gemini_model)
    )
    gemini_used = not isinstance(classifier, StubDocumentClassifier)

    started = time.perf_counter()
    outcome = classifier.classify(pdf_path, signals)
    timings["gemini"] = time.perf_counter() - started

    extraction = ExtractionResult(
        job_id=uuid.uuid4(),
        classifications=outcome.classifications,
        time_cards=outcome.time_cards,
        payslips=outcome.payslips,
        unclassified_candidate_pages=outcome.unclassified_candidate_pages,
        missing_fields=outcome.missing_fields,
        ambiguous_fields=outcome.ambiguous_fields,
        conflicts=outcome.conflicts,
        pdf_page_count=signals.pdf_page_count,
        candidate_page_count=len(signals.candidate_pages) + len(signals.overflow_candidate_pages),
        gemini_call_count=outcome.gemini_call_count,
    )
    started = time.perf_counter()
    extraction = SchemaExtractionValidator().validate(extraction)
    timings["validation"] = time.perf_counter() - started

    return build_report(
        truth,
        extraction,
        list(signals.candidate_pages),
        list(signals.overflow_candidate_pages),
        timings,
        gemini_used,
    )


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.1f}%"


def format_report(report: EvaluationReport) -> str:
    lines = [
        f"Páginas do PDF: {report.pdf_page_count}",
        f"Tempo: triagem {report.triage_seconds:.2f}s · Gemini {report.gemini_seconds:.2f}s "
        f"({report.gemini_call_count} chamadas) · validação {report.validation_seconds:.2f}s",
        "",
        "Triagem (camadas 1–2)",
        f"  páginas relevantes no gabarito: {report.triage.relevant_pages}",
        f"  candidatas enviadas: {report.triage.candidate_pages} (excedentes: {report.triage.overflow_pages})",
        f"  recall: {_pct(report.triage.recall)} · precisão: {_pct(report.triage.precision)}"
        f" · relevantes que ficaram no excedente: {report.triage.relevant_in_overflow}",
    ]
    if not report.gemini_used:
        lines += ["", "Gemini não usado (sem GEMINI_API_KEY ou --local-only): só a triagem foi medida."]
        return "\n".join(lines)

    c, t, p = report.classification, report.time_cards, report.payslips
    assert c is not None and t is not None and p is not None
    lines += [
        "",
        "Classificação (camada 3)",
        f"  acurácia: {_pct(c.accuracy)} ({c.correct}/{c.classified_pages})"
        f" · relevantes não reconhecidas: {c.relevant_missed}",
        "",
        "Cartão de ponto",
        f"  dias encontrados: {t.found_days}/{t.expected_days} ({_pct(t.day_recall)})",
        f"  horários corretos: {t.fields_correct}/{t.fields_total} ({_pct(t.field_accuracy)})",
        "  por campo: "
        + " · ".join(f"{name} {_pct(value)}" for name, value in t.per_field_accuracy.items()),
        f"  dias extras: {t.extra_days} · horários inventados: {t.hallucinated_fields}",
        "",
        "Holerite",
        f"  verbas encontradas: {p.found_items}/{p.expected_items} ({_pct(p.item_recall)})"
        f" · nome idêntico: {p.item_name_matches}",
        f"  extraídas: {p.extracted_items} · sem correspondência: {p.extra_items}"
        f" · precisão: {_pct(p.item_precision)}",
        "",
        f"Conflitos abertos após a validação: {report.open_conflicts}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("gabarito", type=Path)
    parser.add_argument("--json", type=Path, help="grava as métricas (só números) em JSON")
    parser.add_argument("--local-only", action="store_true", help="não chama o Gemini")
    args = parser.parse_args(argv)

    logging.getLogger("veritas_ai").setLevel(logging.WARNING)
    truth = parse_ground_truth(json.loads(args.gabarito.read_text(encoding="utf-8")))
    report = run(args.pdf, truth, local_only=args.local_only)
    print(format_report(report))
    if args.json:
        args.json.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
