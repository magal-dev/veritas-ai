from pathlib import Path

import fitz

from pipeline.extractor import LocalDocumentExtractor, MAX_CANDIDATE_PAGES


def _pdf_with_pages(texts: list[str]) -> bytes:
    document = fitz.open()
    for text in texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def test_extractor_flags_page_with_holerite_keywords(tmp_path: Path):
    pdf_path = tmp_path / "holerite.pdf"
    pdf_path.write_bytes(
        _pdf_with_pages(
            [
                "Pagina 1 sem relevancia",
                "Holerite de pagamento - INSS e FGTS",
                "Pagina 3 generica",
            ]
        )
    )

    signals = LocalDocumentExtractor().extract(pdf_path)

    assert signals.pdf_page_count == 3
    assert 2 in signals.candidate_pages
    assert signals.candidate_pages[0] == 2


def test_extractor_ignores_pages_without_keywords(tmp_path: Path):
    pdf_path = tmp_path / "plain.pdf"
    pdf_path.write_bytes(_pdf_with_pages(["Pagina 1", "Pagina 2", "Pagina 3"]))

    signals = LocalDocumentExtractor().extract(pdf_path)

    assert signals.pdf_page_count == 3
    assert signals.candidate_pages == []
    assert signals.overflow_candidate_pages == []


def test_extractor_caps_candidates(tmp_path: Path):
    texts = [f"holerite INSS pagina {index}" for index in range(1, MAX_CANDIDATE_PAGES + 3)]
    pdf_path = tmp_path / "many.pdf"
    pdf_path.write_bytes(_pdf_with_pages(texts))

    signals = LocalDocumentExtractor().extract(pdf_path)

    assert len(signals.candidate_pages) == MAX_CANDIDATE_PAGES
    assert len(signals.overflow_candidate_pages) == 2


def test_extractor_ranks_strong_keyword_above_petition_weak_keywords(tmp_path: Path):
    pdf_path = tmp_path / "ranking.pdf"
    pdf_path.write_bytes(
        _pdf_with_pages(
            [
                "Requer recolhimento de INSS e FGTS, entrada e saida. Valor R$ 1.000,00",
                "Holerite competencia 03/2024",
            ]
        )
    )

    signals = LocalDocumentExtractor().extract(pdf_path)

    assert signals.candidate_pages[0] == 2


def test_extractor_skips_weak_keyword_page_without_numeric_patterns(tmp_path: Path):
    pdf_path = tmp_path / "peticao.pdf"
    pdf_path.write_bytes(
        _pdf_with_pages(["Peticao: requer recolhimento de INSS e FGTS", "Pagina 2"])
    )

    signals = LocalDocumentExtractor().extract(pdf_path)

    assert signals.candidate_pages == []
    assert signals.overflow_candidate_pages == []


def test_extractor_flags_tabular_page_without_keywords(tmp_path: Path):
    continuation = "\n".join(f"0{day}/03/2024 08:00 12:00 13:00 17:00" for day in range(1, 5))
    pdf_path = tmp_path / "continuacao.pdf"
    pdf_path.write_bytes(_pdf_with_pages(["Pagina 1", continuation]))

    signals = LocalDocumentExtractor().extract(pdf_path)

    assert signals.candidate_pages == [2]


def test_extractor_excludes_neighbor_without_numeric_patterns(tmp_path: Path):
    pdf_path = tmp_path / "exemplo.pdf"
    pdf_path.write_bytes(
        _pdf_with_pages(
            [
                "PETICAO INICIAL\nRequer o pagamento de verbas rescisorias.",
                "HOLERITE / CONTRACHEQUE\nSALARIO BRUTO R$ 3.500,00\nINSS R$ 385,00",
                "CARTAO DE PONTO\nData Entrada Saida\n01/03/2024 08:00 17:00",
            ]
        )
    )

    signals = LocalDocumentExtractor().extract(pdf_path)

    assert sorted(signals.candidate_pages) == [2, 3]
    assert signals.overflow_candidate_pages == []


def test_extractor_includes_neighbor_with_numeric_patterns(tmp_path: Path):
    pdf_path = tmp_path / "vizinho.pdf"
    pdf_path.write_bytes(
        _pdf_with_pages(["CARTAO DE PONTO marco/2024", "01/03/2024 08:00 17:00", "Pagina 3"])
    )

    signals = LocalDocumentExtractor().extract(pdf_path)

    assert signals.candidate_pages == [1, 2]


def test_extractor_skips_petition_with_few_numbers(tmp_path: Path):
    petition = (
        "Requer FGTS e INSS. Jornada com entrada as 08:00 e saida as 18:00.\n"
        "Da-se a causa o valor de R$ 85.000,00."
    )
    pdf_path = tmp_path / "peticao_numeros.pdf"
    pdf_path.write_bytes(_pdf_with_pages([petition, "Holerite competencia 03/2024"]))

    signals = LocalDocumentExtractor().extract(pdf_path)

    assert signals.candidate_pages == [2]
    assert signals.overflow_candidate_pages == []
