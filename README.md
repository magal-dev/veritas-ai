# Veritas AI

Extração inteligente de dados processuais para o PJe-Calc — projeto de Trabalho de Conclusão de Curso.

Aplicação web para contadores e peritos trabalhistas extraírem, a partir do PDF do processo, dados de cartões de ponto e holerites e exportá-los nos arquivos CSV que o PJe-Calc importa.

**Estado atual:** a triagem em 3 camadas (PyMuPDF + heurísticas locais + Gemini só nas páginas candidatas) está implementada, com revisão editável dos dados extraídos (correções e resolução de conflitos antes da exportação) e geração dos CSVs de importação do PJe-Calc Cidadão 2.16. Páginas escaneadas entram na triagem por sinais visuais locais. Cartão de ponto escaneado de layout reconhecido é lido no próprio servidor (OCR local), e ao Gemini vão só faixas anônimas com os horários duvidosos; as demais candidatas escaneadas vão ao Gemini como página.

Leia [AGENTS.md](AGENTS.md) antes de implementar (o [CLAUDE.md](CLAUDE.md) traz o guia operacional para agentes). Contratos: [docs/SCHEMA_EXTRACAO.md](docs/SCHEMA_EXTRACAO.md), [docs/PJE_CALC_LAYOUT.md](docs/PJE_CALC_LAYOUT.md) e [docs/PJE_CALC_IMPORTACAO.md](docs/PJE_CALC_IMPORTACAO.md).

Repositório: https://github.com/magal-dev/veritas-ai

## Como funciona

Fluxo de uma requisição: **upload → triagem → extração → validação → revisão → download → descarte**.

1. **Camada 1 — leitura local (PyMuPDF):** extrai o texto de todas as páginas, sem custo de API, e pontua cada uma por palavras-chave e padrões tabulares.
   - Palavras **fortes** (`cartão de ponto`, `horas trabalhadas`, `holerite`, `salário bruto`, `contracheque`) identificam o tipo documental.
   - Palavras **fracas** (`entrada`, `saída`, `INSS`, `FGTS`) aparecem também em petições e pesam menos; sozinhas, sem horários ou valores, não tornam a página candidata.
   - Regex de horários (`08:00`) e valores monetários (`3.500,00`): uma página sem palavra-chave mas com muitos padrões (continuação de cartão de ponto) também entra.
2. **Camada 2 — heurísticas:** sumário do PDF (`get_toc`), vizinhos ±1 com padrão numérico e densidade de texto. A detecção de tabelas do pdfplumber, a operação local mais cara, roda só nas 10 páginas mais bem pontuadas.
3. **Camada 3 — Gemini:** até 25 páginas candidatas, renderizadas como JPEG em escala de cinza (150 DPI) e enviadas em lotes de 5 páginas por chamada, com as chamadas (no máx. 5) em paralelo (timeout de 90 s, até 3 tentativas em 429/500/503). O modelo classifica a página (`CARTAO_PONTO`, `HOLERITE` ou `IRRELEVANTE`) e devolve JSON com confiança, página de origem e campos ausentes ou ambíguos.
   - **Cartão de ponto escaneado** (página visual candidata): antes do Gemini, o OCR local (Tesseract) tenta montar a tabela. Se reconhece o layout (período "dd/mm/aaaa à dd/mm/aaaa", colunas Ent/Sai), a página **não sai do servidor**. Cada horário é relido em recorte; três leituras iguais e perto da jornada observada são aceitas. As colunas com horário duvidoso vão ao Gemini como faixas verticais só com as células de horário, em ordem embaralhada e sem data, nome ou cabeçalho (4 faixas por chamada). A leitura do Gemini só vale perto da jornada e, nas células já aceitas localmente, funciona como voto: se discordar, o horário vai para revisão. O que continuar duvidoso fica vazio, marcado para conferência e com o recorte da célula na tela de revisão. Página não reconhecida segue como página inteira.
4. **Validação** contra o schema Pydantic e regras de formato e coerência. Horários e datas são normalizados quando a leitura é inequívoca (`8h00` → `08:00`). Valores inválidos, pares incompletos e intervalos fora da jornada são sinalizados, e duplicatas entre páginas são removidas. Valores divergentes entre páginas viram conflito para a revisão decidir: o sistema não escolhe nem inventa valor. As regras completas estão em [docs/SCHEMA_EXTRACAO.md](docs/SCHEMA_EXTRACAO.md#validação-pipelinevalidatorpy).
5. **Revisão:** a tela mostra as pendências (páginas não classificadas, campos ausentes ou a conferir, conflitos com as páginas de origem) e destaca registros de baixa confiança ou sinalizados. Horário de cartão lido no servidor que não veio do consenso local mostra o recorte da célula ao lado do campo.
6. **Exportação** sob demanda no download: um `.zip` montado em memória com os CSVs que o PJe-Calc Cidadão 2.16 importa (jornada do cartão de ponto e um histórico salarial por verba) e um `LEIA-ME.txt` com os passos. O leiaute foi lido dos parsers da própria instalação do PJe-Calc ([docs/PJE_CALC_IMPORTACAO.md](docs/PJE_CALC_IMPORTACAO.md)).

Em um PDF sintético de 300 páginas, a triagem local (camadas 1 e 2) leva cerca de 0,2 s. Para medir na sua máquina, use `python scripts/benchmark_pipeline.py 300`.

O modelo padrão `gemini-3.5-flash-lite` foi escolhido com `scripts/evaluate_models.py`, que compara modelos contra um PDF sintético de gabarito conhecido. A acurácia em documentos reais ainda não foi medida; `scripts/evaluate_extraction.py` faz essa medição contra um gabarito feito à mão (ver "Testes e scripts").

### Interface

Fluxo em 4 etapas (upload, processamento, revisão e download), todo em português, com design system próprio (Instrument Serif + Hanken Grotesk). A interface é responsiva para celular e tem alternância entre tema claro e escuro: segue a preferência do sistema na primeira visita e guarda a escolha no navegador. Os pares de cor de texto foram revisados para contraste mínimo de 4,5:1 (WCAG AA).

### Limitações atuais

- **Sem `GEMINI_API_KEY`:** a triagem local roda, mas as candidatas ficam como "não classificadas" e nenhum dado é extraído.
- **PDF escaneado** (sem camada de texto): a triagem pontua as páginas com imagem por sinais visuais (pixmap 72 DPI, faixas de linhas e traços) e as aceita só nas vagas que sobrarem depois das candidatas de texto (teto de 25). Páginas em branco ou com carimbo isolado são ignoradas.
- **OCR local do cartão de ponto:** reconhece um layout (o medido em folhas reais). Outros layouts e holerites escaneados continuam indo ao Gemini como página. Folha do layout reconhecido cujas datas não se confirmam pelas próprias linhas (folha curta, data cortada na margem) não sai do servidor: os horários são lidos do mesmo jeito e as datas ficam para o perito confirmar na revisão ("Confirmar datas da p. N"); até lá, esses dias não entram na exportação. Sem o Tesseract instalado (ou com `TIME_CARD_OCR=false`), todo cartão escaneado vai como página. Dia de hora extra fora da jornada observada (±75 min) vai para revisão em vez de ser aceito.
- Sem `GEMINI_API_KEY`, o OCR local não roda (a extração depende da camada 3).
- Candidatas além das 5 primeiras não vão ao Gemini; aparecem como pendência na revisão.
- A revisão permite editar cartões e holerites e salvar na sessão; a exportação só é liberada sem conflitos pendentes.
- Férias e faltas têm importação no PJe-Calc, mas não são extraídas. Incidências de FGTS e contribuição social do histórico salarial vão vazias, para o perito marcar.

## Estrutura do repositório

```mermaid
flowchart TB
  subgraph root [Raiz]
    AGENTS[AGENTS.md / CLAUDE.md]
    DOCS[docs/]
    COMPOSE[docker-compose.yml]
  end

  subgraph frontend [frontend/ — React]
  UI[src/components + App.tsx]
  API_CLIENT[src/lib/api.ts]
  end

  subgraph backend [backend/ — FastAPI]
    API[api/]
    SVC[services/]
    PIPE[pipeline/]
    SCH[schemas/]
    MOD[models/]
    REPO[repositories/]
    CORE[core/]
    ALE[alembic/]
  end

  subgraph data [Persistência]
    MEM[(Sessão in-memory)]
    PG[(PostgreSQL — só metadados)]
  end

  GEMINI[[Gemini API — páginas candidatas; cartão escaneado só como faixas anônimas]]

  UI --> API_CLIENT
  API_CLIENT --> API
  API --> SVC
  SVC --> PIPE
  SVC --> MEM
  PIPE --> SCH
  PIPE --> GEMINI
  SVC --> REPO
  REPO --> MOD
  MOD --> PG
  CORE --> API
  CORE --> REPO
  DOCS -.-> SCH
  DOCS -.-> PIPE
  ALE --> PG
  COMPOSE --> PG
```

### Mapa de pastas

```
veritas-ai/
├── AGENTS.md              # Fonte de verdade: stack, privacidade, pipeline, TODOs
├── CLAUDE.md              # Guia operacional para agentes (comandos, onde mexer, testes)
├── README.md              # Este arquivo — visão geral e como rodar
├── docker-compose.yml     # Postgres local (apenas metadados operacionais)
├── .env.example           # Variáveis de ambiente (copiar para .env)
│
├── docs/                  # Contratos e hipóteses documentadas
│   ├── SCHEMA_EXTRACAO.md # JSON-alvo da extração (cartão de ponto, holerite)
│   ├── PJE_CALC_LAYOUT.md # Mapeamento da extração para os CSVs do PJe-Calc
│   └── PJE_CALC_IMPORTACAO.md # Leiaute das importações do PJe-Calc 2.16
│
├── backend/               # API e processamento (Python + FastAPI)
│   ├── main.py            # Entrada da aplicação FastAPI
│   ├── api/               # Rotas HTTP (jobs, health)
│   ├── services/          # Orquestração: sessão, upload, descarte do PDF
│   ├── pipeline/          # Estágios do processamento
│   │   ├── extractor.py   # Camadas 1–2: PyMuPDF + heurísticas (pdfplumber na shortlist)
│   │   ├── classifier.py  # Camada 3: Gemini — classificação e extração em paralelo
│   │   ├── validator.py   # Formatos, coerência da jornada, duplicatas e conflitos
│   │   └── pjecalc_exporter.py # CSVs de importação do PJe-Calc (.zip)
│   ├── schemas/           # Contratos Pydantic (API + extração)
│   ├── models/            # Entidades SQLAlchemy (só metadados, sem conteúdo processual)
│   ├── repositories/      # Acesso ao PostgreSQL
│   ├── core/              # Config, database async, logging
│   ├── alembic/           # Migrations do banco
│   ├── scripts/           # Smoke test, benchmark da triagem e comparação de modelos
│   └── tests/             # Testes do extractor, classifier, validator, exportação e API
│
└── frontend/              # Interface web (React + Vite + TypeScript + Tailwind + shadcn/ui)
    ├── src/
    │   ├── App.tsx        # Fluxo das 4 etapas (upload → download)
    │   ├── components/    # Telas (*Step.tsx), ThemeToggle e primitivos shadcn/ui
    │   └── lib/           # Cliente da API e tipos TypeScript
    ├── public/            # Assets estáticos (favicon, logos)
    └── vite.config.ts     # Dev server e proxy para a API
```

| Pasta | Responsabilidade |
|---|---|
| `docs/` | Contratos de dados e leiaute de importação do PJe-Calc — fonte de verdade para JSON e CSVs |
| `backend/api/` | Endpoints REST: upload, status, preview, download, descarte |
| `backend/services/` | Regras de sessão stateless, tempfile do PDF, coordenação do pipeline |
| `backend/pipeline/` | Transformação do PDF em JSON validado e depois nos CSVs do PJe-Calc |
| `backend/schemas/` | Modelos Pydantic compartilhados entre API, pipeline e validação |
| `backend/models/` + `repositories/` | Persistência **apenas** de metadados (`processing_runs`) |
| `backend/core/` | Configuração, engine async do Postgres, logger operacional |
| `backend/alembic/` | Versionamento do schema do banco |
| `backend/scripts/` | Ferramentas de desenvolvimento; usam só dados fictícios |
| `frontend/src/components/` | UI em português: upload, processamento, revisão, download |
| `frontend/src/lib/` | Chamadas à API e tipos espelhando o backend |

Dados sensíveis do processo **não** passam por `models/`, `repositories/` nem disco após o ciclo da sessão — ficam só em memória até o download.

## Stack

React 19 (Vite + TypeScript) · Tailwind 4 + shadcn/ui · FastAPI · PostgreSQL · SQLAlchemy async · Alembic · PyMuPDF · pdfplumber · Tesseract (OCR local do cartão escaneado) · Gemini (`gemini-3.5-flash-lite` via SDK `google-genai`)

## Como rodar

Portas: frontend `4174`, API `8765`, Postgres `5433`. Requer Python ≥ 3.11 e Node.js.

```powershell
# 1. (Opcional) banco só para metadados operacionais — duração, status, contagem de páginas
docker compose up -d

# 2. API (a partir de backend/)
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
copy ..\.env.example ..\.env      # Linux/macOS: cp ../.env.example ../.env
alembic upgrade head              # precisa do Postgres; se falhar, a API ainda sobe
uvicorn main:app --host 127.0.0.1 --port 8765 --reload

# 3. Interface (a partir de frontend/, em outro terminal)
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 4174
```

Abra http://127.0.0.1:4174. A API responde em http://127.0.0.1:8765/health e a documentação OpenAPI em http://127.0.0.1:8765/docs.

### OCR local do cartão de ponto (Tesseract)

Instale o binário do Tesseract com o idioma português: no Windows, o instalador do [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki) (marque "Portuguese" em *Additional language data*); no Linux, `apt install tesseract-ocr tesseract-ocr-por`. Se o executável não estiver no `PATH`, aponte `TESSERACT_CMD` no `.env` (ex.: `C:\Program Files\Tesseract-OCR\tesseract.exe`). Sem ele a API sobe normalmente e registra `time_card_ocr.unavailable` no log; os cartões escaneados voltam a ir como página.

### Configuração do Gemini

Preencha `GEMINI_API_KEY` no `.env` (chave do [Google AI Studio](https://aistudio.google.com/apikey)). O modelo pode ser trocado em `GEMINI_MODEL`. Sem a chave, a aplicação funciona, mas só executa a triagem local.

Sem Docker/Postgres a aplicação continua utilizável: os jobs ficam só em memória, e o que deixa de ser gravado é a linha de `processing_runs`.

## API

Prefixo `/api/v1`.

| Método | Caminho | Descrição |
|---|---|---|
| POST | `/api/v1/jobs` | Envia o PDF e processa (o arquivo existe só em tempfile durante a requisição) |
| GET | `/api/v1/jobs/{id}` | Status e metadados da sessão |
| GET | `/api/v1/jobs/{id}/preview` | JSON extraído, mantido em memória |
| PATCH | `/api/v1/jobs/{id}/extraction` | Salva correções da revisão e revalida (memória) |
| GET | `/api/v1/jobs/{id}/export` | Download do `.zip` com os CSVs do PJe-Calc (409 se houver conflitos) |
| DELETE | `/api/v1/jobs/{id}` | Descarta a sessão |
| GET | `/health` | Verificação de saúde |

## Testes e scripts

```powershell
# Backend (a partir de backend/) — não precisa de Postgres nem de GEMINI_API_KEY
pytest
pytest tests/test_extractor.py -k nome     # teste específico

# Smoke test ponta a ponta (com a API rodando)
python scripts/generate_sample_pdf.py      # gera tests/fixtures/processo_exemplo.pdf (fictício)
python scripts/test_sample_pdf.py          # POST /jobs + GET /preview e imprime o resumo

# Medições
python scripts/benchmark_pipeline.py 300   # tempo da triagem local, sem Gemini
python scripts/evaluate_models.py          # compara modelos Gemini com gabarito sintético (usa a API)
python scripts/evaluate_extraction.py processo.pdf gabarito.json [--json m.json] [--local-only] [--no-ocr]
                                           # pipeline completo contra gabarito; imprime só métricas
python scripts/evaluate_cell_fallback.py gabarito.json folha*.jpg [--send] [--save-crops dir/]
                                           # cartão escaneado: OCR local + faixas anônimas (mesmo código do pipeline)
python scripts/generate_synthetic_cases.py ../avaliacao-sintetica --cases 24 --seed 1
                                           # processos fictícios com gabarito automático
python scripts/evaluate_synthetic.py ../avaliacao-sintetica [--no-ocr] [--limit N] [--rpm 4]
                                           # mede todos os casos e agrega por layout × digitalização

# Frontend (a partir de frontend/)
npm run build                              # tsc -b + vite build
npm run lint                               # oxlint
npm test                                   # vitest
```

Os testes nunca chamam o Gemini real: usam o classificador stub ou mocks do cliente `google-genai`.

**Avaliação com processos reais.** O formato do gabarito está no topo de `scripts/evaluate_extraction.py`. A saída tem só contagens e porcentagens (recall/precisão da triagem, acurácia da classificação, horários e verbas corretos, itens inventados, chamadas e tempo). PDFs e gabaritos reais contêm dados pessoais: mantenha-os fora do repositório (a pasta `avaliacao-local/` e arquivos `*.gabarito.json` são ignorados pelo git) e apague-os ao terminar. O cartão escaneado passa pelo OCR local como em produção; `--no-ocr` mede a linha de base (página inteira no Gemini). Os horários marcados no documento são separados em corretos, vazios (ficam para a revisão) e errados sem aviso.

**Avaliação com processos sintéticos.** `scripts/generate_synthetic_cases.py` monta processos fictícios (peças de enchimento, holerites e cartões de ponto) e escreve o gabarito junto, sem digitação. Varia o layout do cartão (`relogio`, o layout que o OCR local reconhece, ou `planilha`, que vai inteiro ao Gemini), a digitalização (`nativo`, `leve`, `medio`, `forte`), a jornada, os meses, os feriados, a marcação única e a folha curta de desligamento. A semente recria cada caso, então os PDFs não vão para o repositório (`avaliacao-sintetica/` é ignorada). `scripts/evaluate_synthetic.py` mede todos os casos no ritmo da cota gratuita do Gemini, retoma de onde parou e agrega por layout e digitalização. Limitações: o cartão `relogio` imita o layout das folhas reais medidas (mede robustez dentro dele, não generalização) e o ruído é simulado; as folhas reais seguem como validação de campo, reportada à parte.

**Cartão de ponto escaneado lido no servidor.** `scripts/evaluate_cell_fallback.py` roda o mesmo código do pipeline (`pipeline/time_card_ocr.py` + a chamada de faixas do classificador) contra um gabarito e separa corretos, revisão e errados sem aviso, para o OCR local sozinho e para o pipeline completo (com `--send`). Sem `--send` nada é enviado; `--save-crops` grava exatamente as faixas que sairiam, para inspeção. Aceita as imagens das folhas ou um PDF com `--pages`.

## Privacidade

- Não há login, cadastro nem histórico de extrações.
- Nenhum dado extraído do PDF é persistido. O PostgreSQL recebe só metadados operacionais (timestamps, status, contagem de páginas, de candidatas e de chamadas ao Gemini, código de erro), sem nome de arquivo, texto, JSON, CPF ou número de processo.
- O PDF é apagado ao fim do processamento; a exportação é montada em memória a cada download e nunca é gravada; a sessão em memória expira após `JOB_TTL_SECONDS`.
- Apenas as páginas candidatas (até 25 por processo) são enviadas como imagem à API do Gemini; o restante do documento não sai do servidor.
- Cartão de ponto escaneado reconhecido pelo OCR local não é enviado como página: saem só faixas com células de horário, sem data, nome, cabeçalho ou ordem dos dias. O vínculo de cada linha com o dia e os recortes mostrados na revisão ficam só na sessão em memória.
- Os logs registram só metadados (`job_id`, contagens, duração), nunca conteúdo das páginas.
- O navegador guarda apenas a preferência de tema (`localStorage`); nenhum dado do processo.
- Em produção a comunicação deve ser HTTPS; o ambiente local usa HTTP.

## Licença

Uso acadêmico (TCC). Defina a licença quando o repositório público for criado.
