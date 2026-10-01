"""Gera PDF de exemplo com holerite e cartão de ponto para testes locais."""

from pathlib import Path

import pymupdf as fitz

OUTPUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "processo_exemplo.pdf"


def main() -> None:
    doc = fitz.open()

    # Página irrelevante (petição)
    page1 = doc.new_page()
    page1.insert_text(
        (72, 72),
        "PETICAO INICIAL\n\nRequer o pagamento de verbas rescisorias.\nProcesso trabalhista.",
        fontsize=11,
    )

    # Holerite
    page2 = doc.new_page()
    page2.insert_text(
        (72, 72),
        """HOLERITE / CONTRACHEQUE
Competencia: 03/2024
Empresa: Industria Exemplo Ltda

SALARIO BRUTO ................ R$ 3.500,00
INSS ......................... R$   385,00
FGTS ......................... R$   280,00
HORAS EXTRAS 50% ............. R$   450,00
TOTAL LIQUIDO ................ R$ 2.665,00
""",
        fontsize=11,
    )

    # Cartão de ponto
    page3 = doc.new_page()
    page3.insert_text(
        (72, 72),
        """CARTAO DE PONTO - MARCO/2024
Horas trabalhadas

Data       Entrada  Saida    Intervalo
01/03/2024  08:00   17:00   12:00-13:00
02/03/2024  08:05   17:10   12:00-13:00
03/03/2024  07:55   17:00   12:00-13:00
""",
        fontsize=11,
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc.save(OUTPUT)
    doc.close()
    print(f"PDF gerado: {OUTPUT}")


if __name__ == "__main__":
    main()
