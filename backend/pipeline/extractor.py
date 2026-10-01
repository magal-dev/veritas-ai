"""Camada 1–2: leitura local e heurísticas.

Camada 1: texto de todas as páginas via PyMuPDF + palavras-chave e padrões tabulares
(horários, valores monetários) por regex.
Camada 2: TOC, densidade de texto, vizinhos de hits e confirmação de tabelas com
pdfplumber apenas na shortlist (a detecção de tabelas é a operação local mais cara).
Trilha visual: página com pouco texto extraível e imagem embutida (ou praticamente um
raster) é pontuada sem API por um pixmap cinza de 72 DPI (faixas de linhas com tinta e
traços horizontais). Essas páginas só ocupam as vagas que sobram depois das candidatas
de texto. Limitação conhecida: uma petição escaneada também tem muitas faixas de texto e
pode ocupar uma vaga restante; o Gemini a classifica como IRRELEVANTE.
Não persiste texto nem imagem: o pixmap é descartado ao fim de cada página. O tempfile do PDF é responsabilidade do service (unlink no finally).
"""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz
import pdfplumber

from core.logging import logger

# Palavras-chave da camada 1 (AGENTS.md §6). As fortes identificam o tipo documental;
# as fracas aparecem também em petições e sentenças, por isso pesam menos no score.
STRONG_KEYWORDS = [
    "cartão de ponto",
    "horas trabalhadas",
    "holerite",
    "salário bruto",
    "contracheque",
]
WEAK_KEYWORDS = [
    "entrada",
    "saída",
    "inss",
    "fgts",
]
LAYER1_KEYWORDS = STRONG_KEYWORDS + WEAK_KEYWORDS

STRONG_KEYWORD_SCORE = 300.0
WEAK_KEYWORD_SCORE = 50.0
PATTERN_HIT_SCORE = 10.0
MAX_SCORED_PATTERN_HITS = 20
TABLE_SCORE = 50.0
TOC_SCORE = 30.0
NEIGHBOR_SCORE = 5.0

# Horários (08:00) e valores monetários (3.500,00): indicam cartão de ponto ou holerite.
TIME_PATTERN = re.compile(r"\b\d{1,2}:\d{2}\b")
MONEY_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b")
MIN_PATTERN_HITS = 4

# 25 candidatas = 5 chamadas Gemini x 5 páginas por chamada (classifier.PAGES_PER_CALL).
MAX_CANDIDATE_PAGES = 25
# pdfplumber.extract_tables só roda nas páginas mais bem pontuadas.
TABLE_CHECK_PAGES = 10

# Trilha visual (PDF escaneado). Página com até MAX_VISUAL_TEXT_CHARS caracteres não
# brancos e alguma imagem embutida é visual; o limite comporta o rodapé de assinatura
# do PJe sem abranger uma petição com texto.
MAX_VISUAL_TEXT_CHARS = 200
# Imagem cobrindo quase toda a página: scan com camada OCR inútil (sem sinal de texto).
RASTER_COVERAGE_MIN = 0.85
VISUAL_DPI = 72
# Pixel é tinta se mais escuro que INK_RELATIVE x média da página (o papel domina a
# média, então o limiar acompanha scans claros ou escuros).
INK_RELATIVE = 0.7
# Fração mínima de pixels de tinta por linha para a linha contar como "com tinta".
INK_ROW_MIN_RATIO = 0.005
# Página em branco / ruído de scanner fica abaixo; foto ou página preta fica acima.
MIN_INK_RATIO = 0.0005
MAX_INK_RATIO = 0.5
# Cartão de ponto ou holerite: muitas faixas de linhas, ou traços de tabela.
MIN_VISUAL_BANDS = 8
MIN_RULED_ROWS = 16
# Vizinho visual (continuação de cartão escaneado) precisa de algumas linhas; um
# carimbo isolado tem uma ou duas faixas.
MIN_NEIGHBOR_BANDS = 3
# Traço horizontal: sequência de tinta com pelo menos esta fração da largura.
RULE_MIN_RUN_RATIO = 0.06
MAX_SCORED_BANDS = 40
MAX_SCORED_RULED_ROWS = 40
VISUAL_BAND_SCORE = 2.0
VISUAL_RULE_SCORE = 1.0


@dataclass
class PageSignal:
    page_number: int
    keyword_hits: list[str] = field(default_factory=list)
    pattern_hits: int = 0
    text_density: float = 0.0
    table_hint: bool = False
    toc_match: bool = False
    score: float = 0.0
    # Trilha visual: só métricas agregadas, nunca pixels.
    visual: bool = False
    ink_ratio: float = 0.0
    ink_bands: int = 0
    ruled_rows: int = 0


@dataclass
class ExtractionSignals:
    """Sinais da triagem. Não contém texto de página; nada aqui deve ir para o banco."""

    pdf_page_count: int
    toc_titles: list[str] = field(default_factory=list)
    candidate_pages: list[int] = field(default_factory=list)
    overflow_candidate_pages: list[int] = field(default_factory=list)
    page_signals: list[PageSignal] = field(default_factory=list)


class DocumentExtractor:
    """Contrato da extração local. Implementação real: PyMuPDF + heurísticas."""

    def extract(self, pdf_path: Path) -> ExtractionSignals:
        raise NotImplementedError


def _normalize_text(text: str) -> str:
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


_NORMALIZED_KEYWORDS = [(keyword, _normalize_text(keyword)) for keyword in LAYER1_KEYWORDS]
_STRONG_SET = frozenset(STRONG_KEYWORDS)


def _find_keyword_hits(text: str) -> list[str]:
    normalized = _normalize_text(text)
    return [keyword for keyword, needle in _NORMALIZED_KEYWORDS if needle in normalized]


def _count_pattern_hits(text: str) -> int:
    return len(TIME_PATTERN.findall(text)) + len(MONEY_PATTERN.findall(text))


def _toc_keyword_pages(toc: list, page_count: int) -> set[int]:
    pages: set[int] = set()
    for entry in toc:
        if len(entry) < 3:
            continue
        title = str(entry[1])
        page_number = int(entry[2])
        if page_number < 1 or page_number > page_count:
            continue
        if _find_keyword_hits(title):
            pages.add(page_number)
    return pages


def _score_page(signal: PageSignal) -> float:
    score = 0.0
    for keyword in signal.keyword_hits:
        score += STRONG_KEYWORD_SCORE if keyword in _STRONG_SET else WEAK_KEYWORD_SCORE
    score += min(signal.pattern_hits, MAX_SCORED_PATTERN_HITS) * PATTERN_HIT_SCORE
    if signal.table_hint:
        score += TABLE_SCORE
    if signal.toc_match:
        score += TOC_SCORE
    score += signal.text_density * 10.0
    return score


def _has_primary_signal(signal: PageSignal) -> bool:
    # Petições citam INSS/FGTS, um horário ou o valor da causa: palavra fraca sozinha não
    # basta, a página precisa de densidade tabular (MIN_PATTERN_HITS) como cartão/holerite.
    has_strong = any(keyword in _STRONG_SET for keyword in signal.keyword_hits)
    return has_strong or signal.pattern_hits >= MIN_PATTERN_HITS or signal.toc_match


def _rank(signals: list[PageSignal]) -> list[PageSignal]:
    return sorted(signals, key=lambda item: (-item.score, item.page_number))


def _image_stats(page: fitz.Page) -> tuple[int, float]:
    """Quantidade de imagens e fração da página coberta por elas, sem decodificá-las."""
    page_rect = page.rect
    page_area = max(float(page_rect.width * page_rect.height), 1.0)
    infos = page.get_image_info()
    covered = 0.0
    for info in infos:
        bbox = fitz.Rect(info.get("bbox", (0, 0, 0, 0))) & page_rect
        if not bbox.is_empty:
            covered += float(bbox.width * bbox.height)
    return len(infos), min(covered / page_area, 1.0)


def _is_visual_page(text: str, image_count: int, coverage: float, signal: PageSignal) -> bool:
    if _has_primary_signal(signal):
        return False
    char_count = sum(1 for char in text if not char.isspace())
    if char_count <= MAX_VISUAL_TEXT_CHARS and image_count >= 1:
        return True
    return coverage >= RASTER_COVERAGE_MIN


def _measure_visual(page: fitz.Page, signal: PageSignal) -> None:
    """Pixmap cinza pequeno: proporção de tinta, faixas de linhas e traços horizontais."""
    pixmap = page.get_pixmap(dpi=VISUAL_DPI, colorspace=fitz.csGRAY, alpha=False)
    width, height, stride = pixmap.width, pixmap.height, pixmap.stride
    samples = pixmap.samples
    pixmap = None
    if width == 0 or height == 0:
        return
    threshold = int(sum(samples) / len(samples) * INK_RELATIVE)
    binary = samples.translate(bytes(1 if value < threshold else 0 for value in range(256)))
    samples = None
    min_row_ink = max(2, int(width * INK_ROW_MIN_RATIO))
    rule = re.compile(rb"\x01{%d,}" % max(2, int(width * RULE_MIN_RUN_RATIO)))

    ink_pixels = bands = ruled = 0
    previous_inked = False
    for row_start in range(0, height * stride, stride):
        row = binary[row_start : row_start + width]
        row_ink = row.count(1)
        ink_pixels += row_ink
        inked = row_ink >= min_row_ink
        if inked and not previous_inked:
            bands += 1
        previous_inked = inked
        if rule.search(row):
            ruled += 1

    signal.ink_ratio = ink_pixels / (width * height)
    signal.ink_bands = bands
    signal.ruled_rows = ruled


def _has_ink(signal: PageSignal) -> bool:
    return MIN_INK_RATIO <= signal.ink_ratio <= MAX_INK_RATIO


def _is_visual_table(signal: PageSignal) -> bool:
    if not signal.visual or not _has_ink(signal):
        return False
    if signal.ink_bands >= MIN_VISUAL_BANDS:
        return True
    return signal.ruled_rows >= MIN_RULED_ROWS and signal.ink_bands >= MIN_NEIGHBOR_BANDS


def _visual_score(signal: PageSignal) -> float:
    return (
        min(signal.ink_bands, MAX_SCORED_BANDS) * VISUAL_BAND_SCORE
        + min(signal.ruled_rows, MAX_SCORED_RULED_ROWS) * VISUAL_RULE_SCORE
    )


class LocalDocumentExtractor(DocumentExtractor):
    """Camadas 1–2: triagem local sem chamadas à API."""

    def extract(self, pdf_path: Path) -> ExtractionSignals:
        started = time.perf_counter()
        try:
            document = fitz.open(pdf_path)
        except Exception as exc:
            raise ValueError("INVALID_PDF") from exc

        signals_by_page: dict[int, PageSignal] = {}
        try:
            page_count = document.page_count
            toc = document.get_toc() or []
            toc_titles = [str(entry[1]) for entry in toc if len(entry) > 1]
            toc_pages = _toc_keyword_pages(toc, page_count)

            for index, page in enumerate(document, start=1):
                text = page.get_text("text") or ""
                area = max(float(page.rect.width * page.rect.height), 1.0)
                signal = PageSignal(
                    page_number=index,
                    keyword_hits=_find_keyword_hits(text),
                    pattern_hits=_count_pattern_hits(text),
                    text_density=len(text) / area,
                    toc_match=index in toc_pages,
                )
                signal.score = _score_page(signal)
                image_count, coverage = _image_stats(page)
                if _is_visual_page(text, image_count, coverage, signal):
                    signal.visual = True
                    _measure_visual(page, signal)
                signals_by_page[index] = signal
        finally:
            document.close()

        # Vizinhos ±1 de páginas com keyword hit, se tiverem algum padrão tabular
        # (ex.: continuação de cartão de ponto sem cabeçalho).
        neighbor_pages: set[int] = set()
        for page_number, signal in signals_by_page.items():
            if not signal.keyword_hits or not _has_primary_signal(signal):
                continue
            for neighbor in (page_number - 1, page_number + 1):
                neighbor_signal = signals_by_page.get(neighbor)
                if (
                    neighbor_signal is None
                    or neighbor_signal.visual
                    or _has_primary_signal(neighbor_signal)
                ):
                    continue
                # Petição vizinha de um anexo cita INSS/FGTS e um ou dois números; um
                # fim de cartão de ponto sem cabeçalho não tem palavra-chave.
                if neighbor_signal.pattern_hits > 0 and not neighbor_signal.keyword_hits:
                    neighbor_pages.add(neighbor)

        ranked: list[PageSignal] = []
        for page_number, signal in signals_by_page.items():
            if _has_primary_signal(signal):
                ranked.append(signal)
            elif page_number in neighbor_pages:
                signal.score = NEIGHBOR_SCORE
                ranked.append(signal)

        ranked = _rank(ranked)
        table_checked = self._confirm_tables(pdf_path, ranked[:TABLE_CHECK_PAGES])
        if table_checked:
            ranked = _rank(ranked)

        visual_ranked = _rank_visual(signals_by_page, ranked)

        # Candidatas de texto têm prioridade; páginas visuais só ocupam as vagas restantes.
        free_slots = MAX_CANDIDATE_PAGES - min(len(ranked), MAX_CANDIDATE_PAGES)
        candidate_pages = [item.page_number for item in ranked[:MAX_CANDIDATE_PAGES]]
        candidate_pages += [item.page_number for item in visual_ranked[:free_slots]]
        overflow_pages = [item.page_number for item in ranked[MAX_CANDIDATE_PAGES:]]
        overflow_pages += [item.page_number for item in visual_ranked[free_slots:]]

        logger.info(
            "extractor.complete pdf_page_count=%s candidate_page_count=%s overflow_count=%s "
            "table_checked=%s visual_page_count=%s visual_candidate_count=%s duration_ms=%s",
            page_count,
            len(candidate_pages),
            len(overflow_pages),
            table_checked,
            sum(1 for signal in signals_by_page.values() if signal.visual),
            min(len(visual_ranked), free_slots),
            int((time.perf_counter() - started) * 1000),
        )

        return ExtractionSignals(
            pdf_page_count=page_count,
            toc_titles=toc_titles,
            candidate_pages=candidate_pages,
            overflow_candidate_pages=overflow_pages,
            page_signals=list(signals_by_page.values()),
        )

    @staticmethod
    def _confirm_tables(pdf_path: Path, shortlist: list[PageSignal]) -> int:
        """Detecta tabelas com pdfplumber só na shortlist e recalcula o score."""
        # Página só imagem nunca chega ao extract_tables (não há texto para o pdfplumber).
        primary = [
            signal for signal in shortlist if _has_primary_signal(signal) and not signal.visual
        ]
        if not primary:
            return 0
        with pdfplumber.open(pdf_path) as pdf:
            for signal in primary:
                page = pdf.pages[signal.page_number - 1]
                try:
                    signal.table_hint = bool(page.extract_tables())
                except Exception:
                    signal.table_hint = False
                finally:
                    page.close()
                signal.score = _score_page(signal)
        return len(primary)


def _rank_visual(
    signals_by_page: dict[int, PageSignal], text_ranked: list[PageSignal]
) -> list[PageSignal]:
    """Páginas visuais com aspecto de tabela e vizinhos ±1 também visuais."""
    accepted: dict[int, PageSignal] = {}
    for page_number, signal in signals_by_page.items():
        if _is_visual_table(signal):
            signal.score = _visual_score(signal)
            accepted[page_number] = signal

    # Continuação de cartão escaneado: o vizinho precisa ser visual e ter algumas linhas.
    anchors = set(accepted) | {
        signal.page_number for signal in text_ranked if signal.keyword_hits
    }
    for anchor in sorted(anchors):
        for neighbor in (anchor - 1, anchor + 1):
            neighbor_signal = signals_by_page.get(neighbor)
            if (
                neighbor_signal is None
                or neighbor in accepted
                or not neighbor_signal.visual
                or not _has_ink(neighbor_signal)
                or neighbor_signal.ink_bands < MIN_NEIGHBOR_BANDS
            ):
                continue
            neighbor_signal.score = NEIGHBOR_SCORE
            accepted[neighbor] = neighbor_signal

    return _rank(list(accepted.values()))


class StubDocumentExtractor(DocumentExtractor):
    """Conta páginas; não extrai texto nem classifica candidatas."""

    def extract(self, pdf_path: Path) -> ExtractionSignals:
        try:
            document = fitz.open(pdf_path)
        except Exception as exc:
            raise ValueError("INVALID_PDF") from exc
        try:
            page_count = document.page_count
            toc = document.get_toc() or []
        finally:
            document.close()

        toc_titles = [str(entry[1]) for entry in toc if len(entry) > 1]
        logger.info(
            "extractor.stub_complete pdf_page_count=%s toc_entries=%s",
            page_count,
            len(toc_titles),
        )
        return ExtractionSignals(
            pdf_page_count=page_count,
            toc_titles=toc_titles,
            candidate_pages=[],
            overflow_candidate_pages=[],
            page_signals=[],
        )
