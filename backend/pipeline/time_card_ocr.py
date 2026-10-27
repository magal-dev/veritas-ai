"""Cartão de ponto escaneado lido no servidor: OCR local + faixas anônimas para o Gemini.

A página do cartão nunca sai do servidor. Fluxo por página visual candidata:

1. OCR local (Tesseract) da página inteira; regras do layout montam a tabela dia → horários.
   Página sem o período impresso ou sem a tabela não é reconhecida e segue o caminho normal.
   Página reconhecida cujas linhas não confirmam as datas (folha curta, meses ilegíveis)
   continua aqui: os horários seguem este fluxo e a data de cada registro vai para a revisão
   (`date` em `ambiguous_fields`; a exportação não leva o dia até o perito confirmar).
2. Cada célula é relida em recorte, só dígitos (com e sem binarização). Três leituras iguais
   e perto da jornada observada = valor aceito localmente.
3. Células duvidosas que passam na trava (tamanho de uma célula da coluna, com tinta, sem
   letras) vão ao Gemini empilhadas por coluna, em ordem embaralhada, sem data, nome ou
   cabeçalho. O vínculo linha → dia fica só em memória. A resposta só vale se cair perto
   da jornada.
4. O que continuar duvidoso fica vazio e marcado em `ambiguous_fields` para a revisão, com o
   recorte da célula guardado na sessão. Nada é chutado.

Layout suportado: colunas "Data | Dia | Ent1 Sai1 ..." e o período "dd/mm/aaaa à dd/mm/aaaa"
(medido em folhas reais com scripts/evaluate_cell_fallback.py). Outros layouts não são
reconhecidos e continuam no Gemini com a página inteira.

Logs só com contagens. Datas, horários e textos de página não saem deste módulo.
"""

from __future__ import annotations

import io
import os
import random
import re
import secrets
import shutil
import subprocess
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any

import pymupdf as fitz
from PIL import Image, ImageFilter, ImageOps

from core.logging import logger
from schemas.extraction import TimeCardEntry

WEEKDAYS = ("SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM")
# Leituras do Tesseract que a comparação letra a letra não desempata (SES: SEG ou SEX?).
WEEKDAY_OCR = {"SES": "SEG", "SE3": "SEG", "SEK": "SEX", "QUT": "QUI", "QÜI": "QUI"}
# Linha sem jornada: folga "DESC(00:00 - 23:59)" (e leituras como "CESTI00S00 - 23359)"),
# não admitido, liberado, feriado.
NO_WORK = re.compile(r"DES|ESC|EST|23.?59\)|N[aã]o Adm|Liberad|SENHORA|SRA\.|FERIAD", re.I)
SINGLE_MARK = re.compile(r"\*|Esquec", re.I)
PERIOD = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*[àaÀ]\s*(\d{2})/(\d{2})/(\d{4})")
TABLE_END = re.compile(r"Sald|Hor[aá]rio do Func", re.I)
TWO_TIMES = re.compile(r"(\d{2}[:;.]\d{2}).+?(\d{2}[:;.]\d{2})")
OCR_DIGITS = str.maketrans({"O": "0", "C": "0", "D": "0", "Q": "0", "B": "8", "€": "8", "$": "5"})
DIGITS_ONLY = ["-c", "tessedit_char_whitelist=0123456789:"]

TARGET_HEIGHT = 3200  # altura da página para o OCR: ~ 290 DPI numa folha A4/carta
MIN_ROWS = 5  # menos linhas com dia da semana que isso: não é a tabela do cartão
CELL_PAD = 4
STACK_BORDER = 12
STACK_GAP = 24
TOLERANCE_MIN = 75  # distância máxima da jornada observada para aceitar um horário
MIN_SCHEDULE_SAMPLES = 3
INK_THRESHOLD = 128
MIN_INK_RATIO = 0.04
CONFIDENCE_LOCAL = 0.95
CONFIDENCE_WITH_GEMINI = 0.85
CONFIDENCE_PENDING = 0.3

STRIP_PROMPT = """Cada imagem a seguir é uma faixa vertical de uma coluna de tabela impressa por relógio
de ponto (matricial, às vezes falhado ou borrado), precedida pelo id da faixa e pelo número de
linhas. Cada linha tem um horário HH:mm. Todas usam a mesma fonte: compare os dígitos entre
linhas para ler os apagados. Pares que se confundem nessa impressão: 0/8, 3/8, 5/6, 1/7, 0/9.
Se um dígito de uma linha puder ser um desses pares mesmo após comparar com as outras, ou
estiver incompleto, use null nessa linha. Um null é muito melhor que um valor errado: não
adivinhe e não complete pela sequência.
Responda SOMENTE com JSON, com os valores de cada faixa de cima para baixo e exatamente o
número de linhas informado:
{"strips": [{"id": "<id>", "values": ["HH:mm" | null, ...]}]}"""


# ---------------------------------------------------------------- OCR


@dataclass
class Word:
    x: int
    y: int
    w: int
    h: int
    text: str
    line: tuple[str, ...] = ()


OcrRunner = Callable[[Image.Image, list[str]], str]


def tesseract_runner(command: str) -> OcrRunner:
    def run(image: Image.Image, args: list[str]) -> str:
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        # Paralelismo é por página; threads internas do Tesseract só disputariam CPU.
        env = {**os.environ, "OMP_THREAD_LIMIT": "1"}
        result = subprocess.run(
            [command, "stdin", "stdout", *args],
            input=buffer.getvalue(),
            capture_output=True,
            check=True,
            env=env,
            timeout=120,
        )
        return result.stdout.decode("utf-8", errors="replace")

    return run


@lru_cache(maxsize=4)
def tesseract_available(command: str) -> bool:
    """Binário no PATH e com o idioma `por` instalado."""
    if not shutil.which(command):
        return False
    try:
        result = subprocess.run(
            [command, "--list-langs"], capture_output=True, check=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    return "por" in output.split()


def parse_tsv(output: str) -> list[Word]:
    words: list[Word] = []
    for row in output.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        words.append(
            Word(
                int(cols[6]), int(cols[7]), int(cols[8]), int(cols[9]),
                cols[11].strip(), line=(cols[2], cols[3], cols[4]),
            )
        )
    return words


def group_lines(words: Iterable[Word]) -> list[list[Word]]:
    groups: dict[tuple[str, ...], list[Word]] = {}
    for word in words:
        groups.setdefault(word.line, []).append(word)
    return [sorted(g, key=lambda w: w.x) for g in sorted(groups.values(), key=lambda g: g[0].y)]


def prepare(image: Image.Image) -> Image.Image:
    image = image.convert("L")
    if image.height < TARGET_HEIGHT * 0.9:
        factor = TARGET_HEIGHT / image.height
        image = image.resize((round(image.width * factor), TARGET_HEIGHT), Image.LANCZOS)
    return ImageOps.autocontrast(image, cutoff=2).filter(ImageFilter.MedianFilter(3))


# ---------------------------------------------------------------- regras do layout


def to_time(token: str) -> str | None:
    """Normaliza um horário lido pelo OCR (':' perdido ou lido como 5/4/;)."""
    text = token.strip(".,;|'\"*()").upper().translate(OCR_DIGITS)
    match = (
        re.fullmatch(r"(\d{1,2})[:;.](\d{2})", text)
        or re.fullmatch(r"(\d{2})(\d{2})", text)
        # Cinco caracteres: o do meio é sempre o ':' (lido como 3, 4, 5, 8, '+'...).
        or re.fullmatch(r"(\d{2})[\d+](\d{2})", text)
    )
    if not match:
        return None
    hours, minutes = int(match[1]), int(match[2])
    if not (0 <= hours <= 23 and minutes <= 59):
        return None
    return f"{hours:02d}:{minutes:02d}"


def _minutes(value: str) -> int:
    return int(value[:2]) * 60 + int(value[3:])


def _hhmm(minutes: float) -> str:
    total = int(minutes)
    return f"{total // 60:02d}:{total % 60:02d}"


def weekday_of(token: str) -> str | None:
    """Dia da semana impresso; aceita uma letra trocada se só um dia combinar (GUA → QUA)."""
    letters = re.sub(r"[^A-ZÜ]", "", token.upper())[:3]
    letters = WEEKDAY_OCR.get(letters, letters)
    if letters in WEEKDAYS:
        return letters
    if len(letters) == 2:  # primeira letra perdida na margem ("UA")
        close = [day for day in WEEKDAYS if day.endswith(letters)]
    elif len(letters) == 3:
        close = [day for day in WEEKDAYS if sum(a == b for a, b in zip(day, letters)) == 2]
    else:
        return None
    return close[0] if len(close) == 1 else None


@dataclass
class Cell:
    day: str  # ISO; só em memória
    slot: int  # 0 = entrada, 1 = saída
    box: tuple[int, int, int, int]
    first_read: str | None = None
    single_mark: bool = False  # "Esquecimento": uma marcação só; a posição sai do horário
    rereads: list[str | None] = field(default_factory=list)
    has_letters: bool = False
    ink_ratio: float = 0.0
    crop: Image.Image | None = None
    gemini_read: str | None = None
    value: str | None = None
    source: str | None = None  # "local" | "gemini" | None (revisão)

    @property
    def weekday(self) -> str:
        return WEEKDAYS[date.fromisoformat(self.day).weekday()]

    @property
    def consensus(self) -> str | None:
        reads = [self.first_read, *self.rereads]
        return reads[0] if reads[0] and reads.count(reads[0]) == len(reads) else None


@dataclass
class Columns:
    entry_x: int
    exit_x: int
    width: int
    height: int


@dataclass
class TimeCardPage:
    page_number: int
    rows: int
    columns: Columns
    cells: list[Cell] = field(default_factory=list)
    work_days: list[str] = field(default_factory=list)  # dias com linha de jornada
    unread_days: list[str] = field(default_factory=list)  # dia do período sem linha lida
    # False: layout reconhecido, mas as linhas não confirmam as datas montadas (folha curta,
    # mês ilegível). Os horários seguem lidos aqui; a data de cada registro fica para o perito.
    dates_confirmed: bool = True


@dataclass
class _Row:
    weekday: str
    rest: list[Word]
    fragment: str = ""  # o que vem antes do dia da semana: a data com o dia cortado


def _table_rows(lines: list[list[Word]]) -> list[_Row]:
    rows: list[_Row] = []
    for words in lines:
        if TABLE_END.search(" ".join(w.text for w in words)):
            break
        # Linha da tabela: fragmento de data (com "/") e, logo depois, o dia da semana.
        for index in (1, 2):
            if (
                index < len(words)
                and any("/" in w.text for w in words[:index])
                and (weekday := weekday_of(words[index].text))
            ):
                fragment = " ".join(w.text for w in words[:index])
                rows.append(_Row(weekday, words[index + 1 :], fragment))
                break
    return rows


def _columns(rows: list[_Row]) -> Columns | None:
    """Posição das colunas Ent/Sai a partir das linhas com dois horários legíveis."""
    pairs = [
        row.rest[:2]
        for row in rows
        if len(row.rest) >= 2 and all(to_time(w.text) for w in row.rest[:2])
        and row.rest[0].x < row.rest[1].x
    ]
    if len(pairs) < MIN_SCHEDULE_SAMPLES:
        return None
    return Columns(
        entry_x=round(median(p[0].x for p in pairs)),
        exit_x=round(median(p[1].x for p in pairs)),
        width=round(median(w.w for p in pairs for w in p)),
        height=round(median(w.h for p in pairs for w in p)),
    )


def _is_day_off(row: _Row, columns: Columns) -> bool:
    """Folga, feriado, "Não Admitido"... Só se a coluna de saída não tiver horário: um
    horário de entrada ilegível não pode fazer um dia de trabalho sumir."""
    text = " ".join(w.text for w in row.rest)
    if not NO_WORK.search(text[:30]) or re.match(r"\S{0,3}\d", text):
        return False
    return not any(
        abs(w.x - columns.exit_x) <= columns.width * 0.5 and len(re.findall(r"\d", w.text)) >= 3
        for w in row.rest
    )


def _row_cells(row: _Row, day: str, columns: Columns) -> list[Cell]:
    text = " ".join(w.text for w in row.rest)
    # Palavra mais próxima de cada coluna; traços de borda ("|") não contam.
    near = [
        sorted(
            (w for w in row.rest if abs(w.x - x) <= columns.width * 0.5 and w.w >= columns.width * 0.4),
            key=lambda w, x=x: abs(w.x - x),
        )
        for x in (columns.entry_x, columns.exit_x)
    ]
    y = round(median(w.y for w in row.rest)) if row.rest else 0

    if SINGLE_MARK.search(text):
        token = (near[0] or near[1] or [None])[0]
        if token is None:
            return []
        read = to_time(token.text)
        return [Cell(day, 1 if read and read >= "13:00" else 0, (token.x, token.y, token.w, token.h),
                     first_read=read, single_mark=True)]

    cells: list[Cell] = []
    entry = near[0][0] if near[0] else None
    if entry and not near[1] and entry.w > columns.width * 1.6:
        # Dois horários grudados ("07:58.15:04"): separa pela posição da coluna de saída.
        found = TWO_TIMES.search(entry.text)
        reads = (to_time(found[1]), to_time(found[2])) if found else (None, None)
        right = entry.x + entry.w
        cells.append(Cell(day, 0, (entry.x, entry.y, columns.width, entry.h), first_read=reads[0]))
        cells.append(Cell(day, 1, (columns.exit_x, entry.y, min(columns.width, right - columns.exit_x), entry.h),
                          first_read=reads[1]))
        return cells
    for slot, x in ((0, columns.entry_x), (1, columns.exit_x)):
        token = near[slot][0] if near[slot] else None
        if token is not None:
            cells.append(Cell(day, slot, (token.x, token.y, token.w, token.h), first_read=to_time(token.text)))
        else:
            # Célula sem palavra lida: recorta a posição esperada; a releitura e a trava decidem.
            cells.append(Cell(day, slot, (x, y, columns.width, columns.height)))
    return cells


def _read_period(text: str) -> tuple[date, date, bool] | None:
    """Período impresso: (início, fim, fim lido com segurança).

    O fim costuma sair truncado no OCR ("20/08/2932"); se não for coerente com o início,
    vale o fechamento mensal (início + 1 mês - 1 dia) e a data inicial passa a ser conferida
    pelos meses das linhas (ver _dates_agree).
    """
    found = PERIOD.search(text)
    if not found:
        return None
    try:
        start = date(int(found[3]), int(found[2]), int(found[1]))
    except ValueError:
        return None
    month = start.month % 12 + 1
    year = start.year + (start.month == 12)
    monthly_end = date(year, month, min(start.day, 28)) - timedelta(days=1)
    if start.day > 28:  # fechamento no fim do mês: não há como inferir o dia com segurança
        monthly_end = start + timedelta(days=30)
    try:
        printed_end = date(int(found[6]), int(found[5]), int(found[4]))
    except ValueError:
        return start, monthly_end, False
    if timedelta(days=6) <= printed_end - start <= timedelta(days=62):
        return start, printed_end, True
    return start, monthly_end, False


def _printed_months(rows: list[_Row]) -> list[int | None]:
    """Mês do fragmento de data de cada linha ("1/08/2025" ou "21/08/2025" → 8); None se ilegível."""
    months: list[int | None] = []
    for row in rows:
        text = row.fragment.upper().translate(OCR_DIGITS)
        # Data inteira: o mês é o segundo grupo. Dia cortado na margem: o primeiro.
        found = re.search(r"\d{2}/(\d{2})/\d{2,4}", text) or re.search(r"(\d{2})/\d{2,4}", text)
        months.append(int(found[1]) if found and 1 <= int(found[1]) <= 12 else None)
    return months


def _dates_agree(rows: list[_Row], days: list[date], start: date, one_row_per_day: bool) -> bool:
    """Confere as datas montadas contra o que as próprias linhas mostram.

    Um início mal lido deslocaria todas as datas sem aviso. O mês impresso em cada linha
    tem de bater melhor com as datas montadas do que com qualquer deslocamento delas (o
    período cruza a virada do mês, então um deslocamento muda os meses de algumas linhas;
    o OCR erra meses isolados, por isso a comparação é relativa). Com uma linha por dia,
    os dias da semana lidos também têm de bater; sincronizando pelo dia da semana, a
    primeira linha tem de ser o próprio início.
    """
    months = _printed_months(rows)
    if sum(m is not None for m in months) < MIN_ROWS:
        return False

    def agreement(shift: int) -> int:
        return sum(
            month == (day + timedelta(days=shift)).month
            for month, day in zip(months, days)
            if month is not None
        )

    base = agreement(0)
    if any(agreement(shift) > base for shift in range(-15, 16)):
        return False
    if one_row_per_day:
        same = sum(WEEKDAYS[day.weekday()] == row.weekday for row, day in zip(rows, days))
        return same >= 0.7 * len(rows)
    # Sincronizado pelo dia da semana: a primeira linha tem de cair no próprio início do
    # período (um início mal lido quase sempre obriga a pular dias logo na primeira linha).
    return days[0] == start


def _assign_days(rows: list[_Row], start: date, end: date) -> tuple[list[date], list[date], bool]:
    """(dias do período, data de cada linha, se a ordem das linhas dá a data)."""
    period_days = [start + timedelta(days=n) for n in range((end - start).days + 1)]
    if len(rows) == len(period_days):
        # Uma linha por dia (inclusive folgas e "Não Admitido"): a ordem dá a data, mesmo
        # que o dia da semana tenha sido mal lido.
        return period_days, period_days, True
    # O dia vem cortado na margem; a data sai do período + dia da semana. Sincronizar pelo
    # dia da semana evita que uma linha perdida desloque todas as seguintes.
    days, cursor = [], start
    for row in rows:
        for _ in range(7):
            if WEEKDAYS[cursor.weekday()] == row.weekday:
                break
            cursor += timedelta(days=1)
        days.append(cursor)
        cursor += timedelta(days=1)
    return period_days, days, False


def _year_shift(rows: list[_Row], days: list[date]) -> int:
    """Anos a somar ao período (-1, 0 ou 1) segundo o ano impresso nas linhas."""
    years: list[tuple[int, date]] = []
    for row, day in zip(rows, days):
        found = re.search(r"/\d{2}/(\d{4})", row.fragment.upper().translate(OCR_DIGITS))
        if found:
            years.append((int(found[1]), day))
    if len(years) < MIN_ROWS:
        return 0

    def agreement(shift: int) -> int:
        return sum(year == day.year + shift for year, day in years)

    best = max((-1, 1), key=agreement)
    # Maioria clara: um ano isolado mal lido não move o período.
    return best if agreement(best) > agreement(0) and agreement(best) >= 0.6 * len(years) else 0


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29/02 em ano não bissexto
        return day.replace(year=day.year + years, day=28)


def parse_page(lines: list[list[Word]], page_number: int) -> TimeCardPage | None:
    """Monta a tabela do cartão a partir das linhas do OCR; None se o layout não bater.

    Datas que as próprias linhas não confirmam deixam `dates_confirmed=False`.
    """
    period = _read_period("\n".join(" ".join(w.text for w in words) for words in lines))
    if period is None:
        return None
    start, end, _ = period
    rows = _table_rows(lines)
    columns = _columns(rows)
    if len(rows) < MIN_ROWS or columns is None:
        return None

    page = TimeCardPage(page_number=page_number, rows=len(rows), columns=columns)
    period_days, days, weekdays_count = _assign_days(rows, start, end)
    # Ano do período mal lido ("2025" → "2024"): o ano impresso nas linhas corrige, se bater
    # melhor com as datas deslocadas de um ano do que com as montadas.
    shift = _year_shift(rows, days)
    if shift:
        start, end = _add_years(start, shift), _add_years(end, shift)
        period_days, days, weekdays_count = _assign_days(rows, start, end)
    # Datas não confirmadas (dia da semana mal lido empurrou as datas para fora do período, ou
    # os meses impressos não bastam/não batem) não descartam a página: ela iria inteira ao
    # Gemini. Os horários seguem lidos aqui e a data vai para a revisão.
    page.dates_confirmed = days[-1] <= end and _dates_agree(rows, days, start, weekdays_count)

    for row, day in zip(rows, days):
        if _is_day_off(row, columns):
            continue
        cells = _row_cells(row, day.isoformat(), columns)
        if cells:
            page.cells.extend(cells)
            page.work_days.append(day.isoformat())
    # Dia sem linha lida entre a primeira e a última linha. Depois da última não conta: a
    # folha pode acabar antes do período (desligamento, folha parcial).
    seen = set(days)
    page.unread_days = [
        day.isoformat() for day in period_days if days[0] <= day <= days[-1] and day not in seen
    ]
    return page


# ---------------------------------------------------------------- releitura e trava


def crop_cell(image: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    x, y, w, h = box
    return image.crop((x - CELL_PAD, y - CELL_PAD, x + w + CELL_PAD, y + h + CELL_PAD))


def stack(crops: list[Image.Image], gap: int, border: int = 0, scale: int = 1) -> tuple[Image.Image, list[tuple[int, int]]]:
    """Empilha recortes numa faixa vertical; devolve a faixa e o intervalo y de cada um."""
    tiles = [
        ImageOps.expand(c.resize((c.width * scale, c.height * scale), Image.LANCZOS), border, fill=255)
        for c in crops
    ]
    width = max(t.width for t in tiles)
    strip = Image.new("L", (width, sum(t.height for t in tiles) + gap * (len(tiles) - 1)), 255)
    spans, y = [], 0
    for tile in tiles:
        strip.paste(tile.convert("L"), (0, y))
        spans.append((y, y + tile.height))
        y += tile.height + gap
    return strip, spans


def _texts_by_span(words: list[Word], spans: list[tuple[int, int]]) -> list[str]:
    texts: list[list[Word]] = [[] for _ in spans]
    for word in words:
        center = word.y + word.h / 2
        for index, (top, bottom) in enumerate(spans):
            if top <= center < bottom:
                texts[index].append(word)
                break
    return ["".join(w.text for w in sorted(group, key=lambda w: w.x)) for group in texts]


def reread_cells(cells: list[Cell], run: OcrRunner) -> None:
    """Releituras (só dígitos, com e sem binarização) e texto livre para a trava.

    As células da página vão numa faixa só: três chamadas ao Tesseract por página em vez
    de três por célula.
    """
    if not cells:
        return
    strip, spans = stack([c.crop for c in cells], STACK_GAP, STACK_BORDER, scale=2)  # type: ignore[misc]
    binary = strip.point(lambda p: 255 if p > 150 else 0)
    plain = _texts_by_span(parse_tsv(run(strip, ["--psm", "6", *DIGITS_ONLY, "tsv"])), spans)
    binarized = _texts_by_span(parse_tsv(run(binary, ["--psm", "6", *DIGITS_ONLY, "tsv"])), spans)
    free = _texts_by_span(parse_tsv(run(strip, ["-l", "por", "--psm", "6", "tsv"])), spans)
    for cell, first, second, text in zip(cells, plain, binarized, free):
        cell.rereads = [to_time(first), to_time(second)]
        # Três letras seguidas: palavra ("DESC", nome). Dígito apagado vira uma ou duas letras.
        cell.has_letters = bool(re.search(r"[A-Za-zÀ-ú]{3,}", text))


def ink_ratio(image: Image.Image) -> float:
    histogram = image.convert("L").histogram()
    return sum(histogram[:INK_THRESHOLD]) / max(sum(histogram), 1)


def passes_gate(cell: Cell, columns: Columns) -> bool:
    """Trava antes do envio: o recorte tem de ser uma célula da coluna com um horário e nada mais.

    Mede o tamanho contra a célula típica da própria coluna, exige tinta e recusa letras
    (nome, "DESC", "Justificar"...). Dois horários grudados ou o texto da linha não passam.
    """
    _, _, w, h = cell.box
    return (
        0.8 * columns.width <= w <= 1.3 * columns.width
        and 0.6 * columns.height <= h <= 1.8 * columns.height
        and cell.ink_ratio >= MIN_INK_RATIO
        and not cell.has_letters
    )


# ---------------------------------------------------------------- jornada e decisão


Schedule = dict[str, tuple[str, str]]


def observed_schedule(cells: Iterable[Cell]) -> Schedule:
    """Jornada de referência = mediana das marcações lidas por dia da semana e posição.

    O "Quadro de Horário" impresso sai ruidoso no OCR; as marcações reais se concentram em
    torno da jornada e a mediana ignora as leituras erradas.
    """
    values: dict[tuple[str, int], list[int]] = {}
    for cell in cells:
        if cell.first_read:
            values.setdefault((cell.weekday, cell.slot), []).append(_minutes(cell.first_read))
    schedule: Schedule = {}
    for weekday in WEEKDAYS:
        spans = [sorted(values.get((weekday, slot), [])) for slot in (0, 1)]
        if all(len(span) >= MIN_SCHEDULE_SAMPLES for span in spans):
            schedule[weekday] = (_hhmm(spans[0][len(spans[0]) // 2]), _hhmm(spans[1][len(spans[1]) // 2]))
    return schedule


def plausible(value: str | None, cell: Cell, schedule: Schedule, *, require_schedule: bool) -> bool:
    if not value:
        return False
    if cell.weekday not in schedule:
        return not require_schedule
    expected = schedule[cell.weekday][_slot_for(value, cell)]
    return abs(_minutes(value) - _minutes(expected)) <= TOLERANCE_MIN


def _slot_for(value: str, cell: Cell) -> int:
    return (1 if value >= "13:00" else 0) if cell.single_mark else cell.slot


def resolve_local(cells: Iterable[Cell], schedule: Schedule) -> None:
    """Aceita localmente só o consenso das três leituras que cai perto da jornada."""
    for cell in cells:
        agreed = cell.consensus
        if agreed and plausible(agreed, cell, schedule, require_schedule=False):
            cell.value, cell.source = agreed, "local"
            cell.slot = _slot_for(agreed, cell)


def apply_gemini(cells: Iterable[Cell], schedule: Schedule) -> None:
    """Leitura do Gemini só vale com jornada conhecida e perto dela; senão, revisão.

    Nas células já aceitas localmente (que vão na faixa como contexto), o Gemini é um voto a
    mais: se ele lê outro horário, o consenso do OCR não basta e a célula vai para revisão.
    As três leituras do Tesseract erram juntas quando o pixel é o mesmo.
    """
    for cell in cells:
        if cell.source == "local" and cell.gemini_read and cell.gemini_read != cell.value:
            cell.value, cell.source = None, None
            continue
        # Sem veto das leituras do Tesseract numa célula duvidosa: medido nas folhas reais,
        # vetar o Gemini quando as releituras discordam dele (por maioria, ou só quando as duas
        # concordam entre si) triplicou a revisão sem reduzir os erros sem aviso. Na impressão
        # matricial o Tesseract diverge o tempo todo e o Gemini acerta quase todas.
        if cell.value is None and plausible(cell.gemini_read, cell, schedule, require_schedule=True):
            cell.value, cell.source = cell.gemini_read, "gemini"
            cell.slot = _slot_for(cell.gemini_read, cell)  # type: ignore[arg-type]


# ---------------------------------------------------------------- faixas para o Gemini


@dataclass
class Strip:
    strip_id: str
    cells: list[Cell]  # ordem embaralhada = ordem das linhas na imagem

    def png(self) -> bytes:
        image, _ = stack([c.crop for c in self.cells], gap=8)  # type: ignore[misc]
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        return buffer.getvalue()


def build_strips(pages: list[TimeCardPage]) -> list[Strip]:
    """Uma faixa por coluna (página × entrada/saída) que tenha célula duvidosa.

    Entram todas as células da coluna aprovadas pela trava: as já resolvidas servem de
    contexto (mesma fonte) e a resposta para elas é ignorada.
    """
    strips: list[Strip] = []
    for page in pages:
        columns = page.columns
        for slot in (0, 1):
            # Coluna física da célula: a marcação única ("Esquecimento") fica na de entrada
            # mesmo quando é uma saída.
            members = [
                c for c in page.cells
                if (abs(c.box[0] - columns.exit_x) < abs(c.box[0] - columns.entry_x)) == bool(slot)
                and passes_gate(c, columns)
            ]
            if not any(c.value is None for c in members):
                continue
            random.shuffle(members)  # a ordem das linhas não revela a sequência dos dias
            strips.append(Strip(f"f{secrets.token_hex(3)}", members))
    return strips


def read_strip_answers(payload: dict[str, Any], strips: list[Strip]) -> int:
    """Grava a leitura do Gemini em cada célula; faixa com contagem errada é descartada."""
    by_id = {strip.strip_id: strip for strip in strips}
    accepted = 0
    for item in payload.get("strips", []):
        strip = by_id.get(str(item.get("id")))
        values = item.get("values")
        if strip is None or not isinstance(values, list) or len(values) != len(strip.cells):
            continue
        for cell, value in zip(strip.cells, values):
            cell.gemini_read = to_time(str(value)) if value else None
        accepted += 1
    return accepted


# ---------------------------------------------------------------- leitura das páginas


@dataclass
class LocalTimeCards:
    pages: list[TimeCardPage] = field(default_factory=list)
    schedule: Schedule = field(default_factory=dict)
    unrecognized_pages: list[int] = field(default_factory=list)


def page_image(page: fitz.Page) -> bytes:
    """Pixels da página para o OCR.

    Página escaneada (uma imagem cobrindo quase tudo, sem rotação): a própria imagem embutida,
    ampliada depois com LANCZOS. Renderizar pelo PDF reamostra a imagem e piora a leitura de
    impressão matricial. Nos outros casos, renderiza na altura do OCR.
    """
    images = page.get_images(full=True)
    if len(images) == 1 and page.rotation == 0:
        xref = images[0][0]
        rects = page.get_image_rects(xref)
        area = abs(page.rect)
        if len(rects) == 1 and area and abs(rects[0] & page.rect) / area >= 0.85:
            extracted = page.parent.extract_image(xref)
            if extracted and extracted.get("image"):
                return extracted["image"]
    zoom = TARGET_HEIGHT / max(page.rect.height, 1)
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY).tobytes("png")


class TimeCardReader:
    """OCR local das páginas visuais candidatas; só reconhece o layout descrito no topo."""

    def __init__(self, run: OcrRunner, workers: int | None = None) -> None:
        self._run = run
        self._workers = workers or os.cpu_count() or 2
        self._render_lock = threading.Lock()

    def read(self, pdf_path: Path, page_numbers: list[int]) -> LocalTimeCards:
        result = LocalTimeCards()
        if not page_numbers:
            return result
        with fitz.open(pdf_path) as document:
            with ThreadPoolExecutor(min(self._workers, len(page_numbers))) as pool:
                parsed = list(pool.map(lambda n: self._read_page(document, n), page_numbers))
        for page_number, page in zip(page_numbers, parsed):
            if page is None:
                result.unrecognized_pages.append(page_number)
            else:
                result.pages.append(page)
        cells = [c for page in result.pages for c in page.cells]
        # A jornada sai das páginas com datas confirmadas: numa página sem confirmação o dia
        # da semana de cada linha pode estar deslocado.
        confirmed = [c for page in result.pages if page.dates_confirmed for c in page.cells]
        result.schedule = observed_schedule(confirmed or cells)
        resolve_local(cells, result.schedule)
        return result

    def _read_page(self, document: fitz.Document, page_number: int) -> TimeCardPage | None:
        # fitz.Document não é thread-safe: só o acesso ao PDF fica sob trava.
        with self._render_lock:
            raw = page_image(document[page_number - 1])
        try:
            image = prepare(Image.open(io.BytesIO(raw)))
            lines = group_lines(parse_tsv(self._run(image, ["-l", "por", "--psm", "6", "tsv"])))
            page = parse_page(lines, page_number)
            if page is None:
                return None
            for cell in page.cells:
                cell.crop = crop_cell(image, cell.box)
                cell.ink_ratio = ink_ratio(cell.crop)
            reread_cells(page.cells, self._run)
            return page
        except (OSError, subprocess.SubprocessError):
            logger.warning("time_card_ocr.page_failed page_number=%s", page_number)
            return None


_unavailable_logged: set[str] = set()


def build_time_card_reader(enabled: bool, command: str) -> TimeCardReader | None:
    """Leitor local, ou None (desligado ou sem Tesseract): aí o cartão vai como página."""
    if not enabled:
        return None
    if not tesseract_available(command):
        # A sonda em si já é cacheada; este aviso rodaria de novo a cada request.
        if command not in _unavailable_logged:
            _unavailable_logged.add(command)
            logger.warning("time_card_ocr.unavailable reason=tesseract_or_por_missing")
        return None
    return TimeCardReader(tesseract_runner(command))


# ---------------------------------------------------------------- saída


def review_png(cell: Cell) -> bytes:
    """Recorte ampliado da célula para a revisão (fica só na sessão)."""
    crop = cell.crop or Image.new("L", (1, 1), 255)
    image = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def to_entries(pages: list[TimeCardPage]) -> tuple[list[TimeCardEntry], dict[str, bytes]]:
    """Um registro por dia de jornada; recortes das células que não vieram do consenso local."""
    entries: list[TimeCardEntry] = []
    crops: dict[str, bytes] = {}
    for page in pages:
        date_pending = [] if page.dates_confirmed else ["date"]
        by_day: dict[str, list[Cell]] = {}
        for cell in page.cells:
            by_day.setdefault(cell.day, []).append(cell)
        for day in page.work_days:
            values: dict[str, str | None] = {"clock_in": None, "clock_out": None}
            ambiguous: list[str] = []
            review_crops: dict[str, str] = {}
            sources: set[str | None] = set()
            for cell in by_day.get(day, []):
                name = "clock_in" if cell.slot == 0 else "clock_out"
                if cell.value is not None:
                    values[name] = cell.value
                elif cell.single_mark:
                    ambiguous += [n for n in ("clock_in", "clock_out") if n not in ambiguous]
                elif name not in ambiguous:
                    ambiguous.append(name)
                sources.add(cell.source)
                if cell.source != "local":
                    crop_id = secrets.token_hex(8)
                    crops[crop_id] = review_png(cell)
                    review_crops["clock_in" if cell.single_mark and cell.value is None else name] = crop_id
            if None in sources:
                confidence = CONFIDENCE_PENDING
            elif "gemini" in sources:
                confidence = CONFIDENCE_WITH_GEMINI
            else:
                confidence = CONFIDENCE_LOCAL
            entries.append(
                TimeCardEntry(
                    date=day,
                    competence=day[:7],
                    source_page=page.page_number,
                    confidence=confidence,
                    ambiguous_fields=date_pending + ambiguous,
                    review_crops=review_crops,
                    **values,
                )
            )
        for day in page.unread_days:
            # Dia do período sem linha lida: pode ser jornada ou folga; o perito confere.
            entries.append(
                TimeCardEntry(
                    date=day,
                    competence=day[:7],
                    source_page=page.page_number,
                    confidence=0.0,
                    ambiguous_fields=[*date_pending, "clock_in", "clock_out"],
                )
            )
    return entries, crops


def summary(local: LocalTimeCards) -> dict[str, int]:
    """Contagens para log e para o script de avaliação (nunca valores)."""
    cells = [c for page in local.pages for c in page.cells]
    return {
        "pages": len(local.pages),
        "unrecognized": len(local.unrecognized_pages),
        "dates_unconfirmed": sum(not page.dates_confirmed for page in local.pages),
        "cells": len(cells),
        "local": sum(c.source == "local" for c in cells),
        "gemini": sum(c.source == "gemini" for c in cells),
        "review": sum(c.value is None for c in cells),
        "unread_days": sum(len(page.unread_days) for page in local.pages),
    }
