"""Compara modelos Gemini na camada 3 com um PDF sintético de gabarito conhecido.

Usa o mesmo caminho de produção (GeminiDocumentClassifier._call_model: mesmo prompt,
mesma imagem JPEG). Só dados fictícios; nada é gravado, exceto o PDF de inspeção
opcional (--save-pdf).

Uso (a partir de backend/):
  python scripts/evaluate_models.py
  python scripts/evaluate_models.py --models gemini-3.6-flash,gemini-3.8-flash --runs 2
  python scripts/evaluate_models.py --models gemini-3.6-flash --thinking default,MINIMAL,LOW
"""

from __future__ import annotations

import argparse
import io
import logging
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import fitz
from google.genai import errors, types
from PIL import Image, ImageEnhance, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import settings  # noqa: E402
from pipeline.classifier import GeminiDocumentClassifier, _render_page  # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("veritas_ai").setLevel(logging.ERROR)

DEFAULT_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]
TIME_FIELDS = ("clock_in", "break_start", "break_end", "clock_out")
RETRY_DELAYS = (4, 10, 20, 40)
RETRY_CODES = {429, 500, 503}
WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


# ---------------------------------------------------------------- gabarito


@dataclass
class PageTruth:
    page_number: int
    document_type: str
    label: str
    # data ISO -> (entrada, saída int., retorno, saída) ou None (DSR/feriado)
    time_cards: dict[str, tuple[str | None, ...] | None] | None = None
    competence: str | None = None
    payslip_amounts: list[float] = field(default_factory=list)
    acceptable_amounts: set[float] = field(default_factory=set)


def _brl(value: float) -> str:
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _write(page: fitz.Page, x: float, y: float, text: str, size: float = 9) -> None:
    page.insert_text((x, y), text, fontsize=size, fontname="helv")


def _petition(page: fitz.Page) -> None:
    lines = [
        "EXCELENTÍSSIMO SENHOR JUIZ DA VARA DO TRABALHO",
        "",
        "JOÃO FICTÍCIO DA SILVA, já qualificado, vem propor RECLAMAÇÃO TRABALHISTA",
        "em face de METALÚRGICA EXEMPLO LTDA, pelos fatos a seguir.",
        "",
        "O reclamante cumpria jornada com entrada às 08:00 e saída após as 18:00,",
        "sem o correto pagamento de horas extras. Requer o recolhimento de FGTS e",
        "INSS sobre as parcelas deferidas e a multa do art. 477 da CLT.",
        "",
        "Dá-se à causa o valor de R$ 85.000,00.",
    ]
    for index, line in enumerate(lines):
        _write(page, 60, 80 + index * 16, line, 10)


def _time_card(page: fitz.Page, year: int, month: int, rng: random.Random,
               holidays: set[int], missing_out: set[int]) -> dict:
    first = date(year, month, 1)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    _write(page, 40, 50, "CARTÃO DE PONTO - REGISTRO ELETRÔNICO", 12)
    _write(page, 40, 68, "Empresa: METALÚRGICA EXEMPLO LTDA     Funcionário: JOÃO FICTÍCIO DA SILVA")
    _write(page, 40, 82, f"Período: {first:%d/%m/%Y} a {last:%d/%m/%Y}     Horário contratual: 08:00-12:00 / 13:00-17:00")
    columns = [40, 75, 150, 215, 290, 360, 430]
    headers = ["Dia", "Data", "Entrada", "Saída Int.", "Retorno", "Saída", "Observação"]
    y = 110
    for x, header in zip(columns, headers):
        _write(page, x, y, header, 8.5)
    page.draw_line((38, y + 4), (560, y + 4))

    truth: dict[str, tuple[str | None, ...] | None] = {}
    current = first
    while current <= last:
        y += 19
        day = current.day
        row = [WEEKDAYS[current.weekday()], f"{current:%d/%m/%Y}"]
        if current.weekday() >= 5 or day in holidays:
            note = "FERIADO" if day in holidays else "DSR"
            row += ["", "", "", "", note]
            truth[current.isoformat()] = None
        else:
            clock_in = 8 * 60 + rng.randint(-8, 9)
            break_start = 12 * 60 + rng.randint(-4, 6)
            break_end = break_start + 60 + rng.randint(-3, 5)
            clock_out = 17 * 60 + rng.choice([0, 3, 12, 35, 48, 62, 95]) + rng.randint(0, 4)
            times: list[str | None] = [_hhmm(clock_in), _hhmm(break_start), _hhmm(break_end), _hhmm(clock_out)]
            note = ""
            if day in missing_out:
                times[3] = None
                note = "Marcação ausente"
            row += [t or "" for t in times] + [note]
            truth[current.isoformat()] = tuple(times)
        for x, value in zip(columns, row):
            _write(page, x, y, value, 8.5)
        page.draw_line((38, y + 5), (560, y + 5), color=(0.8, 0.8, 0.8))
        current += timedelta(days=1)
    return truth


def _payslip(page: fitz.Page, month_label: str, items: list[tuple[str, str, str, float, bool]]) -> tuple[list[float], set[float]]:
    _write(page, 40, 50, "RECIBO DE PAGAMENTO DE SALÁRIO", 12)
    _write(page, 40, 68, "Empresa: METALÚRGICA EXEMPLO LTDA     CNPJ: 00.000.000/0001-00")
    _write(page, 40, 82, "Funcionário: JOÃO FICTÍCIO DA SILVA     Cargo: Operador de Máquinas")
    _write(page, 40, 96, f"Competência: {month_label}")
    columns = [45, 90, 290, 370, 460]
    headers = ["Cód.", "Descrição", "Referência", "Vencimentos", "Descontos"]
    y = 125
    page.draw_rect(fitz.Rect(38, y - 14, 555, y + 6 + 18 * len(items)))
    for x, header in zip(columns, headers):
        _write(page, x, y, header, 9)
    page.draw_line((38, y + 5), (555, y + 5))
    earnings = deductions = 0.0
    amounts: list[float] = []
    for code, description, reference, amount, is_deduction in items:
        y += 18
        values = [code, description, reference, "" if is_deduction else _brl(amount), _brl(amount) if is_deduction else ""]
        for x, value in zip(columns, values):
            _write(page, x, y, value, 9)
        amounts.append(round(amount, 2))
        if is_deduction:
            deductions += amount
        else:
            earnings += amount
    earnings, deductions = round(earnings, 2), round(deductions, 2)
    net = round(earnings - deductions, 2)
    base_salary = items[0][3]
    inss = next(amount for _, description, _, amount, _ in items if description.startswith("INSS"))
    fgts = round(earnings * 0.08, 2)
    irrf_base = round(earnings - inss, 2)
    y += 30
    _write(page, 290, y, f"Total Vencimentos: {_brl(earnings)}     Total Descontos: {_brl(deductions)}")
    _write(page, 290, y + 16, f"Líquido a Receber: {_brl(net)}", 10)
    y += 50
    footer = [
        ("Salário Base", base_salary), ("Base Cálc. INSS", earnings),
        ("Base Cálc. FGTS", earnings), ("FGTS do Mês", fgts), ("Base Cálc. IRRF", irrf_base),
    ]
    for index, (label, value) in enumerate(footer):
        _write(page, 45 + index * 102, y, label, 7.5)
        _write(page, 45 + index * 102, y + 13, _brl(value), 9)
    acceptable = set(amounts) | {earnings, deductions, net, base_salary, fgts, irrf_base}
    return amounts, acceptable


def _degrade_to_image_page(target: fitz.Document, source_page: fitz.Page, seed: int) -> None:
    """Simula digitalização: raster 110 DPI, rotação, blur, ruído, contraste baixo, JPEG ruim."""
    pixmap = source_page.get_pixmap(dpi=110, colorspace=fitz.csGRAY)
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("L")
    image = image.rotate(1.4 if seed % 2 else -1.1, resample=Image.BICUBIC, expand=True, fillcolor=255)
    image = image.filter(ImageFilter.GaussianBlur(0.7))
    image = Image.blend(image, Image.effect_noise(image.size, 30).convert("L"), 0.12)
    image = ImageEnhance.Contrast(image).enhance(0.75)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=45)
    page = target.new_page()
    page.insert_image(page.rect, stream=buffer.getvalue())


def build_eval_pdf() -> tuple[bytes, list[PageTruth]]:
    rng = random.Random(42)
    document = fitz.open()
    scratch = fitz.open()
    truths: list[PageTruth] = []

    _petition(document.new_page())
    truths.append(PageTruth(1, "IRRELEVANTE", "petição"))

    amounts, acceptable = _payslip(document.new_page(), "Abril/2024", [
        ("001", "Salário Base", "220,00", 3200.00, False),
        ("010", "Horas Extras 50%", "20,00", 436.36, False),
        ("015", "Adicional Noturno 20%", "", 128.00, False),
        ("020", "DSR s/ Horas Extras", "", 87.27, False),
        ("101", "INSS", "11,68%", 412.47, True),
        ("105", "IRRF", "7,50%", 98.55, True),
        ("110", "Vale Transporte", "6,00%", 192.00, True),
    ])
    truths.append(PageTruth(2, "HOLERITE", "holerite nativo", competence="2024-04",
                            payslip_amounts=amounts, acceptable_amounts=acceptable))

    march = _time_card(document.new_page(), 2024, 3, rng, holidays={29}, missing_out={14})
    truths.append(PageTruth(3, "CARTAO_PONTO", "ponto nativo", time_cards=march))

    april = _time_card(scratch.new_page(), 2024, 4, rng, holidays={21}, missing_out={10})
    _degrade_to_image_page(document, scratch[0], seed=1)
    truths.append(PageTruth(4, "CARTAO_PONTO", "ponto escaneado", time_cards=april))

    amounts, acceptable = _payslip(scratch.new_page(), "Maio/2024", [
        ("001", "Salário Base", "220,00", 3200.00, False),
        ("010", "Horas Extras 50%", "15,00", 327.27, False),
        ("011", "Horas Extras 100%", "4,00", 116.36, False),
        ("030", "Adicional Insalubridade 20%", "", 282.40, False),
        ("101", "INSS", "11,75%", 423.10, True),
        ("110", "Vale Transporte", "6,00%", 192.00, True),
        ("120", "Faltas", "1,00", 106.67, True),
    ])
    _degrade_to_image_page(document, scratch[1], seed=2)
    truths.append(PageTruth(5, "HOLERITE", "holerite escaneado", competence="2024-05",
                            payslip_amounts=amounts, acceptable_amounts=acceptable))

    payload = document.tobytes()
    document.close()
    scratch.close()
    return payload, truths


# ---------------------------------------------------------------- avaliação


@dataclass
class Score:
    model: str
    thinking: str
    pages: int = 0
    classified_ok: int = 0
    failures: int = 0
    retries: int = 0
    hallucinations: int = 0
    field_ok: dict[str, int] = field(default_factory=dict)
    field_total: dict[str, int] = field(default_factory=dict)
    latencies: list[float] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_thought: int = 0
    resolved_model: str = ""
    errors: list[str] = field(default_factory=list)

    def add(self, label: str, ok: int, total: int) -> None:
        self.field_ok[label] = self.field_ok.get(label, 0) + ok
        self.field_total[label] = self.field_total.get(label, 0) + total

    def pct(self, label: str) -> str:
        total = self.field_total.get(label, 0)
        return f"{100 * self.field_ok.get(label, 0) / total:.0f}%" if total else "-"


def _norm_time(value: str | None) -> str | None:
    if not value:
        return None
    match = re.match(r"^\s*(\d{1,2})\s*[:hH]\s*(\d{2})", str(value))
    return f"{int(match[1]):02d}:{match[2]}" if match else str(value).strip()


def _score_time_cards(score: Score, truth: PageTruth, time_cards: list) -> None:
    predicted: dict[str, object] = {}
    for entry in time_cards:
        predicted.setdefault(entry.date, entry)
    ok = total = 0
    for iso_date, expected in truth.time_cards.items():
        entry = predicted.get(iso_date)
        got = [_norm_time(getattr(entry, name)) if entry else None for name in TIME_FIELDS]
        if expected is None:
            if any(got):
                score.hallucinations += 1
            continue
        for want, have in zip(expected, got):
            total += 1
            if want is None:
                ok += have is None
                score.hallucinations += have is not None
            else:
                ok += have == want
    score.hallucinations += sum(1 for iso_date in predicted if iso_date not in truth.time_cards)
    score.add(truth.label, ok, total)


def _score_payslips(score: Score, truth: PageTruth, payslips: list) -> None:
    got = [(round(abs(entry.amount), 2), entry.competence) for entry in payslips]
    found = sum(1 for amount in truth.payslip_amounts if any(abs(g - amount) < 0.006 for g, _ in got))
    competence_ok = sum(1 for _, competence in got if competence == truth.competence)
    score.add(truth.label, found, len(truth.payslip_amounts))
    score.add("competência", competence_ok, len(got))
    score.hallucinations += sum(
        1 for g, _ in got if not any(abs(g - amount) < 0.006 for amount in truth.acceptable_amounts)
    )


def _evaluate(model: str, thinking: str, runs: int, image_parts: dict, truths: list[PageTruth]) -> Score:
    score = Score(model=model, thinking=thinking)
    classifier = GeminiDocumentClassifier(api_key=settings.gemini_api_key, model_name=model)
    if thinking != "default":
        classifier._config = classifier._config.model_copy(
            update={"thinking_config": types.ThinkingConfig(thinking_level=thinking)}
        )

    models_api = classifier._client.models
    original = models_api.generate_content
    last_response: dict[str, object] = {}

    def capture(**kwargs):
        response = original(**kwargs)
        last_response["value"] = response
        return response

    models_api.generate_content = capture

    for _ in range(runs):
        for truth in truths:
            score.pages += 1
            outcome = None
            for attempt, delay in enumerate((0, *RETRY_DELAYS)):
                time.sleep(delay)
                started = time.perf_counter()
                try:
                    outcome = classifier._call_model(
                        [(truth.page_number, image_parts[truth.page_number])]
                    ).get(truth.page_number)
                    if outcome is None:
                        raise ValueError("PAGE_MISSING")
                    score.latencies.append(time.perf_counter() - started)
                    break
                except errors.APIError as exc:
                    if exc.code in RETRY_CODES and attempt < len(RETRY_DELAYS):
                        score.retries += 1
                        continue
                    score.errors.append(f"p{truth.page_number}: {exc.code} {str(exc.message)[:60]}")
                    break
                except Exception as exc:  # JSON inválido, schema etc.
                    score.errors.append(f"p{truth.page_number}: {type(exc).__name__}")
                    break
            if outcome is None:
                score.failures += 1
                continue

            response = last_response.get("value")
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                score.tokens_in += usage.prompt_token_count or 0
                score.tokens_out += usage.candidates_token_count or 0
                score.tokens_thought += usage.thoughts_token_count or 0
            score.resolved_model = getattr(response, "model_version", "") or score.resolved_model

            if outcome["classification"].document_type.value == truth.document_type:
                score.classified_ok += 1
            if truth.time_cards is not None:
                _score_time_cards(score, truth, outcome["time_cards"])
            elif truth.payslip_amounts:
                _score_payslips(score, truth, outcome["payslips"])
            else:
                score.hallucinations += len(outcome["time_cards"]) + len(outcome["payslips"])
    return score


def _print_table(scores: list[Score]) -> None:
    headers = [
        "modelo", "thinking", "classif.", "ponto nat.", "ponto esc.", "holer. nat.", "holer. esc.",
        "compet.", "alucin.", "falhas", "lat. média", "lat. máx", "tok in/out/think por pág.", "retries",
    ]
    rows = []
    for s in scores:
        answered = max(len(s.latencies), 1)
        rows.append([
            s.model, s.thinking,
            f"{s.classified_ok}/{s.pages}",
            s.pct("ponto nativo"), s.pct("ponto escaneado"),
            s.pct("holerite nativo"), s.pct("holerite escaneado"), s.pct("competência"),
            str(s.hallucinations), str(s.failures),
            f"{sum(s.latencies) / answered:.1f}s" if s.latencies else "-",
            f"{max(s.latencies):.1f}s" if s.latencies else "-",
            f"{s.tokens_in // answered}/{s.tokens_out // answered}/{s.tokens_thought // answered}",
            str(s.retries),
        ])
    widths = [max(len(str(r[i])) for r in [headers, *rows]) for i in range(len(headers))]
    print("| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |")
    print("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    for row in rows:
        print("| " + " | ".join(str(c).ljust(w) for c, w in zip(row, widths)) + " |")
    for s in scores:
        if s.resolved_model and s.resolved_model != s.model:
            print(f"* {s.model} respondeu como {s.resolved_model}")
        for error in s.errors[:4]:
            print(f"! {s.model} [{s.thinking}] {error}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--thinking", default="default", help="default, MINIMAL, LOW, MEDIUM, HIGH (lista)")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--save-pdf", type=Path, help="salva o PDF sintético para inspeção visual")
    args = parser.parse_args()

    if not settings.gemini_api_key.strip():
        print("GEMINI_API_KEY ausente.")
        return 1

    pdf_bytes, truths = build_eval_pdf()
    if args.save_pdf:
        args.save_pdf.write_bytes(pdf_bytes)
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    image_parts = {truth.page_number: _render_page(document, truth.page_number) for truth in truths}
    document.close()

    configs = [
        (model.strip(), level.strip())
        for model in args.models.split(",") if model.strip()
        for level in args.thinking.split(",") if level.strip()
    ]
    print(f"Avaliando {len(configs)} configuração(ões) x {len(truths)} páginas x {args.runs} run(s)...")
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(configs)) as executor:
        futures = [executor.submit(_evaluate, model, level, args.runs, image_parts, truths) for model, level in configs]
        scores = [future.result() for future in futures]
    print(f"Concluído em {time.perf_counter() - started:.0f}s\n")
    _print_table(scores)
    return 0


if __name__ == "__main__":
    sys.exit(main())
