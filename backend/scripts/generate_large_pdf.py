"""Gera um PDF sintético grande (só dados fictícios) para testar carga do pipeline.

Mistura petições/peças processuais com 12 holerites e 12 cartões de ponto
(alguns simulando digitalização, sem camada de texto).

Uso (a partir de backend/):
  python scripts/generate_large_pdf.py            # 500 páginas
  python scripts/generate_large_pdf.py 1500
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evaluate_models import (  # noqa: E402
    _degrade_to_image_page,
    _payslip,
    _petition,
    _time_card,
)

OUTPUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "processo_grande.pdf"
SCANNED_MONTHS = {3, 7, 11}


def _payslip_items(rng: random.Random) -> list[tuple[str, str, str, float, bool]]:
    overtime = round(rng.uniform(150, 600), 2)
    inss = round(rng.uniform(380, 450), 2)
    return [
        ("001", "Salário Base", "220,00", 3200.00, False),
        ("010", "Horas Extras 50%", f"{rng.randint(8, 30)},00", overtime, False),
        ("020", "DSR s/ Horas Extras", "", round(overtime / 5, 2), False),
        ("101", "INSS", "11,68%", inss, True),
        ("110", "Vale Transporte", "6,00%", 192.00, True),
    ]


def main() -> int:
    total_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    rng = random.Random(7)
    document = fitz.open()
    scratch = fitz.open()

    months = list(range(1, 13))
    special: dict[int, tuple[str, int]] = {}
    for index, month in enumerate(months):
        special[int(total_pages * (0.30 + index * 0.025))] = ("holerite", month)
        special[int(total_pages * (0.62 + index * 0.025))] = ("ponto", month)

    month_names = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
                   "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
    for page_number in range(1, total_pages + 1):
        kind, month = special.get(page_number, ("peticao", 0))
        scanned = month in SCANNED_MONTHS
        target = scratch.new_page() if scanned else document.new_page()
        if kind == "holerite":
            _payslip(target, f"{month_names[month - 1]}/2024", _payslip_items(rng))
        elif kind == "ponto":
            _time_card(target, 2024, month, rng, holidays=set(), missing_out={rng.randint(2, 27)})
        else:
            _petition(target)
        if scanned:
            _degrade_to_image_page(document, target, seed=month)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT, garbage=3, deflate=True)
    document.close()
    scratch.close()
    size_mb = OUTPUT.stat().st_size / 1024 / 1024
    print(f"PDF gerado: {OUTPUT} ({total_pages} páginas, {size_mb:.1f} MB)")
    print("Holerites e cartões de ponto: 12 de cada; meses 3, 7 e 11 simulam digitalização.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
