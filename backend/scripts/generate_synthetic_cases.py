"""Gera processos trabalhistas sintéticos com gabarito, para avaliar o pipeline em escala.

Cada caso é um PDF com peças processuais de enchimento, holerites e cartões de ponto, mais
o gabarito no formato de scripts/evaluate_extraction.py (gerado junto, nada digitado à mão).
Tudo é fictício (nomes, empresas, jornadas e valores sorteados), então os casos não têm
dado pessoal; mesmo assim os PDFs não vão para o repositório (o CI bloqueia `*.pdf`): a
semente recria cada caso.

Variação entre os casos:

- layout do cartão: "relogio" (o layout que o OCR local reconhece: Data | Dia | Ent | Sai,
  período "dd/mm/aaaa à dd/mm/aaaa", folga "DESC(00:00 - 23:59)", marcação única
  "Esquecimento", folha curta de desligamento) ou "planilha" (outro layout, com intervalo:
  vai inteiro ao Gemini, como qualquer layout não reconhecido);
- digitalização: "nativo" (PDF com texto) ou escaneado "leve", "medio" e "forte" (raster,
  rotação, borrão, ruído, contraste baixo, falha de fita e JPEG);
- jornada por dia da semana, horas extras, feriados, sábados trabalhados, número de meses,
  holerites (nativos ou escaneados) e páginas de enchimento.

Limitação: o cartão "relogio" imita o layout das folhas reais medidas, então mede robustez
dentro desse layout, não generalização para outros; o ruído é simulado. As folhas reais
seguem como validação de campo, reportada à parte.

Uso (a partir de backend/):
  python scripts/generate_synthetic_cases.py ../avaliacao-sintetica --cases 24 --seed 1
  python scripts/evaluate_synthetic.py ../avaliacao-sintetica
"""

from __future__ import annotations

import argparse
import io
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageEnhance, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate_models import _payslip, _time_card  # noqa: E402

LAYOUTS = ("relogio", "planilha")
SCANS = ("nativo", "leve", "medio", "forte")
# Ciclo de combinações: o layout reconhecido domina, porque é o que o OCR local mede.
COMBINATIONS = (
    ("relogio", "leve"),
    ("relogio", "medio"),
    ("relogio", "forte"),
    ("relogio", "nativo"),
    ("planilha", "medio"),
    ("planilha", "nativo"),
)
WEEKDAYS = ("SEG", "TER", "QUA", "QUI", "SEX", "SAB", "DOM")
MONTHS = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto",
          "Setembro", "Outubro", "Novembro", "Dezembro")
FIRST_NAMES = ("ANA", "BRUNO", "CARLA", "DIEGO", "ELISA", "FABIO", "GISELE", "HUGO", "IARA",
               "JONAS", "KARINA", "LUCAS", "MARTA", "NELSON", "OLGA", "PAULO", "RITA", "SAULO")
LAST_NAMES = ("FICTICIA", "EXEMPLAR", "MODELO", "AMOSTRA", "TESTE", "SINTETICA", "PADRAO")
COMPANIES = ("COMERCIO EXEMPLO LTDA", "INDUSTRIA MODELO S.A.", "SERVICOS AMOSTRA EIRELI",
             "LOGISTICA FICTICIA LTDA", "SUPERMERCADO TESTE LTDA")
ROLES = ("Operador de Caixa", "Auxiliar de Produção", "Repositor", "Atendente", "Motorista")


@dataclass(frozen=True)
class Degradation:
    dpi: int
    rotation: float
    blur: float
    noise: float
    contrast: float
    quality: int
    faded_bands: int  # faixas claras de fita gasta (impressora matricial)
    dropout: float  # fração da tinta apagada em pontos (agulha falhando)


DEGRADATIONS = {
    "leve": Degradation(dpi=200, rotation=0.4, blur=0.3, noise=0.05, contrast=0.95, quality=75, faded_bands=0, dropout=0.0),
    "medio": Degradation(dpi=150, rotation=1.0, blur=0.6, noise=0.10, contrast=0.8, quality=55, faded_bands=2, dropout=0.15),
    "forte": Degradation(dpi=110, rotation=1.6, blur=0.9, noise=0.16, contrast=0.7, quality=40, faded_bands=4, dropout=0.3),
}


@dataclass
class CaseSpec:
    case_id: str
    seed: int
    layout: str
    scan: str


@dataclass
class Case:
    spec: CaseSpec
    pdf: bytes
    gabarito: dict
    meta: dict = field(default_factory=dict)


# ---------------------------------------------------------------- texto


def _write(page: fitz.Page, x: float, y: float, text: str, size: float = 9, font: str = "helv") -> None:
    page.insert_text((x, y), text, fontsize=size, fontname=font)


FILLERS = {
    "Petição inicial": [
        "{nome}, já qualificado nos autos, vem, por seu advogado, propor RECLAMAÇÃO TRABALHISTA",
        "em face de {empresa}, pelos fundamentos de fato e de direito a seguir expostos.",
        "O reclamante foi admitido para exercer a função de {cargo}, cumprindo jornada com",
        "entrada e saída em horários variados, sem a correta anotação das horas extras.",
        "Requer o pagamento das diferenças, com reflexos em FGTS e recolhimento de INSS.",
    ],
    "Procuração": [
        "Pelo presente instrumento particular de mandato, {nome} nomeia e constitui seu",
        "procurador o advogado abaixo assinado, com poderes para o foro em geral.",
    ],
    "Contestação": [
        "{empresa}, já qualificada, apresenta CONTESTAÇÃO à reclamação trabalhista ajuizada",
        "por {nome}, impugnando os pedidos pelos fatos e fundamentos a seguir.",
        "A jornada era corretamente registrada e as horas eventualmente prestadas foram pagas",
        "ou compensadas, conforme cartões de ponto e recibos juntados.",
    ],
    "Ata de audiência": [
        "Aberta a audiência, presentes as partes. Recusada a primeira proposta de conciliação.",
        "Determinada a juntada dos documentos pela reclamada no prazo de cinco dias.",
    ],
    "Documento pessoal": [
        "Cópia de documento de identificação do reclamante, apresentada para instruir o feito.",
    ],
}


def _filler(page: fitz.Page, title: str, people: dict[str, str], rng: random.Random) -> None:
    _write(page, 60, 70, title.upper(), 13)
    y = 110
    for _ in range(rng.randint(2, 5)):
        for line in FILLERS[title]:
            _write(page, 60, y, line.format(**people), 10)
            y += 15
        y += 12
        if y > 760:
            break


# ---------------------------------------------------------------- cartão "relogio"


def _schedule(rng: random.Random) -> dict[int, tuple[int, int] | None]:
    """Jornada por dia da semana em minutos (entrada, saída); None = descanso."""
    start = rng.choice([6 * 60, 7 * 60, 8 * 60, 9 * 60, 13 * 60 + 30])
    length = rng.choice([6 * 60, 7 * 60, 7 * 60 + 20, 8 * 60])
    schedule: dict[int, tuple[int, int] | None] = {}
    for weekday in range(5):
        shift = rng.choice([0, 0, 0, 60, 120]) if start <= 9 * 60 else 0
        schedule[weekday] = (start + shift, start + shift + length)
    schedule[5] = (start, start + 4 * 60) if rng.random() < 0.4 else None
    schedule[6] = None
    return schedule


def _mark(minutes: int) -> str:
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _relogio_sheet(
    page: fitz.Page,
    start: date,
    rng: random.Random,
    schedule: dict[int, tuple[int, int] | None],
    people: dict[str, str],
    holidays: set[date],
    last_day: date | None,
) -> list[dict]:
    """Espelho de ponto no layout reconhecido; devolve as linhas do gabarito."""
    end = _monthly_end(start)
    font = "cour"
    _write(page, 40, 48, "ESPELHO DE PONTO - REGISTRO ELETRONICO", 12, font)
    _write(page, 40, 66, f"Empresa: {people['empresa']}   CNPJ: 00.000.000/0001-00", 9, font)
    _write(page, 40, 80, f"Funcionario: {people['nome']}   Cargo: {people['cargo']}", 9, font)
    _write(page, 40, 94, f"Periodo: {start:%d/%m/%Y} à {end:%d/%m/%Y}", 9, font)
    # Como nas folhas reais, o "23:59)" da folga passa da coluna de saída (não vira horário).
    columns = (40, 125, 175, 222, 300)
    for x, header in zip(columns, ("Data", "Dia", "Ent", "Sai", "Observacao")):
        _write(page, x, 122, header, 9, font)
    page.draw_line((38, 127), (560, 127))

    rows: list[dict] = []
    y = 127.0
    step = min(20.0, 640 / ((end - start).days + 1))
    current = start
    while current <= (last_day or end):
        y += step
        weekday = current.weekday()
        cells = [f"{current:%d/%m/%Y}", WEEKDAYS[weekday]]
        planned = schedule[weekday]
        if current in holidays:
            cells += ["", "", "FERIADO"]
        elif planned is None:
            cells += ["DESC(00:00 - 23:59)"]
        else:
            clock_in = planned[0] + rng.randint(-7, 8)
            clock_out = planned[1] + rng.choice([0, 0, 1, 2, 3, 5, 15, 30, 60]) + rng.randint(-3, 4)
            truth = {"date": current.isoformat(), "clock_in": _mark(clock_in), "clock_out": _mark(clock_out)}
            if rng.random() < 0.04:
                # Marcação única: o relógio imprime o horário na primeira coluna.
                kept = rng.choice(["clock_in", "clock_out"])
                cells += [truth[kept], "", "*Esquecimento"]
                truth["clock_out" if kept == "clock_in" else "clock_in"] = None
            else:
                cells += [truth["clock_in"], truth["clock_out"], ""]
            rows.append(truth)
        for x, value in zip(columns, cells):
            _write(page, x, y, value, 9, font)
        current += timedelta(days=1)
    y += 26
    _write(page, 40, y, "Saldo do periodo: conforme banco de horas", 9, font)
    _write(page, 40, y + 14, "Horario do Funcionario: conforme contrato de trabalho", 9, font)
    return rows


def _monthly_end(start: date) -> date:
    month = start.month % 12 + 1
    year = start.year + (start.month == 12)
    return date(year, month, start.day) - timedelta(days=1)


# ---------------------------------------------------------------- digitalização


def _noise(size: tuple[int, int], rng: random.Random) -> Image.Image:
    """Ruído uniforme da semente do caso (Image.effect_noise não é reproduzível)."""
    return Image.frombytes("L", size, rng.randbytes(size[0] * size[1]))


def _scan(target: fitz.Document, source: fitz.Page, level: str, rng: random.Random) -> None:
    """Rasteriza a página com a degradação do nível e a insere como imagem de página inteira."""
    spec = DEGRADATIONS[level]
    pixmap = source.get_pixmap(dpi=spec.dpi, colorspace=fitz.csGRAY)
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("L")
    for _ in range(spec.faded_bands):
        top = rng.randint(0, image.height - 40)
        band = image.crop((0, top, image.width, top + rng.randint(15, 40)))
        image.paste(ImageEnhance.Brightness(band).enhance(1.6), (0, top))
    if spec.dropout:
        cutoff = 255 * (1 - spec.dropout)
        image.paste(255, mask=_noise(image.size, rng).point(lambda p: 255 if p > cutoff else 0))
    angle = rng.uniform(-spec.rotation, spec.rotation)
    image = image.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255)
    if spec.blur:
        image = image.filter(ImageFilter.GaussianBlur(spec.blur))
    image = Image.blend(image, _noise(image.size, rng), spec.noise)
    image = ImageEnhance.Contrast(image).enhance(spec.contrast)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=spec.quality)
    page = target.new_page(width=source.rect.width, height=source.rect.height)
    page.insert_image(page.rect, stream=buffer.getvalue())


# ---------------------------------------------------------------- holerite


def _payslip_items(rng: random.Random, base: float) -> list[tuple[str, str, str, float, bool]]:
    overtime = round(rng.uniform(80, 700), 2)
    items = [
        ("001", "Salário Base", "220,00", base, False),
        ("010", "Horas Extras 50%", f"{rng.randint(4, 30)},00", overtime, False),
        ("020", "DSR s/ Horas Extras", "", round(overtime / 5, 2), False),
    ]
    if rng.random() < 0.4:
        items.append(("030", "Adicional Noturno 20%", "", round(rng.uniform(60, 300), 2), False))
    items.append(("101", "INSS", "9,00%", round(base * 0.09, 2), True))
    if rng.random() < 0.6:
        items.append(("110", "Vale Transporte", "6,00%", round(base * 0.06, 2), True))
    return items


# ---------------------------------------------------------------- caso


def build_case(spec: CaseSpec) -> Case:
    rng = random.Random(spec.seed)
    people = {
        "nome": f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)} {rng.choice(LAST_NAMES)}",
        "empresa": rng.choice(COMPANIES),
        "cargo": rng.choice(ROLES),
    }
    year = rng.choice([2023, 2024, 2025])
    first_month = rng.randint(1, 9)
    months = rng.randint(1, 4)
    period_start_day = rng.choice([1, 16, 21])
    scanned = spec.scan != "nativo"
    base_salary = float(rng.choice([1518, 1800, 2200, 2750, 3200]))

    document = fitz.open()
    scratch = fitz.open()
    pages: dict[str, str] = {}
    time_cards: list[dict] = []
    payslips: list[dict] = []

    def add(kind: str, draw, scan_level: str | None) -> int:
        if scan_level is None:
            draw(document.new_page())
        else:
            source = scratch.new_page()
            draw(source)
            _scan(document, source, scan_level, rng)
        number = document.page_count
        if kind != "IRRELEVANTE":
            pages[str(number)] = kind
        return number

    for title in ("Petição inicial", "Procuração", "Documento pessoal"):
        for _ in range(rng.randint(1, 6) if title == "Petição inicial" else 1):
            add("IRRELEVANTE", lambda p, t=title: _filler(p, t, people, rng), None)
    for _ in range(rng.randint(2, 8)):
        add("IRRELEVANTE", lambda p: _filler(p, "Contestação", people, rng), None)

    payslip_scan = spec.scan if scanned and rng.random() < 0.5 else None
    for offset in range(months):
        if rng.random() < 0.25:
            continue  # holerite não juntado
        month = (first_month + offset - 1) % 12 + 1
        competence = f"{year}-{month:02d}"
        items = _payslip_items(rng, base_salary)
        label = f"{MONTHS[month - 1]}/{year}"
        add("HOLERITE", lambda p, label=label, items=items: _payslip(p, label, items), payslip_scan)
        payslips += [{"competence": competence, "item_name": name, "amount": amount}
                     for _, name, _, amount, _ in items]

    schedule = _schedule(rng)
    short_sheet = False
    card_pages: list[int] = []
    for offset in range(months):
        month = (first_month + offset - 1) % 12 + 1
        scan_level = spec.scan if scanned else None
        if spec.layout == "relogio":
            start = date(year, month, period_start_day)
            holidays = {start + timedelta(days=rng.randint(0, 27))} if rng.random() < 0.5 else set()
            last_day = None
            if offset == months - 1 and months > 1 and rng.random() < 0.35:
                last_day = start + timedelta(days=rng.randint(6, 14))  # desligamento: folha curta
                short_sheet = True
            rows: list[dict] = []
            card_pages.append(add(
                "CARTAO_PONTO",
                lambda p, s=start, h=holidays, d=last_day, r=rows: r.extend(
                    _relogio_sheet(p, s, rng, schedule, people, h, d)
                ),
                scan_level,
            ))
            time_cards += rows
        else:
            truth: dict = {}
            holidays_day = {rng.randint(2, 27)}
            missing = {rng.randint(2, 27)}
            card_pages.append(add(
                "CARTAO_PONTO",
                lambda p, m=month, h=holidays_day, x=missing, t=truth: t.update(
                    _time_card(p, year, m, rng, holidays=h, missing_out=x)
                ),
                scan_level,
            ))
            for iso, times in truth.items():
                if times is not None:
                    time_cards.append(dict(zip(("date", "clock_in", "break_start", "break_end", "clock_out"),
                                               (iso, *times))))

    if scanned:
        add("IRRELEVANTE", lambda p: _filler(p, "Ata de audiência", people, rng), spec.scan)
    for _ in range(rng.randint(1, 5)):
        add("IRRELEVANTE", lambda p: _filler(p, "Ata de audiência", people, rng), None)

    pdf = document.tobytes(garbage=3, deflate=True)
    meta = {
        "case_id": spec.case_id,
        "seed": spec.seed,
        "layout": spec.layout,
        "scan": spec.scan,
        "payslips_scanned": payslip_scan is not None,
        "months": months,
        "short_sheet": short_sheet,
        "pdf_pages": document.page_count,
        "time_card_pages": card_pages,
    }
    document.close()
    scratch.close()
    gabarito = {"meta": meta, "pages": pages, "time_cards": time_cards, "payslips": payslips}
    return Case(spec=spec, pdf=pdf, gabarito=gabarito, meta=meta)


def plan_cases(count: int, seed: int) -> list[CaseSpec]:
    return [
        CaseSpec(case_id=f"caso_{index + 1:02d}", seed=seed * 1000 + index, layout=layout, scan=scan)
        for index, (layout, scan) in zip(range(count), _cycle(COMBINATIONS))
    ]


def _cycle(items):
    while True:
        yield from items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("output", type=Path, help="pasta de saída (fora do controle de versão)")
    parser.add_argument("--cases", type=int, default=24)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)

    args.output.mkdir(parents=True, exist_ok=True)
    for spec in plan_cases(args.cases, args.seed):
        case = build_case(spec)
        (args.output / f"{spec.case_id}.pdf").write_bytes(case.pdf)
        (args.output / f"{spec.case_id}.gabarito.json").write_text(
            json.dumps(case.gabarito, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"{spec.case_id}: {spec.layout}/{spec.scan} · {case.meta['pdf_pages']} páginas"
              f" · {len(case.gabarito['time_cards'])} dias · {len(case.gabarito['payslips'])} verbas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
