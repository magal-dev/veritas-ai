# Arquivos de importação do PJe-Calc gerados pelo Veritas AI

O PJe-Calc Cidadão **não importa planilha `.xlsx`**. Cada tela tem a sua importação de CSV, com leiaute fixo. O Veritas AI gera esses CSVs a partir da extração revisada, seguindo os parsers da versão **2.16.0**, descritos em [PJE_CALC_IMPORTACAO.md](PJE_CALC_IMPORTACAO.md). Essa especificação foi obtida por leitura do bytecode e dos modelos que vêm com a instalação, sem documentação oficial publicada. Por isso vale testar a importação no PJe-Calc antes de confiar em mudanças de versão.

Código: `backend/pipeline/pjecalc_exporter.py`. Constante de versão: `LAYOUT_VERSION = "pjecalc-2.16-csv-1"` (gravada no `LEIA-ME.txt`).

Quando o leiaute mudar, altere `pjecalc_exporter.py`, este arquivo e `PJE_CALC_IMPORTACAO.md` na mesma mudança.

## Download

`GET /api/v1/jobs/{id}/export` devolve `veritas-pjecalc.zip` (montado em memória, `Cache-Control: no-store`), com:

| Arquivo | Quando aparece | Importação no PJe-Calc |
|---|---|---|
| `cartao_ponto_jornada.csv` | há pelo menos um `TimeCardEntry` | Cartão de Ponto → apuração → aba "Importar Jornada" |
| `historico_salarial_NN_<verba>.csv` | um por verba de `PayslipEntry` (e um para o salário-base, se extraído) | Histórico Salarial → histórico da verba → "Importar ocorrências… a partir de Arquivo Externo" |
| `LEIA-ME.txt` | sempre | passos de importação, avisos e contagens (UTF-8 com BOM) |

Responde `409 CONFLICTS_UNRESOLVED` enquanto houver conflito aberto na sessão.

## `cartao_ponto_jornada.csv`

ISO-8859-1 (charset da JVM no `iniciarPjeCalc.bat`), separador `;`, CRLF, sem linha vazia no fim. Cabeçalho com as 13 colunas do modelo oficial:

```
Data;Entrada1;Saída1;Entrada2;Saída2;Entrada3;Saída3;Entrada4;Saída4;Entrada5;Saída5;Entrada6;Saída6
```

| Coluna | Origem | Regra |
|---|---|---|
| `Data` | `TimeCardEntry.date` | `dd/MM/yyyy`. Registro com data inválida fica de fora (contado no LEIA-ME) |
| `Entrada1`/`Saída1` | `clock_in` → `break_start` (com intervalo) ou `clock_in` → `clock_out` (sem intervalo) | `HH:mm`, sempre 5 caracteres |
| `Entrada2`/`Saída2` | `break_end` → `clock_out` (com intervalo) | idem |
| `Entrada3`…`Saída6` | registros extras do mesmo dia, na ordem da extração | até 6 turnos por dia; o excedente fica de fora (contado) |

- Turno com só entrada ou só saída é omitido, porque o PJe-Calc recusa o arquivo inteiro (MSG0164). A quantidade vai para o LEIA-ME para o perito completar no PJe-Calc. Se o dia ficar sem nenhum turno completo, ele não é exportado (uma linha vazia apagaria as marcações como folga).
- Horário vazio que ainda está em `ambiguous_fields` **não foi lido** (ex.: célula duvidosa do OCR local do cartão escaneado, ou dia do período sem linha lida) e não é tratado como ausência de marcação. Se o dia ficar sem turno completo, ele não é exportado; a quantidade de horários vai para o LEIA-ME. Quando o perito preenche o campo na revisão, ele sai de `ambiguous_fields` e o dia é exportado normalmente.
- Dia sem nenhum horário (e sem horário a conferir) sai com as colunas vazias (folga, DSR, feriado ou falta). No PJe-Calc isso apaga as marcações daquele dia.
- Jornada que vira o dia (`22:00` → `06:00`) é exportada como está; o PJe-Calc aceita.
- Pré-requisito no PJe-Calc: a apuração do cartão de ponto precisa existir com o período. Dias fora dela são ignorados sem aviso.

## `historico_salarial_NN_<verba>.csv`

UTF-8 sem BOM, separador `;`, CRLF, sem linha vazia no fim. No PJe-Calc a importação acontece **dentro** de um histórico, então cada verba vira um arquivo. O nome usa um número de ordem e a verba sem acentos (`historico_salarial_02_horas_extras_50.csv`); o nome original aparece no LEIA-ME.

```
MES_ANO;VALOR;FGTS;FGTS_REC.;CONTRIBUICAO_SOCIAL;CONTRIBUICAO_SOCIAL_REC.
```

| Coluna | Origem | Regra |
|---|---|---|
| `MES_ANO` | `PayslipEntry.competence` | `MM/yyyy`, em ordem cronológica. Competência inválida fica de fora (contada) |
| `VALOR` | `amount` | duas casas, vírgula decimal, sem separador de milhar (`1234,56`) |
| `FGTS`, `FGTS_REC.`, `CONTRIBUICAO_SOCIAL`, `CONTRIBUICAO_SOCIAL_REC.` | não extraídos | vazios (o PJe-Calc lê como `N`); o perito marca as incidências no histórico |

- Verbas são agrupadas ignorando maiúsculas, acentos e espaços extras (mesma regra do validador).
- Lançamentos repetidos da mesma verba na mesma competência são **somados** (contado no LEIA-ME).
- `base_salary` gera o arquivo `Salário-base`, a menos que já exista uma verba com esse nome.
- `;` e `"` dentro de valores viram espaço, porque o PJe-Calc remove aspas antes de separar os campos.

## Fora do escopo

- **Importação de quantidades do Cartão de Ponto:** não é gerada. Ela apaga as apurações de jornada, e o Veritas AI extrai horários, não quantidades apuradas.
- **Férias e Faltas:** o PJe-Calc importa, mas o Veritas AI não extrai esses dados.

## Regras de privacidade na geração

- O `.zip` é montado em memória a cada download e não é gravado em disco nem no banco.
- Os arquivos não contêm `source_excerpt`, página de origem ou confiança. Contêm só o que o PJe-Calc importa.
- O LEIA-ME traz apenas contagens, nomes de arquivo e nomes de verba.
