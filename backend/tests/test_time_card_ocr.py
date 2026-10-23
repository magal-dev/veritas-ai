import io
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pymupdf as fitz
import pytest
from PIL import Image

from pipeline import time_card_ocr as ocr
from pipeline.time_card_ocr import (
    Cell,
    Columns,
    LocalTimeCards,
    TimeCardPage,
    TimeCardReader,
    Word,
    apply_gemini,
    build_strips,
    build_time_card_reader,
    observed_schedule,
    parse_page,
    passes_gate,
    read_strip_answers,
    reread_cells,
    resolve_local,
    stack,
    to_entries,
    to_time,
    weekday_of,
)

COLUMNS = Columns(entry_x=369, exit_x=465, width=76, height=21)
WEEKDAY_NAMES = ["SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM"]
START = date(2025, 7, 21)  # segunda-feira
END = date(2025, 8, 20)


def _word(x: int, y: int, text: str, w: int = 76, h: int = 21) -> Word:
    return Word(x, y, w, h, text, line=(str(y),))


def _schedule_for(day: date) -> tuple[str, str]:
    return ("10:00", "17:00") if day.weekday() in (0, 3) else ("08:00", "15:00")


def _row(y: int, day: date, *cells: Word, weekday: str | None = None) -> list[Word]:
    return [
        _word(90, y, f"{str(day.day)[-1]}/{day.month:02d}/{day.year}", w=134),
        _word(280, y, weekday or WEEKDAY_NAMES[day.weekday()], w=47),
        *cells,
    ]


def _sheet(
    start: date = START,
    end: date = END,
    *,
    skip: set[date] = frozenset(),  # type: ignore[assignment]
    overrides: dict[date, list[Word]] | None = None,
    weekdays: dict[date, str] | None = None,
    period: str | None = None,
) -> list[list[Word]]:
    """Linhas de OCR de uma folha do layout suportado: período, tabela e rodapé."""
    overrides = overrides or {}
    weekdays = weekdays or {}
    lines = [
        [_word(90, 100, "Cartão", w=80), _word(180, 100, "de", w=30), _word(220, 100, "Ponto", w=70)],
        [
            _word(90, 140, "Período:", w=100),
            *[_word(200 + 120 * i, 140, t, w=110) for i, t in enumerate(
                (period or f"{start:%d/%m/%Y} à {end:%d/%m/%Y}").split()
            )],
        ],
    ]
    y = 300
    day = start
    while day <= end:
        if day not in skip:
            if day in overrides:
                cells = overrides[day]
            elif day.weekday() >= 5:
                cells = [_word(368, y, "DESC(00:00", w=156), _word(543, y, "-", w=13), _word(575, y, "23:59)", w=88)]
            else:
                entry, exit_ = _schedule_for(day)
                cells = [_word(369, y, entry), _word(465, y, exit_)]
            lines.append(_row(y, day, *[Word(c.x, y, c.w, c.h, c.text, (str(y),)) for c in cells],
                              weekday=weekdays.get(day)))
        y += 40
        day += timedelta(days=1)
    lines.append([_word(90, y + 40, "Saldo", w=80), _word(180, y + 40, "de", w=30)])
    return lines


# ---------------------------------------------------------------- leitura de tokens


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("08:00", "08:00"),
        ("8:05", "08:05"),
        ("1259", "12:59"),
        ("17300", "17:00"),  # ':' lido como dígito
        ("O8;OO", "08:00"),
        ("0B:15", "08:15"),
        ("25:00", None),
        ("12:61", None),
        ("abc", None),
    ],
)
def test_to_time_normalizes_ocr_reads(token, expected):
    assert to_time(token) == expected


@pytest.mark.parametrize(
    ("token", "expected"),
    [("SEG", "SEG"), ("GUA", "QUA"), ("GUI", "QUI"), ("UA", "QUA"), ("SES", "SEG"), ("COM", "DOM"), ("Não", None), ("X", None)],
)
def test_weekday_of_accepts_one_wrong_letter_when_unique(token, expected):
    assert weekday_of(token) == expected


# ---------------------------------------------------------------- layout


def test_parse_page_builds_dates_from_period_and_row_order():
    page = parse_page(_sheet(), page_number=7)

    assert page is not None
    assert page.page_number == 7
    assert page.unread_days == []
    workdays = [START + timedelta(days=n) for n in range(31) if (START + timedelta(days=n)).weekday() < 5]
    assert page.work_days == [d.isoformat() for d in workdays]
    first = [c for c in page.cells if c.day == "2025-07-21"]
    assert [(c.slot, c.first_read) for c in first] == [(0, "10:00"), (1, "17:00")]


def test_parse_page_dates_survive_misread_weekday_with_one_row_per_day():
    page = parse_page(_sheet(weekdays={date(2025, 7, 22): "SEX"}), page_number=1)

    assert page is not None
    assert "2025-07-22" in page.work_days


def test_parse_page_syncs_by_weekday_and_flags_unread_row():
    missing = date(2025, 7, 23)
    page = parse_page(_sheet(skip={missing}), page_number=1)

    assert page is not None
    assert page.unread_days == [missing.isoformat()]
    assert "2025-07-24" in page.work_days  # a linha perdida não desloca as seguintes


def test_parse_page_infers_period_end_when_ocr_garbles_it():
    page = parse_page(_sheet(period="21/07/2025 à 20/08/2932"), page_number=1)

    assert page is not None
    assert page.work_days[-1] == "2025-08-20"


def test_parse_page_flags_dates_that_disagree_with_printed_months():
    # Início lido 7 dias adiantado: os dias da semana ainda batem, mas os meses impressos
    # nas linhas da virada de mês não. A página fica (não vai inteira ao Gemini), com as
    # datas para o perito confirmar.
    lines = _sheet()
    lines[1] = [
        _word(90, 140, "Período:", w=100),
        *[_word(200 + 120 * i, 140, t, w=110) for i, t in enumerate("28/07/2025 à 27/08/2025".split())],
    ]
    page = parse_page(lines, page_number=1)
    assert page is not None and not page.dates_confirmed
    assert page.cells  # os horários continuam lidos
    assert parse_page(_sheet(), page_number=1).dates_confirmed  # type: ignore[union-attr]


def test_parse_page_keeps_short_sheet_with_unconfirmed_dates():
    # Folha parcial (desligamento): poucas linhas, meses impressos insuficientes para confirmar.
    end = START + timedelta(days=7)
    lines = _sheet(end=end, period=f"{START:%d/%m/%Y} à {end:%d/%m/%Y}")
    rows = [line for line in lines[2:] if len(line) > 1 and weekday_of(line[1].text)]
    for line in rows[4:]:  # data cortada na margem: só 4 meses legíveis
        line[0] = Word(line[0].x, line[0].y, line[0].w, line[0].h, "~/", line[0].line)
    page = parse_page(lines, page_number=1)
    assert page is not None and not page.dates_confirmed
    assert page.work_days  # os horários continuam lidos


def test_parse_page_ignores_pages_without_layout():
    assert parse_page([[_word(10, 10, "Petição", w=90)]], page_number=1) is None
    no_rows = _sheet()[:2]
    assert parse_page(no_rows, page_number=1) is None


def test_parse_page_handles_single_mark_merged_cells_and_missing_tokens():
    single, merged, empty_entry = date(2025, 7, 21), date(2025, 7, 22), date(2025, 7, 23)
    page = parse_page(
        _sheet(
            overrides={
                single: [_word(370, 0, "17:01", w=74), _word(496, 0, "*", w=10), _word(558, 0, "Esquecimento", w=191)],
                merged: [_word(359, 0, "07:58.15:04", w=169)],
                empty_entry: [_word(465, 0, "15:00")],
            }
        ),
        page_number=1,
    )

    assert page is not None
    by_day = {}
    for cell in page.cells:
        by_day.setdefault(cell.day, []).append(cell)
    [mark] = by_day[single.isoformat()]
    assert mark.single_mark and mark.slot == 1 and mark.first_read == "17:01"
    assert [(c.slot, c.first_read) for c in by_day[merged.isoformat()]] == [(0, "07:58"), (1, "15:04")]
    gap = by_day[empty_entry.isoformat()]
    assert [(c.slot, c.first_read) for c in gap] == [(0, None), (1, "15:00")]
    assert gap[0].box[2:] == (COLUMNS.width, COLUMNS.height)


def test_day_off_is_kept_when_exit_column_has_a_time():
    day = date(2025, 7, 22)
    page = parse_page(_sheet(overrides={day: [_word(368, 0, "DEST0800"), _word(465, 0, "15:00")]}), 1)

    assert page is not None
    assert day.isoformat() in page.work_days


# ---------------------------------------------------------------- releitura, trava e decisão


def _crop(text_like: bool = True) -> Image.Image:
    image = Image.new("L", (84, 29), 255)
    if text_like:
        image.paste(0, (10, 8, 70, 20))
    return image


def _tsv(words: list[tuple[int, str]]) -> str:
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = [f"5\t1\t1\t1\t{i}\t1\t5\t{y}\t60\t20\t90\t{text}" for i, (y, text) in enumerate(words)]
    return "\n".join([header, *rows])


def test_reread_cells_reads_whole_page_stack_in_three_calls():
    cells = [Cell("2025-07-21", 0, (0, 0, 76, 21)), Cell("2025-07-21", 1, (0, 0, 76, 21))]
    for cell in cells:
        cell.crop = _crop()
    _, spans = stack([c.crop for c in cells], ocr.STACK_GAP, ocr.STACK_BORDER, scale=2)
    calls = []

    def run(image, args):
        calls.append(args)
        if "-l" in args:  # texto livre: a segunda célula tem uma palavra
            return _tsv([(spans[0][0] + 20, "10:00"), (spans[1][0] + 20, "DESC")])
        return _tsv([(spans[0][0] + 20, "10:00"), (spans[1][0] + 20, "17300")])

    reread_cells(cells, run)

    assert len(calls) == 3
    assert cells[0].rereads == ["10:00", "10:00"] and not cells[0].has_letters
    assert cells[1].rereads == ["17:00", "17:00"] and cells[1].has_letters
    reread_cells([], run)
    assert len(calls) == 3


def _cell(day: str, slot: int, first: str | None, rereads=None, **kwargs) -> Cell:
    cell = Cell(day, slot, kwargs.pop("box", (369 if slot == 0 else 465, 0, 76, 21)), first_read=first, **kwargs)
    cell.rereads = rereads if rereads is not None else [first, first]
    cell.crop = _crop()
    cell.ink_ratio = 0.2
    return cell


def test_passes_gate_checks_size_ink_and_letters():
    assert passes_gate(_cell("2025-07-21", 0, "10:00"), COLUMNS)
    assert not passes_gate(_cell("2025-07-21", 0, None, box=(369, 0, 169, 21)), COLUMNS)
    blank = _cell("2025-07-21", 0, None)
    blank.ink_ratio = 0.0
    assert not passes_gate(blank, COLUMNS)
    worded = _cell("2025-07-21", 0, None)
    worded.has_letters = True
    assert not passes_gate(worded, COLUMNS)


def _week_cells() -> list[Cell]:
    """Três segundas e três terças legíveis: base para a jornada observada."""
    cells = []
    for monday in ("2025-07-21", "2025-07-28", "2025-08-04"):
        cells += [_cell(monday, 0, "10:00"), _cell(monday, 1, "17:00")]
    for tuesday in ("2025-07-22", "2025-07-29", "2025-08-05"):
        cells += [_cell(tuesday, 0, "08:00"), _cell(tuesday, 1, "15:00")]
    return cells


def test_observed_schedule_uses_median_and_needs_three_samples():
    cells = _week_cells() + [_cell("2025-07-23", 0, "08:00")]
    cells[0].first_read = "23:00"  # leitura errada isolada não move a mediana

    schedule = observed_schedule(cells)

    assert schedule == {"SEG": ("10:00", "17:00"), "TER": ("08:00", "15:00")}


def test_resolve_local_accepts_only_plausible_consensus():
    cells = _week_cells()
    disagree = _cell("2025-08-11", 0, "10:00", rereads=["10:08", "10:00"])
    far = _cell("2025-08-11", 1, "23:00")
    unknown_weekday = _cell("2025-07-23", 0, "08:00")  # quarta: sem jornada observada
    cells += [disagree, far, unknown_weekday]
    schedule = observed_schedule(cells)

    resolve_local(cells, schedule)

    assert cells[0].value == "10:00" and cells[0].source == "local"
    assert disagree.value is None and far.value is None
    assert unknown_weekday.value == "08:00"


def test_apply_gemini_needs_schedule_and_vetoes_local_consensus():
    cells = _week_cells()
    schedule = observed_schedule(cells)
    resolve_local(cells, schedule)
    doubtful = _cell("2025-08-11", 0, None, rereads=[None, None])
    implausible = _cell("2025-08-11", 1, None, rereads=[None, None])
    no_schedule = _cell("2025-07-23", 0, None, rereads=[None, None])
    doubtful.gemini_read, implausible.gemini_read, no_schedule.gemini_read = "10:02", "21:00", "08:00"
    cells[1].gemini_read = "17:01"  # discorda do consenso local "17:00"
    cells[2].gemini_read = "10:00"  # concorda
    cells += [doubtful, implausible, no_schedule]

    apply_gemini(cells, schedule)

    assert doubtful.value == "10:02" and doubtful.source == "gemini"
    assert implausible.value is None and no_schedule.value is None
    assert cells[1].value is None and cells[1].source is None
    assert cells[2].value == "10:00" and cells[2].source == "local"


def _page(cells: list[Cell], **kwargs) -> TimeCardPage:
    page = TimeCardPage(page_number=3, rows=31, columns=COLUMNS, cells=cells, **kwargs)
    page.work_days = sorted({c.day for c in cells})
    return page


def test_build_strips_groups_by_physical_column_and_skips_resolved_columns():
    resolved = [_cell("2025-07-21", 0, "10:00"), _cell("2025-07-22", 0, "08:00")]
    for cell in resolved:
        cell.value, cell.source = cell.first_read, "local"
    doubtful_exit = _cell("2025-07-21", 1, None)
    resolved_exit = _cell("2025-07-22", 1, "15:00")
    resolved_exit.value, resolved_exit.source = "15:00", "local"
    blocked = _cell("2025-07-23", 1, None, box=(465, 0, 200, 21))
    single = _cell("2025-07-24", 1, None, box=(370, 0, 74, 21), single_mark=True)

    strips = build_strips([_page([*resolved, doubtful_exit, resolved_exit, blocked, single])])

    # Entrada: a marcação única (fisicamente na coluna de entrada) puxa a faixa.
    assert len(strips) == 2
    members = [{id(c) for c in strip.cells} for strip in strips]
    assert {id(resolved[0]), id(resolved[1]), id(single)} in members
    assert {id(doubtful_exit), id(resolved_exit)} in members
    assert all(id(blocked) not in group for group in members)
    image = Image.open(io.BytesIO(strips[0].png()))
    assert image.height > 29 * 2


def test_read_strip_answers_maps_values_in_order_and_drops_bad_counts():
    cells = [_cell("2025-07-21", 1, None), _cell("2025-07-22", 1, None)]
    strip = ocr.Strip("fabc123", cells)
    other = ocr.Strip("fdef456", [_cell("2025-07-23", 1, None)])

    accepted = read_strip_answers(
        {"strips": [
            {"id": "fabc123", "values": ["17:01", None]},
            {"id": "fdef456", "values": ["15:00", "15:01"]},
            {"id": "desconhecida", "values": []},
        ]},
        [strip, other],
    )

    assert accepted == 1
    assert [c.gemini_read for c in cells] == ["17:01", None]
    assert other.cells[0].gemini_read is None


def test_to_entries_marks_pending_fields_and_keeps_crops_only_for_non_local_cells():
    local_in = _cell("2025-07-21", 0, "10:00")
    local_in.value, local_in.source = "10:00", "local"
    gemini_out = _cell("2025-07-21", 1, None)
    gemini_out.value, gemini_out.source = "17:01", "gemini"
    pending = _cell("2025-07-22", 0, None)
    single = _cell("2025-07-24", 0, None, single_mark=True)
    page = _page([local_in, gemini_out, pending, single], unread_days=["2025-07-23"])

    entries, crops = to_entries([page])

    by_day = {entry.date: entry for entry in entries}
    first = by_day["2025-07-21"]
    assert (first.clock_in, first.clock_out, first.ambiguous_fields) == ("10:00", "17:01", [])
    assert first.confidence == ocr.CONFIDENCE_WITH_GEMINI
    assert list(first.review_crops) == ["clock_out"]
    second = by_day["2025-07-22"]
    assert second.clock_in is None and second.ambiguous_fields == ["clock_in"]
    assert second.confidence == ocr.CONFIDENCE_PENDING
    assert by_day["2025-07-24"].ambiguous_fields == ["clock_in", "clock_out"]
    assert by_day["2025-07-23"].confidence == 0 and by_day["2025-07-23"].ambiguous_fields == ["clock_in", "clock_out"]
    assert len(crops) == 3 and set(crops) >= set(first.review_crops.values())
    assert all(png.startswith(b"\x89PNG") for png in crops.values())
    assert ocr.summary(LocalTimeCards(pages=[page]))["review"] == 2


def test_to_entries_sends_dates_of_unconfirmed_page_to_review():
    read = _cell("2025-07-21", 0, "10:00")
    read.value, read.source = "10:00", "local"
    page = _page([read], unread_days=["2025-07-22"])
    page.dates_confirmed = False

    entries, _ = to_entries([page])

    by_day = {entry.date: entry for entry in entries}
    assert by_day["2025-07-21"].clock_in == "10:00"  # o horário lido continua valendo
    assert by_day["2025-07-21"].ambiguous_fields[0] == "date"
    assert by_day["2025-07-22"].ambiguous_fields == ["date", "clock_in", "clock_out"]
    assert ocr.summary(LocalTimeCards(pages=[page]))["dates_unconfirmed"] == 1


# ---------------------------------------------------------------- leitor e Tesseract


def _scan_pdf(tmp_path: Path, pages: int = 1) -> Path:
    document = fitz.open()
    image = Image.new("L", (600, 800), 255)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    for _ in range(pages):
        page = document.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=buffer.getvalue())
    path = tmp_path / "scan.pdf"
    document.save(path)
    document.close()
    return path


def _lines_to_tsv(lines: list[list[Word]]) -> str:
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = [
        f"5\t1\t1\t1\t{index}\t1\t{w.x}\t{w.y}\t{w.w}\t{w.h}\t90\t{w.text}"
        for index, words in enumerate(lines)
        for w in words
    ]
    return "\n".join([header, *rows])


def test_reader_recognizes_pages_and_resolves_locally(tmp_path: Path):
    pdf_path = _scan_pdf(tmp_path, pages=2)
    sheet = _lines_to_tsv(_sheet())
    calls = {"page": 0}

    def run(image, args):
        if args[:4] == ["-l", "por", "--psm", "6"] and image.height >= ocr.TARGET_HEIGHT * 0.9:
            calls["page"] += 1
            # Segunda página: não é cartão (vai como página para o Gemini).
            return sheet if calls["page"] == 1 else _tsv([(10, "Petição")])
        return _tsv([])  # releituras vazias: nada tem consenso

    local = TimeCardReader(run, workers=2).read(pdf_path, [1, 2])

    assert [page.page_number for page in local.pages] in ([1], [2])
    assert len(local.unrecognized_pages) == 1
    assert local.schedule["SEG"] == ("10:00", "17:00")
    assert all(cell.value is None for page in local.pages for cell in page.cells)
    assert TimeCardReader(run).read(pdf_path, []).pages == []


def test_reader_treats_ocr_failure_as_unrecognized(tmp_path: Path):
    pdf_path = _scan_pdf(tmp_path)

    def run(image, args):
        raise subprocess.CalledProcessError(1, "tesseract")

    local = TimeCardReader(run).read(pdf_path, [1])

    assert local.pages == [] and local.unrecognized_pages == [1]


def test_page_image_uses_embedded_scan_or_renders(tmp_path: Path):
    with fitz.open(_scan_pdf(tmp_path)) as document:
        assert Image.open(io.BytesIO(ocr.page_image(document[0]))).size == (600, 800)
    document = fitz.open()
    document.new_page().insert_text((72, 72), "texto")
    rendered = Image.open(io.BytesIO(ocr.page_image(document[0])))
    assert rendered.height == ocr.TARGET_HEIGHT
    document.close()


def test_tesseract_runner_passes_args_and_limits_threads(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(ocr.subprocess, "run", fake_run)

    output = ocr.tesseract_runner("tesseract")(Image.new("L", (4, 4)), ["--psm", "7"])

    assert output == "ok"
    assert seen["command"] == ["tesseract", "stdin", "stdout", "--psm", "7"]
    assert seen["env"]["OMP_THREAD_LIMIT"] == "1"


def test_build_time_card_reader_requires_tesseract_with_portuguese(monkeypatch):
    ocr.tesseract_available.cache_clear()
    assert build_time_card_reader(False, "tesseract") is None

    monkeypatch.setattr(ocr.shutil, "which", lambda command: None)
    assert build_time_card_reader(True, "sem-tesseract") is None

    monkeypatch.setattr(ocr.shutil, "which", lambda command: "/usr/bin/" + command)
    monkeypatch.setattr(
        ocr.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, stdout=b"eng\npor\n", stderr=b""),
    )
    assert isinstance(build_time_card_reader(True, "tess-com-por"), TimeCardReader)

    def broken(command, **kwargs):
        raise OSError("sem permissão")

    monkeypatch.setattr(ocr.subprocess, "run", broken)
    assert build_time_card_reader(True, "tess-quebrado") is None
    ocr.tesseract_available.cache_clear()
