"""Avaliação do cartão de ponto escaneado lido no servidor (pipeline/time_card_ocr.py).

Roda o mesmo código da camada 3 (OCR local + faixas anônimas por coluna para o Gemini)
contra um gabarito feito à mão e separa o resultado em três números por estratégia:
corretos, enviados à revisão e errados sem aviso (o pior caso para o perito).

Estratégias:
- local_1_leitura: só a primeira leitura do OCR, checada contra a jornada (referência).
- local_consenso: três leituras iguais e perto da jornada (o que o pipeline aceita sem API).
- pipeline: local_consenso + leitura do Gemini por faixa de coluna (só com --send).

Dependência extra: o binário do Tesseract com o idioma `por` (Windows: instalador do
UB Mannheim; Linux: `apt install tesseract-ocr tesseract-ocr-por`).

Saída: só contagens e porcentagens. Nenhuma data, horário ou texto de página vai para o
terminal ou para o JSON. Com --save-crops, grava as faixas que seriam enviadas (é o próprio
conteúdo que sairia do servidor; serve para inspecionar a trava).

Gabarito: mesmo formato de scripts/evaluate_extraction.py; só "time_cards" é usado
(clock_in/clock_out; o intervalo pré-assinalado não é extraído). Marcação única
("Esquecimento") entra com o outro horário null.

Uso (a partir de backend/):
  python scripts/evaluate_cell_fallback.py gabarito.json folha1.jpg folha2.jpg
  python scripts/evaluate_cell_fallback.py gabarito.json processo.pdf --pages 115-118
  python scripts/evaluate_cell_fallback.py gabarito.json folha*.jpg --save-crops faixas/
  python scripts/evaluate_cell_fallback.py gabarito.json folha*.jpg --send   # chama o Gemini

Sem --send nada sai da máquina: o relatório mostra quantas faixas e células seriam enviadas.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import settings  # noqa: E402
from evaluate_extraction import parse_ground_truth  # noqa: E402
from pipeline.classifier import STRIPS_PER_CALL, GeminiDocumentClassifier  # noqa: E402
from pipeline.time_card_ocr import (  # noqa: E402
    TimeCardReader,
    apply_gemini,
    build_strips,
    passes_gate,
    plausible,
    summary,
    tesseract_available,
    tesseract_runner,
)


@dataclass
class Outcome:
    correct: int = 0
    review: int = 0
    silent_errors: int = 0

    def add(self, predicted: str | None, expected: str) -> None:
        if predicted is None:
            self.review += 1
        elif predicted == expected:
            self.correct += 1
        else:
            self.silent_errors += 1


@dataclass
class Report:
    pages: int
    pages_unrecognized: int
    expected_times: int
    seconds_local: float
    seconds_gemini: float | None
    cells_detected: int
    cells_doubtful: int
    cells_blocked_by_gate: int
    strips: int
    cells_in_strips: int
    gemini_calls: int
    gemini_correct_on_doubtful: int | None
    gemini_null_on_doubtful: int | None
    gemini_wrong_on_doubtful: int | None
    unread_days: int
    times_on_days_off: int
    strategies: dict[str, dict[str, int]]


def _pdf_from_inputs(inputs: list[Path], folder: Path) -> Path:
    if len(inputs) == 1 and inputs[0].suffix.lower() == ".pdf":
        return inputs[0]
    document = fitz.open()
    for path in inputs:
        with fitz.open(path) as image:
            page_pdf = fitz.open("pdf", image.convert_to_pdf())
        document.insert_pdf(page_pdf)
    target = folder / "folhas.pdf"
    document.save(target)
    document.close()
    return target


def evaluate(args: argparse.Namespace) -> Report:
    if not tesseract_available(args.tesseract):
        raise SystemExit("Tesseract (com o idioma por) não encontrado (veja o topo do script).")
    truth = parse_ground_truth(json.loads(args.gabarito.read_text(encoding="utf-8")))
    expected = {
        (row.date, slot): value
        for row in truth.time_cards
        for slot, value in enumerate((row.times.get("clock_in"), row.times.get("clock_out")))
        if value
    }

    with tempfile.TemporaryDirectory() as folder:
        pdf_path = _pdf_from_inputs(args.inputs, Path(folder))
        with fitz.open(pdf_path) as document:
            first, last = (int(v) for v in args.pages.split("-")) if args.pages else (1, document.page_count)
            pages = list(range(first, min(last, document.page_count) + 1))
        started = time.perf_counter()
        local = TimeCardReader(tesseract_runner(args.tesseract), workers=args.workers).read(pdf_path, pages)
        seconds_local = time.perf_counter() - started

    cells = [cell for page in local.pages for cell in page.cells]
    columns = {id(cell): page.columns for page in local.pages for cell in page.cells}
    local_consensus = {id(cell): cell.value for cell in cells}
    doubtful = [cell for cell in cells if cell.value is None]
    strips = build_strips(local.pages)
    in_strips = {id(cell) for strip in strips for cell in strip.cells}

    if args.save_crops:
        args.save_crops.mkdir(parents=True, exist_ok=True)
        for strip in strips:
            (args.save_crops / f"{strip.strip_id}.png").write_bytes(strip.png())

    seconds_gemini: float | None = None
    calls = 0
    if args.send and strips:
        if not settings.gemini_api_key:
            raise SystemExit("--send exige GEMINI_API_KEY no .env.")
        classifier = GeminiDocumentClassifier(api_key=settings.gemini_api_key, model_name=args.model)
        started = time.perf_counter()
        calls = classifier.read_strips(strips)
        seconds_gemini = time.perf_counter() - started
        apply_gemini(cells, local.schedule)

    strategies = {"local_1_leitura": Outcome(), "local_consenso": Outcome()}
    if args.send:
        strategies["pipeline"] = Outcome()
    gemini = {"correct": 0, "null": 0, "wrong": 0}
    found: set[tuple[str, int]] = set()
    for cell in cells:
        key = (cell.day, cell.slot)
        if key not in expected or key in found:
            continue
        found.add(key)
        want = expected[key]
        first = cell.first_read if plausible(cell.first_read, cell, local.schedule, require_schedule=False) else None
        strategies["local_1_leitura"].add(first, want)
        strategies["local_consenso"].add(local_consensus[id(cell)], want)
        if args.send:
            strategies["pipeline"].add(cell.value, want)
            if local_consensus[id(cell)] is None and id(cell) in in_strips:
                outcome = "null" if cell.gemini_read is None else "correct" if cell.gemini_read == want else "wrong"
                gemini[outcome] += 1
    for outcome in strategies.values():  # horário do gabarito sem célula detectada = revisão
        outcome.review += len(expected) - len(found)

    expected_days = {day for day, _ in expected}
    counts = summary(local)
    return Report(
        pages=len(pages),
        pages_unrecognized=counts["unrecognized"],
        expected_times=len(expected),
        seconds_local=round(seconds_local, 1),
        seconds_gemini=round(seconds_gemini, 1) if seconds_gemini is not None else None,
        cells_detected=len(cells),
        cells_doubtful=len(doubtful),
        cells_blocked_by_gate=sum(not passes_gate(cell, columns[id(cell)]) for cell in doubtful),
        strips=len(strips),
        cells_in_strips=len(in_strips),
        gemini_calls=calls,
        gemini_correct_on_doubtful=gemini["correct"] if args.send else None,
        gemini_null_on_doubtful=gemini["null"] if args.send else None,
        gemini_wrong_on_doubtful=gemini["wrong"] if args.send else None,
        unread_days=counts["unread_days"],
        times_on_days_off=sum(1 for cell in cells if cell.day not in expected_days and cell.value),
        strategies={name: asdict(outcome) for name, outcome in strategies.items()},
    )


def _pct(part: int, total: int) -> str:
    return f"{100 * part / total:.0f}%" if total else "-"


def format_report(report: Report) -> str:
    total = report.expected_times
    lines = [
        f"Páginas: {report.pages} (não reconhecidas como cartão: {report.pages_unrecognized})",
        f"Horários no gabarito: {total}  |  células detectadas: {report.cells_detected}"
        f"  |  dias do período sem linha lida: {report.unread_days}",
        f"Tempo local (OCR + releituras + trava): {report.seconds_local} s",
        "",
        f"{'estratégia':20s} {'corretos':>10s} {'revisão':>10s} {'errados sem aviso':>18s}",
    ]
    for name, outcome in report.strategies.items():
        lines.append(
            f"{name:20s} {_pct(outcome['correct'], total):>10s} {_pct(outcome['review'], total):>10s}"
            f" {outcome['silent_errors']:>18d}"
        )
    lines += [
        "",
        f"Células duvidosas: {report.cells_doubtful}  |  barradas pela trava: {report.cells_blocked_by_gate}",
        f"Faixas: {report.strips} com {report.cells_in_strips} células no total"
        f" ({STRIPS_PER_CALL} faixas por chamada)",
        f"Horários aceitos em dias sem jornada no gabarito: {report.times_on_days_off}",
    ]
    if report.seconds_gemini is not None:
        lines.append(
            f"Gemini: {report.gemini_calls} chamada(s), {report.seconds_gemini} s; nas duvidosas enviadas:"
            f" corretas {report.gemini_correct_on_doubtful}, null {report.gemini_null_on_doubtful},"
            f" erradas {report.gemini_wrong_on_doubtful} (a checagem da jornada ainda filtra as erradas)"
        )
    else:
        lines.append("Simulação: nada foi enviado. Use --send para medir com o Gemini.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gabarito", type=Path)
    parser.add_argument("inputs", type=Path, nargs="+", help="imagens das folhas ou um PDF")
    parser.add_argument("--pages", help="intervalo de páginas do PDF, ex.: 115-118")
    parser.add_argument("--send", action="store_true", help="envia as faixas aprovadas ao Gemini")
    parser.add_argument("--model", default=settings.gemini_model)
    parser.add_argument("--tesseract", default=settings.tesseract_cmd, help="caminho do binário")
    parser.add_argument("--save-crops", type=Path, help="grava as faixas que seriam enviadas")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    parser.add_argument("--json", type=Path, help="grava as métricas (só números) em JSON")
    args = parser.parse_args(argv)
    if args.tesseract == "tesseract" and not shutil.which("tesseract"):
        windows = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if windows.exists():
            args.tesseract = str(windows)

    report = evaluate(args)
    print(format_report(report))
    if args.json:
        args.json.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
