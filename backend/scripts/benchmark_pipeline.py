"""Mede o tempo da triagem local (camadas 1–2) em um PDF sintético grande.

Não chama o Gemini. O PDF é gerado em tempfile e apagado ao final.
Uso (a partir de backend/): python scripts/benchmark_pipeline.py [total_paginas]
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.extractor import LocalDocumentExtractor  # noqa: E402

PETITION_TEXT = """PETICAO INICIAL
O reclamante requer o pagamento de verbas rescisorias, recolhimento de FGTS
e INSS sobre as parcelas deferidas, bem como horas extras decorrentes da
jornada de entrada e saida registrada. Requer ainda a multa do art. 477 da CLT.
"""

PAYSLIP_TEXT = """HOLERITE / CONTRACHEQUE
Competencia: 03/2024
SALARIO BRUTO ................ R$ 3.500,00
INSS ......................... R$   385,00
FGTS ......................... R$   280,00
HORAS EXTRAS 50% ............. R$   450,00
TOTAL LIQUIDO ................ R$ 2.665,00
"""

TIME_CARD_TEXT = """CARTAO DE PONTO - MARCO/2024
Data       Entrada  Saida    Intervalo
01/03/2024  08:00   17:00   12:00-13:00
02/03/2024  08:05   17:10   12:00-13:00
03/03/2024  07:55   17:00   12:00-13:00
04/03/2024  08:02   17:04   12:00-13:00
"""


def _build_pdf(path: Path, total_pages: int) -> set[int]:
    document = fitz.open()
    relevant_positions = {
        total_pages // 3: PAYSLIP_TEXT,
        total_pages // 3 + 1: PAYSLIP_TEXT,
        2 * total_pages // 3: TIME_CARD_TEXT,
        2 * total_pages // 3 + 1: TIME_CARD_TEXT,
    }
    for page_number in range(1, total_pages + 1):
        page = document.new_page()
        page.insert_text((72, 72), relevant_positions.get(page_number, PETITION_TEXT), fontsize=11)
    document.save(path)
    document.close()
    return set(relevant_positions)


def main() -> int:
    total_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    handle.close()
    pdf_path = Path(handle.name)
    try:
        relevant = _build_pdf(pdf_path, total_pages)
        started = time.perf_counter()
        signals = LocalDocumentExtractor().extract(pdf_path)
        duration_ms = int((time.perf_counter() - started) * 1000)
    finally:
        pdf_path.unlink(missing_ok=True)

    found = relevant & set(signals.candidate_pages)
    print(f"paginas: {signals.pdf_page_count}")
    print(f"duracao_triagem_ms: {duration_ms}")
    print(f"candidatas: {signals.candidate_pages}")
    print(f"overflow: {len(signals.overflow_candidate_pages)}")
    print(f"paginas_relevantes: {sorted(relevant)}")
    print(f"relevantes_nas_candidatas: {len(found)}/{len(relevant)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
