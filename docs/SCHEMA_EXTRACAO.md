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

## `Conflict`

```json
{
  "field": "time_cards[2024-03-04]",
  "values": [{"clock_in": "08:00", "clock_out": "17:00"}, {"clock_in": "08:00", "clock_out": "18:00"}],
  "source_pages": [12, 40],
  "note": "Horários diferentes para o dia 2024-03-04 em páginas distintas."
}
```

`field` identifica o grupo em conflito: `time_cards[<data>]`, `payslips[<competência>|<verba>]` ou `payslips[<competência>].base_salary`. Conflitos devolvidos pelo próprio Gemini mantêm o `field` original.

## Regras de fallback

- Campo não encontrado: omitir o valor e listar o nome em `missing_fields`.
- Campo ambíguo: manter o valor de maior confiança e listar em `ambiguous_fields`.
- Conflito entre documentos: registrar em `conflicts` sem escolher automaticamente; a revisão humana na sessão decide (escolher uma página/valor ou igualar campos na tabela e salvar via `PATCH /api/v1/jobs/{id}/extraction`).
- Confiança abaixo de `0.5`: o registro pode ir ao Excel, mas a UI de revisão deve destacá-lo.

## Validação (`pipeline/validator.py`)

Roda depois do Gemini e antes da revisão. São regras de formato e coerência interna, **não** regras jurídicas (limites de jornada da CLT, cálculo de verbas etc. ficam com o PJe-Calc e com o perito).

| Regra | Comportamento |
|---|---|
| Horário em leitura inequívoca (`8:00`, `8h00`, `17.30`) | Normalizado para `HH:mm` |
| Horário inválido (`25:00`, `0800`) | Valor removido; campo listado em `ambiguous_fields` do registro |
| Data `DD/MM/AAAA` ou `AAAA-M-D` | Normalizada para `YYYY-MM-DD` (formato brasileiro assumido) |
| Data ou competência inválida em campo obrigatório | Valor mantido como veio; campo listado em `ambiguous_fields` |
| Competência inválida no cartão de ponto (opcional) | Valor removido; campo listado em `ambiguous_fields` |
| Par incompleto (entrada sem saída, início sem fim de intervalo) | Campo faltante listado em `missing_fields` |
| Linha sem nenhum horário | Tratada como folga/DSR/feriado; sem pendência |
| Horários fora de ordem (intervalo fora da jornada) | Valores mantidos; horários listados em `ambiguous_fields`. Jornada que vira o dia (ex.: 22:00–06:00) é aceita |
| Mesmo dia (ou mesma competência + verba) com o **mesmo** valor em páginas diferentes | Duplicata removida; fica o registro da página de maior confiança |
| Mesmo dia (ou mesma competência + verba) com valores **diferentes** em páginas diferentes | Todos mantidos; um `Conflict` é registrado |
| Salário-base diferente na mesma competência, entre páginas | Um `Conflict` é registrado |
| Repetição na mesma página | Preservada (ex.: duas linhas da mesma verba) |

Verbas são comparadas ignorando maiúsculas, acentos e espaços extras. Os registros saem ordenados por data (cartão) e competência (holerite). As listas `missing_fields` e `ambiguous_fields` do resultado reúnem, sem repetição, as pendências da página e dos registros.

### Revisão editável (sessão)

Depois da validação inicial, o perito pode corrigir `time_cards` e `payslips` na interface e enviar `PATCH /api/v1/jobs/{id}/extraction` com essas listas. O resultado inteiro passa de novo pelo validador:

- Conflitos entre páginas (os três formatos de `field` acima) são recalculados a partir das listas. Manter só uma versão por dia/verba remove o conflito; valores iguais viram duplicata e também removem o conflito. Salário-base conflitante é unificado em todas as verbas da mesma competência.
- Conflitos devolvidos pelo Gemini não podem ser recalculados. A interface os reenvia em `conflicts` enquanto estiverem abertos; o perito os fecha com "Marcar como conferido".
- Só as linhas editadas ficam com `confidence = 1` e perdem as pendências dos campos tocados (editar um horário limpa os quatro, porque pares e ordem da jornada dependem de todos). O validador volta a sinalizar o que continuar fora do formato ou incoerente. As demais linhas mantêm a confiança do Gemini.
- `missing_fields` e `ambiguous_fields` do resultado são refeitos a partir dos registros; pendências só de página (sem registro) não sobrevivem ao salvamento.

O download do Excel (`GET /excel`) responde `409` com `CONFLICTS_UNRESOLVED` enquanto restar qualquer conflito na sessão.

## O que este schema não é

Não é o layout oficial do PJe-Calc. A planilha de saída é um mapeamento **provisório** descrito em [PJE_CALC_LAYOUT.md](PJE_CALC_LAYOUT.md).
