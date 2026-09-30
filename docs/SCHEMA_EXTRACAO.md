# Schema JSON da extração (contrato in-memory)

Este documento define o JSON-alvo da extração. Os objetos existem **somente na sessão**: memória do processo FastAPI e estado React. Não são persistidos no PostgreSQL nem em disco após o download/descarte.

Campos de rastreabilidade (`source_page`, `source_excerpt`, `confidence`) são obrigatórios no contrato para tornar a extração auditável **dentro da sessão**. `source_excerpt` nunca deve ir para logs.

Versão do contrato: `extraction-schema-0.1`

## Campos transversais

| Campo | Tipo | Obrigatório | Significado |
|---|---|---|---|
| `confidence` | `number` 0–1 | sim | Confiança do campo ou do registro |
| `source_page` | `integer` ≥ 1 | sim | Página de origem no PDF |
| `source_excerpt` | `string` | não | Trecho curto que sustentou o valor (sessão apenas) |
| `missing_fields` | `string[]` | sim | Campos esperados e não encontrados |
| `ambiguous_fields` | `string[]` | sim | Campos com mais de uma leitura possível |
| `conflicts` | `object[]` | sim | Valores conflitantes entre páginas/documentos |

## `ExtractionResult`

```json
{
  "schema_version": "extraction-schema-0.1",
  "job_id": "uuid",
  "time_cards": [],
  "payslips": [],
  "unclassified_candidate_pages": [],
  "missing_fields": [],
  "ambiguous_fields": [],
  "conflicts": []
}
```

O pipeline preenche este schema via triagem local + Gemini nas páginas candidatas. Sem `GEMINI_API_KEY` ou sem candidatas, as listas podem ficar vazias. O validador aplica este schema.

## `TimeCardEntry` (cartão de ponto)

Campos obrigatórios: `date`, `source_page`, `confidence`.  
Campos opcionais: `clock_in`, `clock_out`, `break_start`, `break_end`, `competence`, `source_excerpt`.

Horários no formato `HH:mm`. Datas em `YYYY-MM-DD`. Competência em `YYYY-MM`.

## `PayslipEntry` (holerite / ficha financeira)

Campos obrigatórios: `competence`, `item_name`, `amount`, `source_page`, `confidence`.  
Campos opcionais: `base_salary`, `overtime_paid_hours`, `source_excerpt`.

Valores monetários em `decimal` (string ou number), sempre com duas casas na exportação.

## Regras de fallback

- Campo não encontrado: omitir o valor e listar o nome em `missing_fields`.
- Campo ambíguo: manter o valor de maior confiança e listar em `ambiguous_fields`.
- Conflito entre documentos: registrar em `conflicts` sem escolher automaticamente; a revisão humana na sessão decide.
- Confiança abaixo de `0.5`: o registro pode ir ao Excel, mas a UI de revisão deve destacá-lo.

## O que este schema não é

Não é o layout oficial do PJe-Calc. A planilha de saída é um mapeamento **provisório** descrito em [PJE_CALC_LAYOUT.md](PJE_CALC_LAYOUT.md).
