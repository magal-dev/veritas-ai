# Layout provisório da planilha (hipótese)

**Este não é o layout oficial de importação do PJe-Calc.**

O formato rígido exigido pelo sistema da Justiça do Trabalho ainda não foi incorporado a este repositório. Até existir um modelo oficial (planilha-exemplo ou documentação do PJe-Calc), o `excel_builder` gera um workbook **hipotético** apenas para:

- exercitar o fluxo upload → revisão → download → descarte;
- versionar o contrato de colunas;
- permitir substituição pontual quando o modelo real chegar.

Constante de versão no código: `LAYOUT_VERSION = "provisional-0.1"` (também gravada na aba `MetadadosSessao`).

Quando o modelo oficial for adotado, altere `backend/pipeline/excel_builder.py` e este arquivo na mesma mudança. Não trate as colunas abaixo como requisitos de negócio do PJe-Calc.

## Aba `CartaoPonto`

| Coluna | Origem no JSON | Observação |
|---|---|---|
| competencia | `TimeCardEntry.competence` | `YYYY-MM` |
| data | `TimeCardEntry.date` | `YYYY-MM-DD` |
| entrada | `clock_in` | `HH:mm` |
| saida | `clock_out` | `HH:mm` |
| intervalo_inicio | `break_start` | `HH:mm` |
| intervalo_fim | `break_end` | `HH:mm` |
| origem_pagina | `source_page` | auditoria de sessão |
| confianca | `confidence` | 0–1 |

## Aba `Holerite`

| Coluna | Origem no JSON | Observação |
|---|---|---|
| competencia | `PayslipEntry.competence` | `YYYY-MM` |
| verba | `item_name` | nome da verba extraída |
| valor | `amount` | duas casas decimais |
| origem_pagina | `source_page` | auditoria de sessão |
| confianca | `confidence` | 0–1 |

## Aba `MetadadosSessao`

Apenas contagens e timestamps — **sem** nome das partes, CPF, número do processo ou trechos de PDF.

| Chave | Valor |
|---|---|
| layout_version | `provisional-0.1` |
| schema_version | `extraction-schema-0.1` |
| generated_at | ISO-8601 |
| time_card_rows | inteiro |
| payslip_rows | inteiro |
| pdf_page_count | inteiro (metadado operacional) |
| candidate_page_count | inteiro |
| gemini_call_count | inteiro (nesta fundação: 0) |

## Regras de privacidade na geração

- O `.xlsx` nasce em arquivo temporário e é apagado imediatamente após o stream de download.
- A planilha não deve conter `source_excerpt`.
- Nenhum identificador de pessoa física/jurídica deve ser adicionado a `MetadadosSessao`.
