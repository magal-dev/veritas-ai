"""Avalia os casos sintéticos em lote e agrega as métricas por layout e digitalização.

Roda o mesmo caminho de scripts/evaluate_extraction.py (produção: triagem → OCR local do
cartão escaneado → Gemini → validador) em cada caso gerado por
scripts/generate_synthetic_cases.py. Pensado para a cota gratuita do Gemini:

- espera entre os casos para não passar de --rpm chamadas por minuto;
- grava as métricas de cada caso ao terminar e, rodando de novo, pula os já medidos
  (a cota diária acaba no meio? rode amanhã e ele continua);
- --limit N mede no máximo N casos nesta rodada.

Uso (a partir de backend/):
  python scripts/evaluate_synthetic.py ../avaliacao-sintetica
  python scripts/evaluate_synthetic.py ../avaliacao-sintetica --no-ocr --only relogio/leve,relogio/medio
                                                                          # linha de base: página inteira
  python scripts/evaluate_synthetic.py ../avaliacao-sintetica --summary-only
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate_extraction import parse_ground_truth, run  # noqa: E402

GABARITO_SUFFIX = ".gabarito.json"


def metrics_path(gabarito: Path, use_ocr: bool) -> Path:
    stem = gabarito.name.removesuffix(GABARITO_SUFFIX)
    return gabarito.with_name(f"{stem}.metricas{'' if use_ocr else '-sem-ocr'}.json")


def evaluate_folder(
    folder: Path, *, use_ocr: bool, rpm: int, limit: int | None, only: set[str] | None = None
) -> int:
    measured = 0
    for gabarito in sorted(folder.glob(f"*{GABARITO_SUFFIX}")):
        target = metrics_path(gabarito, use_ocr)
        if target.exists():
            continue
        if limit is not None and measured >= limit:
            break
        payload = json.loads(gabarito.read_text(encoding="utf-8"))
        meta = payload.get("meta", {})
        if only and f"{meta.get('layout')}/{meta.get('scan')}" not in only:
            continue
        pdf = gabarito.with_name(gabarito.name.removesuffix(GABARITO_SUFFIX) + ".pdf")
        started = time.perf_counter()
        report = run(pdf, parse_ground_truth(payload), local_only=False, use_ocr=use_ocr)
        elapsed = time.perf_counter() - started
        if not report.gemini_used:
            print("GEMINI_API_KEY ausente: nada medido.")
            return measured
        result = {"meta": payload.get("meta", {}), "report": asdict(report)}
        target.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        measured += 1
        print(f"{target.name}: {report.gemini_call_count} chamadas em {elapsed:.0f}s")
        # Ritmo da cota: o lote paralelo do caso conta como rajada; espera o resto do minuto.
        pause = report.gemini_call_count * 60 / rpm - elapsed
        if pause > 0:
            time.sleep(pause)
    return measured


def _sum(rows: list[dict[str, Any]], section: str, key: str) -> int:
    return sum((row["report"].get(section) or {}).get(key) or 0 for row in rows)


def summarize(folder: Path, use_ocr: bool) -> list[dict[str, Any]]:
    """Agrega por (layout, digitalização) e no total. Só contagens e proporções."""
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(folder.glob(f"*.metricas{'' if use_ocr else '-sem-ocr'}.json"))
    ]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        meta = row["meta"]
        groups.setdefault((meta.get("layout", "?"), meta.get("scan", "?")), []).append(row)
    if rows:
        groups[("total", "")] = rows

    table = []
    for (layout, scan), members in groups.items():
        marks = _sum(members, "time_cards", "expected_marks")
        empty = _sum(members, "time_cards", "empty_marks")
        wrong = _sum(members, "time_cards", "wrong_marks")
        relevant = _sum(members, "triage", "relevant_pages")
        items = _sum(members, "payslips", "expected_items")
        table.append({
            "layout": layout,
            "scan": scan,
            "cases": len(members),
            "triage_recall": _ratio(_sum(members, "triage", "relevant_in_candidates"), relevant),
            "marks": marks,
            "marks_correct": _ratio(marks - empty - wrong, marks),
            "marks_empty": _ratio(empty, marks),
            "marks_wrong": wrong,
            "invented": _sum(members, "time_cards", "hallucinated_fields"),
            "extra_days": _sum(members, "time_cards", "extra_days"),
            "unconfirmed_date_days": _sum(members, "time_cards", "unconfirmed_date_days"),
            "payslip_recall": _ratio(_sum(members, "payslips", "found_items"), items),
            "gemini_calls": sum(row["report"]["gemini_call_count"] for row in members),
            "pages_sent_whole": sum(row["report"].get("pages_sent_whole") or 0 for row in members),
            "local_ocr_pages": sum((row["report"].get("local_ocr") or {}).get("pages", 0) for row in members),
        })
    return table


def _ratio(part: int, total: int) -> float | None:
    return round(part / total, 4) if total else None


def format_table(table: list[dict[str, Any]]) -> str:
    def pct(value: float | None) -> str:
        return "-" if value is None else f"{100 * value:.1f}%"

    headers = ["layout", "digitalização", "casos", "triagem", "marcações", "corretas", "vazias",
               "erradas s/ aviso", "inventadas", "datas a conf.", "verbas", "chamadas", "pág. inteiras"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    for row in table:
        cells = [row["layout"], row["scan"], row["cases"], pct(row["triage_recall"]), row["marks"],
                 pct(row["marks_correct"]), pct(row["marks_empty"]), row["marks_wrong"], row["invented"],
                 row["unconfirmed_date_days"], pct(row["payslip_recall"]), row["gemini_calls"],
                 row["pages_sent_whole"]]
        lines.append("| " + " | ".join(str(cell) for cell in cells) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--no-ocr", action="store_true", help="linha de base: cartão escaneado inteiro ao Gemini")
    parser.add_argument("--rpm", type=int, default=4, help="chamadas por minuto (cota gratuita)")
    parser.add_argument("--limit", type=int, help="máximo de casos nesta rodada")
    parser.add_argument("--only", help="só estas combinações, ex.: relogio/leve,relogio/medio")
    parser.add_argument("--summary-only", action="store_true", help="só agrega o que já foi medido")
    args = parser.parse_args(argv)

    logging.getLogger("veritas_ai").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    use_ocr = not args.no_ocr
    only = {item.strip() for item in args.only.split(",")} if args.only else None
    if not args.summary_only:
        evaluate_folder(args.folder, use_ocr=use_ocr, rpm=args.rpm, limit=args.limit, only=only)
    table = summarize(args.folder, use_ocr)
    print(format_table(table))
    suffix = "" if use_ocr else "-sem-ocr"
    (args.folder / f"resumo{suffix}.json").write_text(json.dumps(table, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
