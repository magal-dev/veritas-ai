"""Gera os arquivos de importação do PJe-Calc Cidadão. Ver docs/PJE_CALC_LAYOUT.md.

O PJe-Calc não importa planilha .xlsx: cada tela tem a sua importação de CSV. Os leiautes
seguem os parsers da versão 2.16.0 (docs/PJE_CALC_IMPORTACAO.md). A saída é um .zip em
memória com um CSV por importação e um LEIA-ME com os passos.
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO

from pipeline.validator import (
    _normalize_label,
    normalize_competence,
    normalize_date,
    normalize_time,
)
from schemas.extraction import ExtractionResult, PayslipEntry, TimeCardEntry

LAYOUT_VERSION = "pjecalc-2.16-csv-1"

JORNADA_FILENAME = "cartao_ponto_jornada.csv"
README_FILENAME = "LEIA-ME.txt"
MAX_SHIFTS = 6

JORNADA_HEADER = ["Data"] + [
    f"{label}{index}" for index in range(1, MAX_SHIFTS + 1) for label in ("Entrada", "Saída")
]
HISTORICO_HEADER = [
    "MES_ANO",
    "VALOR",
    "FGTS",
    "FGTS_REC.",
    "CONTRIBUICAO_SOCIAL",
    "CONTRIBUICAO_SOCIAL_REC.",
]
BASE_SALARY_LABEL = "Salário-base"

# Os parsers do PJe-Calc leem linhas com readLine; uma linha vazia no fim vira erro
# (MSG0191) nas importações de histórico, então não há quebra depois da última linha.
_LINE_BREAK = "\r\n"
# Aspas são removidas pelo PJe-Calc antes do split e `;` separa campos: nenhum dos dois
# pode sobreviver dentro de um valor.
_UNSAFE_CHARS = re.compile(r'[;"\r\n]')


@dataclass
class ExportSummary:
    jornada_days: int = 0
    skipped_time_cards: int = 0
    incomplete_shifts: int = 0
    omitted_days: int = 0
    dropped_shifts: int = 0
    historico_files: list[tuple[str, str, int]] = field(default_factory=list)
    skipped_payslips: int = 0
    summed_competences: int = 0


@dataclass
class PjeCalcExport:
    files: dict[str, bytes]
    summary: ExportSummary


def _csv(rows: Iterable[list[str]]) -> str:
    return _LINE_BREAK.join(";".join(_UNSAFE_CHARS.sub(" ", cell) for cell in row) for row in rows)


def _competence_br(value: str | None) -> str | None:
    normalized = normalize_competence(value or "")
    if normalized is None:
        return None
    year, month = normalized.split("-")
    return f"{month}/{year}"


def _time(value: str | None) -> str | None:
    return normalize_time(value) if value else None


def _amount_br(value: float) -> str:
    # Sem separador de milhar: o PJe-Calc lê `1234,56` e `1.234,56`, mas um ponto
    # decimal (`1234.56`) seria lido como milhar.
    return f"{value:.2f}".replace(".", ",")


def _shifts(entry: TimeCardEntry) -> tuple[list[tuple[str, str]], int]:
    """Turnos completos do registro e quantos turnos ficaram com só uma das pontas.

    O intervalo divide a jornada em dois turnos (entrada→início do intervalo,
    fim do intervalo→saída). O PJe-Calc recusa o arquivo inteiro (MSG0164) se um turno
    tiver só entrada ou só saída, então turnos incompletos ficam de fora.
    """
    clock_in, clock_out = _time(entry.clock_in), _time(entry.clock_out)
    break_start, break_end = _time(entry.break_start), _time(entry.break_end)
    if entry.break_start or entry.break_end:
        pairs = [(clock_in, break_start), (break_end, clock_out)]
    else:
        pairs = [(clock_in, clock_out)]

    complete: list[tuple[str, str]] = []
    incomplete = 0
    for start, end in pairs:
        if start and end:
            complete.append((start, end))
        elif start or end:
            incomplete += 1
    return complete, incomplete


def build_jornada_csv(time_cards: list[TimeCardEntry], summary: ExportSummary) -> bytes:
    days: dict[str, list[tuple[str, str]]] = {}
    days_with_incomplete: set[str] = set()
    for entry in time_cards:
        iso_day = normalize_date(entry.date)
        if iso_day is None:
            summary.skipped_time_cards += 1
            continue
        complete, incomplete = _shifts(entry)
        summary.incomplete_shifts += incomplete
        if incomplete:
            days_with_incomplete.add(iso_day)
        # Mais de um registro no mesmo dia (repetição na mesma página) vira turnos extras,
        # na ordem em que aparecem: ordenar por horário quebraria jornada que vira o dia.
        days.setdefault(iso_day, []).extend(complete)

    rows = [JORNADA_HEADER]
    for iso_day in sorted(days):
        shifts = days[iso_day]
        if not shifts and iso_day in days_with_incomplete:
            # Linha vazia apagaria as marcações do dia no PJe-Calc como se fosse folga.
            summary.omitted_days += 1
            continue
        summary.dropped_shifts += max(0, len(shifts) - MAX_SHIFTS)
        cells = [time for shift in shifts[:MAX_SHIFTS] for time in shift]
        cells += [""] * (2 * MAX_SHIFTS - len(cells))
        rows.append([date.fromisoformat(iso_day).strftime("%d/%m/%Y"), *cells])
    summary.jornada_days = len(rows) - 1

    # A importação de jornada usa o charset da JVM, ISO-8859-1 no iniciarPjeCalc.bat.
    return _csv(rows).encode("iso-8859-1", errors="replace")


def _slug(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")[:40] or "verba"


def _historico_csv(values: dict[str, float]) -> bytes:
    rows = [HISTORICO_HEADER]
    for competence in sorted(values, key=lambda item: (item[3:], item[:2])):
        # Incidências não são extraídas do holerite; vazio vira "N" no PJe-Calc e o perito
        # marca FGTS/contribuição social no próprio histórico.
        rows.append([competence, _amount_br(values[competence]), "", "", "", ""])
    return _csv(rows).encode("utf-8")


def build_historico_csvs(
    payslips: list[PayslipEntry], summary: ExportSummary
) -> dict[str, bytes]:
    """Um CSV por verba: no PJe-Calc cada arquivo é importado dentro de um histórico."""
    groups: dict[str, tuple[str, dict[str, float]]] = {}
    base_salaries: dict[str, float] = {}
    for entry in payslips:
        competence = _competence_br(entry.competence)
        if competence is None:
            summary.skipped_payslips += 1
            continue
        if entry.base_salary is not None:
            base_salaries.setdefault(competence, entry.base_salary)
        label, values = groups.setdefault(
            _normalize_label(entry.item_name), (entry.item_name.strip(), {})
        )
        if competence in values:
            summary.summed_competences += 1
        values[competence] = values.get(competence, 0.0) + entry.amount

    ordered = sorted(groups.values(), key=lambda item: _normalize_label(item[0]))
    if base_salaries and _normalize_label(BASE_SALARY_LABEL) not in groups:
        ordered.insert(0, (BASE_SALARY_LABEL, base_salaries))

    files: dict[str, bytes] = {}
    for index, (label, values) in enumerate(ordered, start=1):
        filename = f"historico_salarial_{index:02d}_{_slug(label)}.csv"
        files[filename] = _historico_csv(values)
        summary.historico_files.append((filename, label, len(values)))
    return files


def _readme(summary: ExportSummary) -> str:
    lines = [
        "Veritas AI: arquivos de importação para o PJe-Calc Cidadão",
        f"Leiaute: {LAYOUT_VERSION} (conferido com os parsers do PJe-Calc 2.16.0)",
        "",
        "Revise os dados no PJe-Calc depois de importar. A extração automática pode errar.",
        "",
    ]
    has_jornada = summary.jornada_days or summary.omitted_days or summary.skipped_time_cards
    if has_jornada:
        lines += [
            f"1. {JORNADA_FILENAME} ({summary.jornada_days} dia(s))",
            "   Tela: Cartão de Ponto > apuração > aba \"Importar Jornada\".",
            "   Antes de importar, cadastre a apuração do cartão de ponto com o período",
            "   do contrato: o PJe-Calc só atualiza dias que já existem e ignora os demais.",
            "   Dias sem marcação vêm com os horários vazios (folga, DSR, feriado ou falta).",
            "   Não use a importação de QUANTIDADES depois desta: ela apaga as apurações.",
        ]
        if summary.incomplete_shifts:
            lines.append(
                f"   Atenção: {summary.incomplete_shifts} turno(s) com só entrada ou só saída"
                " ficaram de fora. Complete-os no PJe-Calc."
            )
        if summary.omitted_days:
            lines.append(
                f"   Atenção: {summary.omitted_days} dia(s) sem nenhum turno completo não"
                " foram exportados, para não apagar as marcações deles no PJe-Calc."
            )
        if summary.dropped_shifts:
            lines.append(
                f"   Atenção: {summary.dropped_shifts} turno(s) passaram do limite de"
                f" {MAX_SHIFTS} por dia e ficaram de fora."
            )
        if summary.skipped_time_cards:
            lines.append(
                f"   Atenção: {summary.skipped_time_cards} registro(s) com data inválida"
                " ficaram de fora."
            )
        lines.append("")

    if summary.historico_files:
        lines += [
            "2. Histórico Salarial: um arquivo por verba",
            "   Tela: Histórico Salarial > abra ou crie o histórico da verba > \"Importar",
            "   ocorrências a partir de Arquivo Externo\". A importação substitui as",
            "   ocorrências já cadastradas naquele histórico.",
            "   As colunas de incidência (FGTS e contribuição social) vão vazias, o que o",
            "   PJe-Calc trata como \"N\". Marque as incidências no histórico.",
            "   Meses ausentes entre a primeira e a última competência são preenchidos",
            "   pelo PJe-Calc; confira os valores deles.",
        ]
        for filename, label, count in summary.historico_files:
            lines.append(f"   - {filename}: {label} ({count} competência(s))")
        if summary.summed_competences:
            lines.append(
                f"   Atenção: {summary.summed_competences} lançamento(s) repetidos da mesma"
                " verba na mesma competência foram somados."
            )
        if summary.skipped_payslips:
            lines.append(
                f"   Atenção: {summary.skipped_payslips} lançamento(s) com competência"
                " inválida ficaram de fora."
            )
        lines.append("")

    if not has_jornada and not summary.historico_files and not summary.skipped_payslips:
        lines += ["Nenhum cartão de ponto ou holerite foi extraído nesta sessão.", ""]

    lines.append(
        "Férias e faltas também têm importação no PJe-Calc, mas não são extraídas pelo"
        " Veritas AI."
    )
    return _LINE_BREAK.join(lines) + _LINE_BREAK


class PjeCalcExporter:
    def build(self, extraction: ExtractionResult) -> PjeCalcExport:
        summary = ExportSummary()
        files: dict[str, bytes] = {}
        if extraction.time_cards:
            files[JORNADA_FILENAME] = build_jornada_csv(extraction.time_cards, summary)
        files.update(build_historico_csvs(extraction.payslips, summary))
        files[README_FILENAME] = _readme(summary).encode("utf-8-sig")
        return PjeCalcExport(files=files, summary=summary)

    def build_zip(self, extraction: ExtractionResult) -> bytes:
        export = self.build(extraction)
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in export.files.items():
                archive.writestr(name, payload)
        return buffer.getvalue()
