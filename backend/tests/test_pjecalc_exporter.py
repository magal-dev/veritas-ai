import zipfile
from io import BytesIO
from uuid import uuid4

from pipeline.pjecalc_exporter import (
    HISTORICO_HEADER,
    JORNADA_FILENAME,
    JORNADA_HEADER,
    README_FILENAME,
    PjeCalcExporter,
)
from schemas.extraction import ExtractionResult, PayslipEntry, TimeCardEntry


def _card(day: str, **times) -> TimeCardEntry:
    return TimeCardEntry(date=day, source_page=1, confidence=0.9, **times)


def _payslip(competence: str, item: str, amount: float, **extra) -> PayslipEntry:
    return PayslipEntry(
        competence=competence,
        item_name=item,
        amount=amount,
        source_page=2,
        confidence=0.9,
        **extra,
    )


def _rows(payload: bytes, encoding: str) -> list[str]:
    return payload.decode(encoding).split("\r\n")


def test_empty_extraction_exports_only_readme():
    export = PjeCalcExporter().build(ExtractionResult(job_id=uuid4()))
    assert list(export.files) == [README_FILENAME]
    readme = export.files[README_FILENAME].decode("utf-8-sig")
    assert "Nenhum cartão de ponto ou holerite" in readme


def test_jornada_follows_pjecalc_layout():
    extraction = ExtractionResult(
        job_id=uuid4(),
        time_cards=[
            _card(
                "2021-05-03",
                clock_in="08:00",
                break_start="12:00",
                break_end="13:00",
                clock_out="17:30",
            ),
            _card("2021-05-08"),
            _card("2021-05-09", clock_in="22:00", clock_out="06:00"),
        ],
    )
    payload = PjeCalcExporter().build(extraction).files[JORNADA_FILENAME]
    rows = _rows(payload, "iso-8859-1")

    assert rows[0] == ";".join(JORNADA_HEADER)
    assert rows[0].startswith("Data;Entrada1;Saída1;Entrada2;Saída2")
    assert len(JORNADA_HEADER) == 13
    assert rows[1:] == [
        "03/05/2021;08:00;12:00;13:00;17:30;;;;;;;;",
        "08/05/2021;;;;;;;;;;;;",
        "09/05/2021;22:00;06:00;;;;;;;;;;",
    ]
    # Cabeçalho em ISO-8859-1 (charset da JVM do PJe-Calc) e sem linha vazia no fim.
    assert "Saída1".encode("iso-8859-1") in payload
    assert not payload.endswith(b"\r\n")


def test_jornada_drops_incomplete_shift_and_reports_it():
    extraction = ExtractionResult(
        job_id=uuid4(),
        time_cards=[
            _card("2021-05-03", clock_in="08:00", break_start="12:00", break_end="13:00"),
            _card("2021-05-04", clock_in="08:00"),
            _card("not-a-date", clock_in="08:00", clock_out="17:00"),
        ],
    )
    export = PjeCalcExporter().build(extraction)
    rows = _rows(export.files[JORNADA_FILENAME], "iso-8859-1")
    # O dia 04 não vira linha vazia: no PJe-Calc isso apagaria as marcações como folga.
    assert rows[1:] == ["03/05/2021;08:00;12:00;;;;;;;;;;"]
    assert export.summary.incomplete_shifts == 2
    assert export.summary.omitted_days == 1
    assert export.summary.skipped_time_cards == 1
    readme = export.files[README_FILENAME].decode("utf-8-sig")
    assert "2 turno(s) com só entrada ou só saída" in readme
    assert "1 dia(s) sem nenhum turno completo" in readme
    assert "1 registro(s) com data inválida" in readme


def test_jornada_does_not_export_unread_ocr_day_as_day_off():
    # Saída do OCR local do cartão escaneado: célula duvidosa vazia em ambiguous_fields e
    # dia do período sem linha lida. Nenhum dos dois pode virar linha de folga.
    extraction = ExtractionResult(
        job_id=uuid4(),
        time_cards=[
            _card("2025-07-21", clock_in="10:00", clock_out="17:01"),
            _card("2025-07-22", clock_out="15:02", ambiguous_fields=["clock_in"]),
            _card("2025-07-23", ambiguous_fields=["clock_in", "clock_out"]),
            _card("2025-07-26"),  # folga lida como folga: linha vazia
        ],
    )
    export = PjeCalcExporter().build(extraction)
    rows = _rows(export.files[JORNADA_FILENAME], "iso-8859-1")
    assert rows[1:] == ["21/07/2025;10:00;17:01;;;;;;;;;;", "26/07/2025;;;;;;;;;;;;"]
    assert export.summary.unread_times == 3
    assert export.summary.omitted_days == 2
    readme = export.files[README_FILENAME].decode("utf-8-sig")
    assert "3 horário(s) marcados para conferir" in readme


def test_jornada_skips_unconfirmed_dates_until_review_confirms():
    pending = _card("2025-08-01", clock_in="08:00", clock_out="15:00", ambiguous_fields=["date"])
    extraction = ExtractionResult(job_id=uuid4(), time_cards=[pending])
    export = PjeCalcExporter().build(extraction)
    assert _rows(export.files[JORNADA_FILENAME], "iso-8859-1")[1:] == []
    assert export.summary.unconfirmed_dates == 1
    assert "1 registro(s) com data não confirmada" in export.files[README_FILENAME].decode("utf-8-sig")

    confirmed = pending.model_copy(update={"ambiguous_fields": []})
    export = PjeCalcExporter().build(ExtractionResult(job_id=uuid4(), time_cards=[confirmed]))
    assert _rows(export.files[JORNADA_FILENAME], "iso-8859-1")[1:] == ["01/08/2025;08:00;15:00;;;;;;;;;;"]


def test_jornada_exports_ocr_day_once_review_fills_it():
    # A revisão tira o campo de ambiguous_fields quando o perito o preenche.
    extraction = ExtractionResult(
        job_id=uuid4(),
        time_cards=[_card("2025-07-22", clock_in="08:01", clock_out="15:02", ambiguous_fields=[])],
    )
    export = PjeCalcExporter().build(extraction)
    assert _rows(export.files[JORNADA_FILENAME], "iso-8859-1")[1:] == ["22/07/2025;08:01;15:02;;;;;;;;;;"]
    assert export.summary.unread_times == 0


def test_jornada_merges_same_day_records_up_to_six_shifts():
    cards = [
        _card("2021-05-03", clock_in=f"{hour:02d}:00", clock_out=f"{hour:02d}:30")
        for hour in range(1, 9)
    ]
    export = PjeCalcExporter().build(ExtractionResult(job_id=uuid4(), time_cards=cards))
    row = _rows(export.files[JORNADA_FILENAME], "iso-8859-1")[1]
    assert row.split(";")[1:] == [
        value for hour in range(1, 7) for value in (f"{hour:02d}:00", f"{hour:02d}:30")
    ]
    assert export.summary.dropped_shifts == 2


def test_historico_has_one_file_per_item_in_pjecalc_format():
    extraction = ExtractionResult(
        job_id=uuid4(),
        payslips=[
            _payslip("2022-02", "Horas extras 50%", 310.4),
            _payslip("2022-01", "Horas extras 50%", 1234.5),
            _payslip("2022-01", "horas  EXTRAS 50%", 10.0),
            _payslip("2022-01", "Adicional; noturno", 99.99),
        ],
    )
    export = PjeCalcExporter().build(extraction)
    assert sorted(export.files) == [
        README_FILENAME,
        "historico_salarial_01_adicional_noturno.csv",
        "historico_salarial_02_horas_extras_50.csv",
    ]

    extras = _rows(export.files["historico_salarial_02_horas_extras_50.csv"], "utf-8")
    assert extras == [
        ";".join(HISTORICO_HEADER),
        "01/2022;1244,50;;;;",
        "02/2022;310,40;;;;",
    ]
    noturno = _rows(export.files["historico_salarial_01_adicional_noturno.csv"], "utf-8")
    assert noturno[1] == "01/2022;99,99;;;;"
    assert export.summary.summed_competences == 1

    readme = export.files[README_FILENAME].decode("utf-8-sig")
    assert "historico_salarial_02_horas_extras_50.csv: Horas extras 50% (2 competência(s))" in readme


def test_historico_orders_competences_across_years():
    extraction = ExtractionResult(
        job_id=uuid4(),
        payslips=[
            _payslip("2023-01", "Salário", 2000.0),
            _payslip("2022-12", "Salário", 1900.0),
        ],
    )
    files = PjeCalcExporter().build(extraction).files
    rows = _rows(files["historico_salarial_01_salario.csv"], "utf-8")
    assert [row.split(";")[0] for row in rows[1:]] == ["12/2022", "01/2023"]


def test_base_salary_becomes_its_own_history():
    extraction = ExtractionResult(
        job_id=uuid4(),
        payslips=[
            _payslip("2022-01", "Horas extras", 300.0, base_salary=1850.0),
            _payslip("2022-01", "DSR", 60.0, base_salary=1850.0),
            _payslip("bad", "DSR", 60.0),
        ],
    )
    export = PjeCalcExporter().build(extraction)
    base = _rows(export.files["historico_salarial_01_salario_base.csv"], "utf-8")
    assert base[1:] == ["01/2022;1850,00;;;;"]
    assert export.summary.skipped_payslips == 1


def test_base_salary_is_not_duplicated_when_extracted_as_item():
    extraction = ExtractionResult(
        job_id=uuid4(),
        payslips=[
            _payslip("2022-01", "Salário base", 1850.0, base_salary=1850.0),
            _payslip("2022-01", "Horas extras", 300.0, base_salary=1850.0),
        ],
    )
    files = PjeCalcExporter().build(extraction).files
    assert sorted(files) == [
        README_FILENAME,
        "historico_salarial_01_horas_extras.csv",
        "historico_salarial_02_salario_base.csv",
    ]


def test_zip_contains_all_files():
    extraction = ExtractionResult(
        job_id=uuid4(),
        time_cards=[_card("2021-05-03", clock_in="08:00", clock_out="17:00")],
        payslips=[_payslip("2022-01", "Salário", 2000.0)],
    )
    archive = zipfile.ZipFile(BytesIO(PjeCalcExporter().build_zip(extraction)))
    assert sorted(archive.namelist()) == [
        README_FILENAME,
        JORNADA_FILENAME,
        "historico_salarial_01_salario.csv",
    ]
    readme = archive.read(README_FILENAME).decode("utf-8-sig")
    assert "Importar Jornada" in readme
    assert "source_excerpt" not in readme
