"""Experimento: OCR local de cartões de ponto + fallback ao Gemini só com recortes de célula.

Avalia uma alternativa à camada 3 em que a página nunca sai do servidor:

1. OCR local (Tesseract) da página inteira e regras de layout montam a tabela (dia → horários).
2. Cada horário é relido no recorte da própria célula (OCR só de dígitos). Leituras que
   concordam e caem perto da jornada contratual são aceitas localmente.
3. As células duvidosas passam por uma trava (proporção de uma célula, sem letras, 3–4
   dígitos). Só as aprovadas vão ao Gemini: imagem da célula, id aleatório, ordem
   embaralhada, sem data, página, nome ou cabeçalho. O vínculo id → dia fica em memória.
4. O que continuar duvidoso fica para revisão humana.

Escrito para o layout de cartão de ponto com colunas "Data | Dia | Ent1 Sai1 ..." e o
período impresso como "dd/mm/aaaa à dd/mm/aaaa". A jornada de referência sai da mediana das
marcações lidas (ou de --jornada). Outros layouts precisam de regras próprias: isto é um experimento, não o
pipeline de produção.

Dependência extra só deste script: o binário do Tesseract com o idioma `por`
(Windows: instalador do UB Mannheim; Linux: `apt install tesseract-ocr tesseract-ocr-por`).
Não entra no `pyproject.toml` porque a aplicação não o usa.

Saída: só contagens e porcentagens. Nenhuma data, horário ou texto de página vai para o
terminal ou para o JSON. Com --save-crops, grava os PNGs das células que seriam enviadas
(é o próprio conteúdo que sairia do servidor; serve para inspecionar a trava).

Gabarito: mesmo formato de scripts/evaluate_extraction.py; só "time_cards" é usado
(clock_in/clock_out; o intervalo pré-assinalado não é extraído). Marcação única
("Esquecimento") entra com o outro horário null.

Uso (a partir de backend/):
  python scripts/evaluate_cell_fallback.py gabarito.json folha1.jpg folha2.jpg
  python scripts/evaluate_cell_fallback.py gabarito.json processo.pdf --pages 115-118
  python scripts/evaluate_cell_fallback.py gabarito.json folha*.jpg --save-crops recortes/
  python scripts/evaluate_cell_fallback.py gabarito.json folha*.jpg --send   # chama o Gemini

Sem --send nada sai da máquina: o relatório mostra quantas células seriam enviadas.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import secrets
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pymupdf as fitz
from PIL import Image, ImageFilter, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.config import settings  # noqa: E402
from evaluate_extraction import parse_ground_truth  # noqa: E402

WEEKDAYS = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]
# Leituras frequentes do Tesseract para os dias da semana em impressão matricial.
WEEKDAY_OCR = {
    "SEK": "SEX", "SES": "SEG", "SE3": "SEG", "SEC": "SEG", "COM": "DOM", "DCM": "DOM",
    "DEM": "DOM", "DOH": "DOM", "CUI": "QUI", "QUT": "QUI", "OUA": "QUA", "CUA": "QUA", "SAE": "SAB",
}
NO_WORK = re.compile(r"DES|ESC|EST\(|23[:;.]?59|N[aã]o Adm|Liberad|SENHORA|SRA\.|FERIAD", re.I)
SINGLE_MARK = re.compile(r"\*|Esquec", re.I)
PERIOD = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*[àaÀ]\s*(\d{2})/(\d{2})/(\d{4})")
TABLE_END = re.compile(r"Sald|Hor[aá]rio do Func", re.I)
OCR_DIGITS = str.maketrans({"O": "0", "C": "0", "D": "0", "Q": "0", "B": "8", "€": "8", "$": "5"})

TARGET_HEIGHT = 3200  # ~ 290 DPI numa folha A4/carta
CELL_PAD = 4
TOLERANCE_MIN = 75  # distância máxima da jornada contratual para aceitar um horário
GEMINI_BATCH = 40
CELL_PROMPT = """Cada imagem a seguir é o recorte de uma única célula de uma tabela impressa e
contém um horário no formato HH:mm (ex.: 08:05). Transcreva exatamente o que está impresso.
Se algum dígito não for legível com segurança, devolva null para aquela célula; não adivinhe.
Responda SOMENTE com JSON: {"cells": [{"id": "<id>", "value": "HH:mm" | null}]}"""


# ---------------------------------------------------------------- OCR


def _tesseract(image: Image.Image, args: list[str]) -> str:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}  # paralelismo é por página, não dentro do Tesseract
    result = subprocess.run(
        ["tesseract", "stdin", "stdout", *args],
        input=buffer.getvalue(), capture_output=True, check=True, env=env,
    )
    return result.stdout.decode("utf-8", errors="replace")


@dataclass
class Word:
    x: int
    y: int
    w: int
    h: int
    text: str


def _ocr_lines(image: Image.Image) -> list[list[Word]]:
    groups: dict[tuple[str, str, str], list[Word]] = {}
    for row in _tesseract(image, ["-l", "por", "--psm", "6", "tsv"]).splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        word = Word(int(cols[6]), int(cols[7]), int(cols[8]), int(cols[9]), cols[11].strip())
        groups.setdefault((cols[2], cols[3], cols[4]), []).append(word)
    return [sorted(g, key=lambda w: w.x) for g in sorted(groups.values(), key=lambda g: g[0].y)]


def _prepare(image: Image.Image) -> Image.Image:
    image = image.convert("L")
    if image.height < TARGET_HEIGHT * 0.9:
        factor = TARGET_HEIGHT / image.height
        image = image.resize((round(image.width * factor), TARGET_HEIGHT), Image.LANCZOS)
    return ImageOps.autocontrast(image, cutoff=2).filter(ImageFilter.MedianFilter(3))


def load_pages(paths: list[Path], page_range: tuple[int, int] | None) -> list[Image.Image]:
    images: list[Image.Image] = []
    for path in paths:
        if path.suffix.lower() == ".pdf":
            with fitz.open(path) as document:
                first, last = page_range or (1, document.page_count)
                for number in range(first - 1, min(last, document.page_count)):
                    pixmap = document[number].get_pixmap(dpi=300, colorspace=fitz.csGRAY)
                    images.append(Image.open(io.BytesIO(pixmap.tobytes("png"))))
        else:
            images.append(Image.open(path))
    return [_prepare(image) for image in images]


# ---------------------------------------------------------------- regras do layout


def to_time(token: str) -> str | None:
    """Normaliza um horário lido pelo OCR (':' perdido ou lido como 5/4/;)."""
    text = token.strip(".,;|'\"*()").upper().translate(OCR_DIGITS)
    match = (
        re.fullmatch(r"(\d{1,2})[:;.](\d{2})", text)
        or re.fullmatch(r"(\d{2})(\d{2})", text)
        or re.fullmatch(r"(\d{2})[54+](\d{2})", text)
    )
    if not match:
        return None
    hours, minutes = int(match[1]), int(match[2])
    if not (0 <= hours <= 23 and minutes <= 59):
        return None
    return f"{hours:02d}:{minutes:02d}"


def _minutes(value: str) -> int:
    return int(value[:2]) * 60 + int(value[3:])


def _weekday(token: str) -> str | None:
    letters = re.sub(r"[^A-Z]", "", token.upper())[:3]
    letters = WEEKDAY_OCR.get(letters, letters)
    return letters if letters in WEEKDAYS else None


Schedule = dict[str, tuple[str, str]]


def parse_schedule_arg(raw: str) -> Schedule:
    """'SEG,QUI=10:00-17:00;TER,QUA,SEX=08:00-15:00' → {dia: (início, fim)}."""
    schedule: Schedule = {}
    for part in filter(None, raw.split(";")):
        days, span = part.split("=")
        start, end = (to_time(value) for value in span.split("-"))
        if not start or not end:
            raise ValueError("--jornada inválida")
        for day in days.split(","):
            schedule[day.strip().upper()] = (start, end)
    return schedule


def observed_schedule(cells: list[Cell]) -> Schedule:
    """Jornada de referência = mediana das marcações lidas por dia da semana e posição.

    O 'Quadro de Horário' impresso sai ruidoso no OCR; as marcações reais se concentram em
    torno da jornada e a mediana ignora as leituras erradas. Vale para qualquer layout.
    """
    values: dict[tuple[str, int], list[int]] = {}
    for cell in cells:
        if cell.first_read:
            values.setdefault((cell.weekday, cell.slot), []).append(_minutes(cell.first_read))
    schedule: Schedule = {}
    for weekday in WEEKDAYS:
        spans = [sorted(values.get((weekday, slot), [])) for slot in (0, 1)]
        if all(len(span) >= 3 for span in spans):
            start, end = (span[len(span) // 2] for span in spans)
            schedule[weekday] = (f"{start // 60:02d}:{start % 60:02d}", f"{end // 60:02d}:{end % 60:02d}")
    return schedule


@dataclass
class Cell:
    day: str  # ISO; fica só em memória
    slot: int  # 0 = entrada, 1 = saída
    weekday: str
    box: tuple[int, int, int, int]
    page_index: int
    first_read: str | None = None
    rereads: list[str | None] = field(default_factory=list)


@dataclass
class PageParse:
    period_found: bool
    rows: int = 0
    cells: list[Cell] = field(default_factory=list)


def parse_page(image: Image.Image, page_index: int) -> PageParse:
    lines = _ocr_lines(image)
    full_text = "\n".join(" ".join(w.text for w in words) for words in lines)
    period = PERIOD.search(full_text)
    result = PageParse(period_found=bool(period))
    if not period:
        return result
    cursor = date(int(period[3]), int(period[2]), int(period[1]))

    rows: list[tuple[str, list[Word]]] = []
    for words in lines:
        text = " ".join(w.text for w in words)
        if TABLE_END.search(text):
            break
        # Linha da tabela: fragmento de data e, logo depois, o dia da semana.
        index = next((i for i, w in enumerate(words[:3]) if _weekday(w.text)), None)
        if index in (None, 0):
            continue
        rows.append((_weekday(words[index].text), words[index + 1:]))  # type: ignore[arg-type]
    result.rows = len(rows)

    for weekday, rest in rows:
        # O dia vem cortado na margem; a data sai do período + dia da semana. Sincronizar
        # pelo dia da semana evita que uma linha perdida desloque todas as seguintes.
        for _ in range(7):
            if WEEKDAYS[cursor.weekday()] == weekday:
                break
            cursor += timedelta(days=1)
        day, cursor = cursor.isoformat(), cursor + timedelta(days=1)
        text = " ".join(w.text for w in rest)
        if NO_WORK.search(text[:30]) and not re.match(r"\S{0,3}\d", text):
            continue
        boxes = [w for w in rest[:3] if re.search(r"\d.*\d", w.text)][:2]
        if not boxes:
            continue
        if SINGLE_MARK.search(text):
            read = to_time(boxes[0].text)
            slots = [1 if read and read >= "13:00" else 0]
        else:
            slots = [0, 1]
        for slot, word in zip(slots, boxes):
            result.cells.append(Cell(day, slot, weekday, (word.x, word.y, word.w, word.h), page_index,
                                     first_read=to_time(word.text)))
    return result


def crop_cell(image: Image.Image, cell: Cell) -> Image.Image:
    x, y, w, h = cell.box
    return image.crop((x - CELL_PAD, y - CELL_PAD, x + w + CELL_PAD, y + h + CELL_PAD))


def reread(image: Image.Image, cell: Cell) -> list[str | None]:
    """Duas leituras independentes só da célula, restritas a dígitos e ':'."""
    crop = crop_cell(image, cell)
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    args = ["--psm", "7", "-c", "tessedit_char_whitelist=0123456789:"]
    plain = _tesseract(crop, args).strip()
    binary = _tesseract(crop.point(lambda p: 255 if p > 150 else 0), args).strip()
    return [to_time(plain), to_time(binary)]


def plausible(value: str | None, weekday: str, slot: int, schedule: Schedule) -> str | None:
    if not value:
        return None
    if weekday not in schedule:  # sem jornada conhecida, só o formato vale
        return value
    expected = schedule[weekday][slot]
    return value if abs(_minutes(value) - _minutes(expected)) <= TOLERANCE_MIN else None


def cell_gate(image: Image.Image, cell: Cell) -> bool:
    """Trava antes do envio: o recorte tem de ser uma célula com um horário e nada mais."""
    crop = crop_cell(image, cell)
    if not 1.8 <= crop.width / max(crop.height, 1) <= 3.8:  # dois horários grudados, texto da linha
        return False
    free_text = _tesseract(crop, ["-l", "por", "--psm", "7"])
    if re.search(r"[A-Za-zÀ-ú]{2,}", free_text):  # letras: nome, "DESC", "Justificar"...
        return False
    digits = re.sub(r"\D", "", _tesseract(crop, ["--psm", "7", "-c", "tessedit_char_whitelist=0123456789:"]))
    return 3 <= len(digits) <= 4


# ---------------------------------------------------------------- Gemini (só células)


def ask_gemini(crops: dict[str, Image.Image], model: str) -> tuple[dict[str, str | None], int]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
    ids = list(crops)
    random.shuffle(ids)  # a ordem não revela a sequência dos dias
    answers: dict[str, str | None] = {}
    calls = 0
    for start in range(0, len(ids), GEMINI_BATCH):
        contents: list[Any] = [CELL_PROMPT]
        for cell_id in ids[start:start + GEMINI_BATCH]:
            buffer = io.BytesIO()
            crops[cell_id].save(buffer, "PNG")
            contents += [f"Célula {cell_id}:", types.Part.from_bytes(data=buffer.getvalue(), mime_type="image/png")]
        response = client.models.generate_content(model=model, contents=contents, config=config)
        calls += 1
        payload = json.loads(re.sub(r"^```(?:json)?|```$", "", (response.text or "").strip()))
        for item in payload.get("cells", []):
            if item.get("id") in crops:
                answers[item["id"]] = to_time(str(item["value"])) if item.get("value") else None
    return answers, calls


# ---------------------------------------------------------------- avaliação


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
    pages_without_period: int
    expected_times: int
    seconds_local: float
    seconds_gemini: float | None
    cells_detected: int
    cells_doubtful: int
    cells_blocked_by_gate: int
    cells_sent: int
    gemini_calls: int
    gemini_correct_on_sent: int | None
    invented_on_days_off: int
    schedule_source: str
    strategies: dict[str, dict[str, int]]


def evaluate(args: argparse.Namespace) -> Report:
    if not shutil.which("tesseract"):
        raise SystemExit("Tesseract não encontrado no PATH (veja o topo do script).")
    truth = parse_ground_truth(json.loads(args.gabarito.read_text(encoding="utf-8")))
    expected = {
        (row.date, slot): value
        for row in truth.time_cards
        for slot, value in enumerate((row.times.get("clock_in"), row.times.get("clock_out")))
        if value
    }
    page_range = tuple(int(v) for v in args.pages.split("-")) if args.pages else None

    started = time.perf_counter()
    images = load_pages(args.inputs, page_range)  # type: ignore[arg-type]
    with ThreadPoolExecutor(args.workers) as pool:
        parsed = list(pool.map(lambda item: parse_page(item[1], item[0]), enumerate(images)))
        cells = [cell for page in parsed for cell in page.cells]
        rereads = list(pool.map(lambda c: reread(images[c.page_index], c), cells))
    for cell, reads in zip(cells, rereads):
        cell.rereads = reads

    if args.jornada:
        schedule, schedule_source = parse_schedule_arg(args.jornada), "--jornada"
    else:
        schedule, schedule_source = observed_schedule(cells), "mediana das marcações lidas"

    local_single: dict[int, str | None] = {}
    local_consensus: dict[int, str | None] = {}
    doubtful: list[int] = []
    for index, cell in enumerate(cells):
        local_single[index] = plausible(cell.first_read, cell.weekday, cell.slot, schedule)
        reads = [cell.first_read, *cell.rereads]
        agreed = reads[0] if reads[0] and reads.count(reads[0]) == len(reads) else None
        local_consensus[index] = plausible(agreed, cell.weekday, cell.slot, schedule)
        if local_consensus[index] is None:
            doubtful.append(index)

    gate_ok = list(ThreadPoolExecutor(args.workers).map(lambda i: cell_gate(images[cells[i].page_index], cells[i]),
                                                        doubtful))
    to_send = {f"c{secrets.token_hex(3)}": i for i, ok in zip(doubtful, gate_ok) if ok}
    seconds_local = time.perf_counter() - started

    if args.save_crops:
        args.save_crops.mkdir(parents=True, exist_ok=True)
        for cell_id, index in to_send.items():
            crop_cell(images[cells[index].page_index], cells[index]).save(args.save_crops / f"{cell_id}.png")

    gemini: dict[int, str | None] = {}
    seconds_gemini: float | None = None
    calls = 0
    if args.send and to_send:
        if not settings.gemini_api_key:
            raise SystemExit("--send exige GEMINI_API_KEY no .env.")
        started = time.perf_counter()
        crops = {cell_id: crop_cell(images[cells[i].page_index], cells[i]) for cell_id, i in to_send.items()}
        answers, calls = ask_gemini(crops, args.model)
        seconds_gemini = time.perf_counter() - started
        gemini = {index: answers.get(cell_id) for cell_id, index in to_send.items()}

    strategies = {
        "local_1_leitura": Outcome(),
        "local_consenso": Outcome(),
        "local_consenso+gemini_celula": Outcome(),
    }
    gemini_correct = 0
    found: set[tuple[str, int]] = set()
    for index, cell in enumerate(cells):
        key = (cell.day, cell.slot)
        if key not in expected or key in found:
            continue
        found.add(key)
        want = expected[key]
        strategies["local_1_leitura"].add(local_single[index], want)
        strategies["local_consenso"].add(local_consensus[index], want)
        fallback = local_consensus[index]
        if fallback is None and index in gemini:
            fallback = plausible(gemini[index], cell.weekday, cell.slot, schedule)
            gemini_correct += gemini[index] == want
        strategies["local_consenso+gemini_celula"].add(fallback, want)
    for outcome in strategies.values():  # horário do gabarito sem célula detectada = revisão
        outcome.review += len(expected) - len(found)

    expected_days = {day for day, _ in expected}
    invented = sum(
        1 for index, cell in enumerate(cells)
        if cell.day not in expected_days and local_single[index] is not None
    )
    return Report(
        pages=len(images),
        pages_without_period=sum(not page.period_found for page in parsed),
        expected_times=len(expected),
        seconds_local=round(seconds_local, 1),
        seconds_gemini=round(seconds_gemini, 1) if seconds_gemini is not None else None,
        cells_detected=len(cells),
        cells_doubtful=len(doubtful),
        cells_blocked_by_gate=len(doubtful) - len(to_send),
        cells_sent=len(to_send) if args.send else 0,
        gemini_calls=calls,
        gemini_correct_on_sent=gemini_correct if args.send else None,
        invented_on_days_off=invented,
        schedule_source=schedule_source,
        strategies={name: asdict(outcome) for name, outcome in strategies.items()},
    )


def _pct(part: int, total: int) -> str:
    return f"{100 * part / total:.0f}%" if total else "-"


def format_report(report: Report, sent: bool) -> str:
    total = report.expected_times
    lines = [
        f"Páginas: {report.pages} (sem período detectado: {report.pages_without_period})",
        f"Jornada usada na checagem: {report.schedule_source}",
        f"Horários no gabarito: {total}  |  células detectadas: {report.cells_detected}",
        f"Tempo local (OCR + releituras + trava): {report.seconds_local} s",
        "",
        f"{'estratégia':32s} {'corretos':>10s} {'revisão':>10s} {'errados sem aviso':>18s}",
    ]
    for name, outcome in report.strategies.items():
        if name.endswith("gemini_celula") and not sent:
            continue
        lines.append(
            f"{name:32s} {_pct(outcome['correct'], total):>10s} {_pct(outcome['review'], total):>10s}"
            f" {outcome['silent_errors']:>18d}"
        )
    lines += [
        "",
        f"Células duvidosas: {report.cells_doubtful}  |  barradas pela trava: {report.cells_blocked_by_gate}"
        f"  |  aptas a enviar: {report.cells_doubtful - report.cells_blocked_by_gate}",
        f"Horários extraídos em dias sem jornada no gabarito: {report.invented_on_days_off}",
    ]
    if sent:
        lines.append(
            f"Gemini: {report.cells_sent} células em {report.gemini_calls} chamada(s), {report.seconds_gemini} s;"
            f" corretas: {report.gemini_correct_on_sent}/{report.cells_sent}"
        )
    else:
        lines.append("Simulação: nada foi enviado. Use --send para medir o fallback com o Gemini.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("gabarito", type=Path)
    parser.add_argument("inputs", type=Path, nargs="+", help="imagens das folhas ou um PDF")
    parser.add_argument("--pages", help="intervalo de páginas do PDF, ex.: 115-118")
    parser.add_argument("--jornada", help="ex.: 'SEG,QUI=10:00-17:00;TER,QUA,SEX=08:00-15:00'")
    parser.add_argument("--send", action="store_true", help="envia as células aprovadas ao Gemini")
    parser.add_argument("--model", default=settings.gemini_model)
    parser.add_argument("--save-crops", type=Path, help="grava as células que seriam enviadas")
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    parser.add_argument("--json", type=Path, help="grava as métricas (só números) em JSON")
    args = parser.parse_args(argv)

    report = evaluate(args)
    print(format_report(report, sent=args.send))
    if args.json:
        args.json.write_text(json.dumps(asdict(report), indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
