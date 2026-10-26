from __future__ import annotations

import json
from pathlib import Path

import pymupdf as fitz
import pytest

from pipeline.time_card_ocr import Word, group_lines, parse_page
from scripts import evaluate_synthetic
from scripts.evaluate_extraction import parse_ground_truth
from scripts.generate_synthetic_cases import COMBINATIONS, CaseSpec, build_case, main, plan_cases


def _case(layout: str, scan: str, seed: int = 3):
    return build_case(CaseSpec(case_id="caso_teste", seed=seed, layout=layout, scan=scan))


def _ocr_lines(page: fitz.Page) -> list[list[Word]]:
    """Palavras do PDF nativo no formato do OCR (uma linha por y), sem Tesseract."""
    words = [
        Word(round(x0), round(y0), round(x1 - x0), round(y1 - y0), text, line=(str(round(y1)),))
        for x0, y0, x1, y1, text, *_ in page.get_text("words")
    ]
    return group_lines(words)


def test_plan_cases_cycles_layouts_and_scans() -> None:
    specs = plan_cases(len(COMBINATIONS) + 1, seed=2)
    assert [(s.layout, s.scan) for s in specs[: len(COMBINATIONS)]] == list(COMBINATIONS)
    assert (specs[-1].layout, specs[-1].scan) == COMBINATIONS[0]
    assert len({s.seed for s in specs}) == len(specs)


def test_build_case_is_deterministic() -> None:
    assert _case("relogio", "medio").gabarito == _case("relogio", "medio").gabarito


def test_gabarito_matches_the_pdf_and_the_evaluation_format() -> None:
    case = _case("relogio", "nativo")
    truth = parse_ground_truth(case.gabarito)
    with fitz.open(stream=case.pdf, filetype="pdf") as document:
        assert document.page_count == case.meta["pdf_pages"]
        kinds = {document[n - 1].get_text().split("\n")[0] for n in truth.relevant_pages}
    assert set(case.meta["time_card_pages"]) <= truth.relevant_pages
    assert any("ESPELHO DE PONTO" in kind for kind in kinds)
    assert truth.time_cards and truth.payslips is not None
    # Layout de um turno só: o intervalo nunca é marcado.
    assert all(row.times["break_start"] is None for row in truth.time_cards)


def test_native_relogio_sheet_is_read_by_the_ocr_layout_rules() -> None:
    # Fidelidade ao layout real: as regras do OCR local reconhecem a folha sintética
    # (com as palavras do PDF no lugar do Tesseract) e leem os horários do gabarito.
    case = _case("relogio", "nativo")
    truth = {row["date"]: row for row in case.gabarito["time_cards"]}
    with fitz.open(stream=case.pdf, filetype="pdf") as document:
        for number in case.meta["time_card_pages"]:
            page = parse_page(_ocr_lines(document[number - 1]), number)
            assert page is not None and page.dates_confirmed
            for cell in page.cells:
                row = truth[cell.day]
                if cell.single_mark:
                    assert cell.first_read in (row["clock_in"], row["clock_out"])
                else:
                    assert cell.first_read == row["clock_in" if cell.slot == 0 else "clock_out"]
            assert {d for d in page.work_days} <= set(truth)


def test_planilha_layout_has_break_times_and_is_not_the_ocr_layout() -> None:
    case = _case("planilha", "nativo")
    assert any(row["break_start"] for row in case.gabarito["time_cards"])
    with fitz.open(stream=case.pdf, filetype="pdf") as document:
        number = case.meta["time_card_pages"][0]
        assert parse_page(_ocr_lines(document[number - 1]), number) is None


def test_scanned_case_has_image_only_time_card_pages() -> None:
    case = _case("relogio", "forte")
    with fitz.open(stream=case.pdf, filetype="pdf") as document:
        for number in case.meta["time_card_pages"]:
            page = document[number - 1]
            assert not page.get_text().strip()
            assert len(page.get_images()) == 1


def test_main_writes_pdf_and_gabarito(tmp_path: Path, capsys) -> None:
    assert main([str(tmp_path), "--cases", "2", "--seed", "5"]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "caso_01.gabarito.json", "caso_01.pdf", "caso_02.gabarito.json", "caso_02.pdf",
    ]
    gabarito = json.loads((tmp_path / "caso_01.gabarito.json").read_text(encoding="utf-8"))
    assert gabarito["meta"]["layout"] == "relogio"
    assert "caso_02" in capsys.readouterr().out


# ---------------------------------------------------------------- avaliação em lote


def _report(calls: int, marks: int, empty: int, wrong: int, local_pages: int) -> dict:
    return {
        "gemini_call_count": calls,
        "pages_sent_whole": 1,
        "triage": {"relevant_pages": 4, "relevant_in_candidates": 3},
        "time_cards": {"expected_marks": marks, "empty_marks": empty, "wrong_marks": wrong,
                       "hallucinated_fields": 0, "extra_days": 0, "unconfirmed_date_days": 0},
        "payslips": {"expected_items": 5, "found_items": 5},
        "local_ocr": {"pages": local_pages},
    }


def _write_metrics(folder: Path, name: str, layout: str, scan: str, report: dict) -> None:
    (folder / f"{name}.metricas.json").write_text(
        json.dumps({"meta": {"layout": layout, "scan": scan}, "report": report}), encoding="utf-8"
    )


def test_summarize_groups_by_layout_and_scan(tmp_path: Path) -> None:
    _write_metrics(tmp_path, "caso_01", "relogio", "medio", _report(2, 100, 10, 1, 2))
    _write_metrics(tmp_path, "caso_02", "relogio", "medio", _report(3, 100, 30, 0, 3))
    _write_metrics(tmp_path, "caso_03", "planilha", "nativo", _report(1, 50, 0, 2, 0))

    table = {(row["layout"], row["scan"]): row for row in evaluate_synthetic.summarize(tmp_path, use_ocr=True)}

    medio = table[("relogio", "medio")]
    assert (medio["cases"], medio["marks"], medio["marks_wrong"], medio["gemini_calls"]) == (2, 200, 1, 5)
    assert medio["marks_correct"] == pytest.approx(159 / 200)
    assert medio["marks_empty"] == pytest.approx(40 / 200)
    assert medio["triage_recall"] == 0.75
    assert table[("total", "")]["cases"] == 3
    assert "| relogio | medio | 2 |" in evaluate_synthetic.format_table(list(table.values()))


def test_evaluate_folder_skips_measured_cases_and_paces_calls(tmp_path: Path, monkeypatch) -> None:
    for name in ("caso_01", "caso_02", "caso_03"):
        (tmp_path / f"{name}.gabarito.json").write_text(json.dumps({"meta": {"layout": "relogio"}}), encoding="utf-8")
        (tmp_path / f"{name}.pdf").write_bytes(b"%PDF")
    _write_metrics(tmp_path, "caso_01", "relogio", "leve", _report(1, 1, 0, 0, 1))
    measured: list[str] = []
    sleeps: list[float] = []

    class _Report:
        gemini_used = True
        gemini_call_count = 2

    def fake_run(pdf, truth, local_only, use_ocr):
        measured.append(pdf.name)
        return _Report()

    monkeypatch.setattr(evaluate_synthetic, "run", fake_run)
    monkeypatch.setattr(evaluate_synthetic, "asdict", lambda report: {"gemini_call_count": 2})
    monkeypatch.setattr(evaluate_synthetic.time, "sleep", sleeps.append)

    assert evaluate_synthetic.evaluate_folder(tmp_path, use_ocr=True, rpm=4, limit=1) == 1
    assert measured == ["caso_02.pdf"]
    assert sleeps and sleeps[0] == pytest.approx(30, abs=1)
    assert (tmp_path / "caso_02.metricas.json").exists()
    assert not (tmp_path / "caso_03.metricas.json").exists()

    measured.clear()
    assert evaluate_synthetic.evaluate_folder(tmp_path, use_ocr=False, rpm=4, limit=None, only={"planilha/medio"}) == 0
    assert measured == []
