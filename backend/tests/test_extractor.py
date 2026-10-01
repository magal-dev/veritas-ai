import io
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageEnhance, ImageFilter

from pipeline.extractor import (
    MAX_CANDIDATE_PAGES,
    MAX_VISUAL_TEXT_CHARS,
    MIN_NEIGHBOR_BANDS,
    MIN_VISUAL_BANDS,
    LocalDocumentExtractor,
)


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


# ------------------------------------------------------------- PDF escaneado
# Páginas "escaneadas" sintéticas: desenhadas com fitz e degradadas a imagem como em
# scripts/evaluate_models.py::_degrade_to_image_page (SCANNED_MONTHS do PDF grande).


def _draw_time_card(page: fitz.Page, rows: int = 25) -> None:
    page.insert_text((40, 50), "CARTAO DE PONTO - REGISTRO ELETRONICO", fontsize=12)
    page.insert_text((40, 68), "Periodo: 01/03/2024 a 31/03/2024", fontsize=9)
    y = 110
    for x, header in zip([40, 120, 200, 280, 360], ["Data", "Entrada", "Saida Int.", "Retorno", "Saida"]):
        page.insert_text((x, y), header, fontsize=8.5)
    page.draw_line((38, y + 4), (560, y + 4))
    for day in range(1, rows + 1):
        y += 19
        values = [f"{day:02d}/03/2024", "08:00", "12:00", "13:00", "17:00"]
        for x, value in zip([40, 120, 200, 280, 360], values):
            page.insert_text((x, y), value, fontsize=8.5)
        page.draw_line((38, y + 5), (560, y + 5), color=(0.8, 0.8, 0.8))


def _draw_stamp(page: fitz.Page) -> None:
    page.draw_rect(fitz.Rect(380, 650, 540, 720), width=2)
    page.insert_text((395, 690), "RECEBIDO 12/03/2024", fontsize=11)


def _degraded_image(source_page: fitz.Page, seed: int) -> bytes:
    """Simula digitalização: raster 110 DPI, rotação, blur, ruído, contraste baixo, JPEG ruim."""
    pixmap = source_page.get_pixmap(dpi=110, colorspace=fitz.csGRAY)
    image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("L")
    image = image.rotate(1.4 if seed % 2 else -1.1, resample=Image.BICUBIC, expand=True, fillcolor=255)
    image = image.filter(ImageFilter.GaussianBlur(0.7))
    image = Image.blend(image, Image.effect_noise(image.size, 30).convert("L"), 0.12)
    image = ImageEnhance.Contrast(image).enhance(0.75)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=45)
    return buffer.getvalue()


def _add_scanned(
    document: fitz.Document, draw=None, seed: int = 1, footer: str = "", rect=None
) -> None:
    scratch = fitz.open()
    source = scratch.new_page()
    if draw is not None:
        draw(source)
    stream = _degraded_image(source, seed)
    scratch.close()
    page = document.new_page()
    page.insert_image(rect or page.rect, stream=stream)
    if footer:
        page.insert_text((40, 830), footer, fontsize=4)


def _add_text(document: fitz.Document, text: str) -> None:
    document.new_page().insert_text((72, 72), text)


def _save(document: fitz.Document, path: Path) -> Path:
    path.write_bytes(document.tobytes())
    document.close()
    return path


def test_extractor_keeps_native_time_card_as_candidate(tmp_path: Path):
    document = fitz.open()
    _add_text(document, "Pagina 1")
    _draw_time_card(document.new_page())
    _add_scanned(document, _draw_time_card)

    signals = LocalDocumentExtractor().extract(_save(document, tmp_path / "nativo.pdf"))

    assert signals.candidate_pages[0] == 2
    assert not signals.page_signals[1].visual


def test_extractor_flags_scanned_time_card(tmp_path: Path):
    document = fitz.open()
    _add_text(document, "Pagina 1")
    _add_scanned(document, _draw_time_card, seed=1)
    _add_scanned(document, _draw_time_card, seed=2)

    signals = LocalDocumentExtractor().extract(_save(document, tmp_path / "escaneado.pdf"))

    assert signals.candidate_pages == [2, 3] or signals.candidate_pages == [3, 2]
    scanned = signals.page_signals[1]
    assert scanned.visual
    assert scanned.ink_bands >= MIN_VISUAL_BANDS


def test_extractor_ignores_scanned_blank_and_stamp_pages(tmp_path: Path):
    document = fitz.open()
    _add_scanned(document, None, seed=1)
    _add_text(document, "Pagina 2")
    _add_scanned(document, _draw_stamp, seed=2)

    signals = LocalDocumentExtractor().extract(_save(document, tmp_path / "branco.pdf"))

    assert signals.page_signals[0].visual
    assert signals.page_signals[2].visual
    assert signals.candidate_pages == []
    assert signals.overflow_candidate_pages == []


def test_extractor_visual_text_threshold(tmp_path: Path):
    words = ("processo trabalhista " * 20).replace(" ", "")
    at_limit = words[:MAX_VISUAL_TEXT_CHARS]
    over_limit = words[: MAX_VISUAL_TEXT_CHARS + 1]
    # Imagem em metade da página: só a regra de texto curto decide.
    half = fitz.Rect(0, 0, 595, 421)
    document = fitz.open()
    _add_scanned(document, _draw_time_card, seed=1, footer=at_limit, rect=half)
    _add_scanned(document, _draw_time_card, seed=2, footer=over_limit, rect=half)
    # Imagem na página inteira (praticamente raster): visual mesmo com texto longo.
    _add_scanned(document, _draw_time_card, seed=3, footer=over_limit)

    signals = LocalDocumentExtractor().extract(_save(document, tmp_path / "limiar.pdf"))

    assert signals.page_signals[0].visual
    assert not signals.page_signals[1].visual
    assert signals.page_signals[2].visual
    assert 1 in signals.candidate_pages
    assert 2 not in signals.candidate_pages
    assert 3 in signals.candidate_pages


def test_extractor_ignores_native_petition_with_logo(tmp_path: Path):
    document = fitz.open()
    page = document.new_page()
    logo = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 40, 40), False)
    logo.clear_with(0)
    page.insert_image(fitz.Rect(40, 30, 100, 90), pixmap=logo)
    lines = [f"Linha {index} da peticao: requer o pagamento de verbas rescisorias." for index in range(30)]
    page.insert_text((72, 120), "\n".join(lines), fontsize=9)

    signals = LocalDocumentExtractor().extract(_save(document, tmp_path / "logo.pdf"))

    assert not signals.page_signals[0].visual
    assert signals.candidate_pages == []


def test_extractor_text_candidates_take_priority_over_visual(tmp_path: Path):
    document = fitz.open()
    for index in range(MAX_CANDIDATE_PAGES):
        _add_text(document, f"holerite INSS pagina {index}")
    _add_scanned(document, _draw_time_card)

    signals = LocalDocumentExtractor().extract(_save(document, tmp_path / "cheio.pdf"))

    scanned_page = MAX_CANDIDATE_PAGES + 1
    assert len(signals.candidate_pages) == MAX_CANDIDATE_PAGES
    assert scanned_page not in signals.candidate_pages
    assert signals.overflow_candidate_pages == [scanned_page]


def test_extractor_visual_pages_fill_remaining_slots(tmp_path: Path):
    document = fitz.open()
    for index in range(MAX_CANDIDATE_PAGES - 1):
        _add_text(document, f"holerite INSS pagina {index}")
    _add_scanned(document, _draw_time_card, seed=1)
    _add_scanned(document, _draw_time_card, seed=2)

    signals = LocalDocumentExtractor().extract(_save(document, tmp_path / "vagas.pdf"))

    scanned = {MAX_CANDIDATE_PAGES, MAX_CANDIDATE_PAGES + 1}
    assert len(signals.candidate_pages) == MAX_CANDIDATE_PAGES
    assert sorted(signals.candidate_pages[: MAX_CANDIDATE_PAGES - 1]) == list(
        range(1, MAX_CANDIDATE_PAGES)
    )
    assert signals.candidate_pages[-1] in scanned
    assert len(signals.overflow_candidate_pages) == 1
    assert signals.overflow_candidate_pages[0] in scanned


def test_extractor_includes_visual_neighbor_only_next_to_scanned_card(tmp_path: Path):
    def short_continuation(page: fitz.Page) -> None:
        _draw_time_card(page, rows=MIN_NEIGHBOR_BANDS + 1)

    alone = fitz.open()
    _add_scanned(alone, short_continuation)
    _add_text(alone, "Pagina 2")
    alone_signals = LocalDocumentExtractor().extract(_save(alone, tmp_path / "sozinha.pdf"))

    next_to_card = fitz.open()
    _add_scanned(next_to_card, _draw_time_card, seed=1)
    _add_scanned(next_to_card, short_continuation, seed=2)
    signals = LocalDocumentExtractor().extract(_save(next_to_card, tmp_path / "vizinha.pdf"))

    weak = alone_signals.page_signals[0]
    assert weak.visual
    assert MIN_NEIGHBOR_BANDS <= weak.ink_bands < MIN_VISUAL_BANDS
    assert alone_signals.candidate_pages == []
    assert signals.candidate_pages == [1, 2]


def test_extractor_skips_table_detection_on_image_pages(tmp_path: Path, monkeypatch):
    document = fitz.open()
    _add_text(document, "CARTAO DE PONTO marco/2024")
    _add_scanned(document, _draw_time_card)
    path = _save(document, tmp_path / "tabelas.pdf")

    opened_pages: list[int] = []
    original = LocalDocumentExtractor._confirm_tables

    def spy(pdf_path, shortlist):
        opened_pages.extend(signal.page_number for signal in shortlist)
        return original(pdf_path, shortlist)

    monkeypatch.setattr(LocalDocumentExtractor, "_confirm_tables", staticmethod(spy))

    signals = LocalDocumentExtractor().extract(path)

    assert opened_pages == [1]
    assert signals.candidate_pages == [1, 2]
