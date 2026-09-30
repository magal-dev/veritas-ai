# AGENTS.md — Veritas AI

Fonte de verdade para humanos e agentes. Leia este arquivo antes de alterar código, arquitetura ou texto acadêmico. Não invente stack, persistência, autenticação ou layout oficial do PJe-Calc.

## 1. Identidade

**Nome do projeto:** Veritas AI

**Contexto acadêmico (TCC):** Extração Inteligente de Dados Processuais para PJe-Calc

Aplicação web para contadores e peritos trabalhistas: recebe o PDF do processo, localiza cartões de ponto e holerites, extrai campos estruturados, valida e gera planilha para importação no PJe-Calc. Depois do download, descarta tudo.

Objetivo desta etapa do repositório: **fundação sólida** com **triagem em 3 camadas e extração Gemini** nas páginas candidatas. PDFs escaneados (sem texto extraível) e revisão editável permanecem trabalho futuro.

## 2. Mapa de pastas

```
/
├── AGENTS.md                 ← você está aqui
├── CLAUDE.md                 ← guia operacional do Claude Code (importa este arquivo)
├── README.md                 ← como rodar
├── docker-compose.yml        ← Postgres local (só metadados)
├── docs/
│   ├── SCHEMA_EXTRACAO.md    ← contrato JSON in-memory
│   └── PJE_CALC_LAYOUT.md    ← Excel provisório (HIPÓTESE, não é o layout oficial)
├── backend/
│   ├── main.py               ← app FastAPI
│   ├── core/                 ← config, database, logging
│   ├── api/                  ← rotas e controllers
│   ├── pipeline/             ← estágios do processamento
│   │   ├── extractor.py      ← Camadas 1–2 (PyMuPDF + regex + heurísticas; pdfplumber na shortlist)
│   │   ├── classifier.py     ← Camada 3 Gemini (só páginas candidatas)
│   │   ├── validator.py      ← regras + schema Pydantic
│   │   └── excel_builder.py  ← openpyxl, layout provisional-0.1
│   ├── models/               ← SQLAlchemy (ProcessingRun apenas)
│   ├── repositories/         ← acesso ao PostgreSQL
│   ├── services/             ← orquestra pipeline + sessão in-memory
│   ├── schemas/              ← Pydantic (JSON de extração e API)
│   └── alembic/              ← migrations
└── frontend/                 ← Vite + React + TypeScript + Tailwind + shadcn/ui
```

Respeite essas pastas. Não coloque regra de extração em `api/`. Não coloque SQL em `services/`. Não grave JSON extraído em `models/`.

## 3. Stack (imutável)

Não substitua estes componentes salvo limitação técnica real e justificada.

| Camada | Tecnologia |
|---|---|
| Frontend | React (Vite + TypeScript) |
| Backend | Python, FastAPI, Uvicorn |
| IA / LLM | Google Gemini API (`gemini-3.6-flash`, configurável via `GEMINI_MODEL`) via `google-genai` (SDK oficial; `google-generativeai` foi descontinuado) |
| PDF | PyMuPDF (`fitz`) + pdfplumber |
| ORM | SQLAlchemy async + asyncpg |
| Migrations | Alembic |
| Banco | PostgreSQL (Neon em nuvem; Compose na máquina local) |
| Excel | openpyxl |
| Datas | pendulum + `datetime` nativo |

TypeScript no frontend é tipagem sobre React, não troca de stack. Não introduza Next.js, Celery, Redis, outro LLM ou outro banco.

## 4. Arquitetura

Duas abordagens complementares:

1. **Layered:** React (apresentação) → FastAPI (API) → pipeline de IA (processamento) → PostgreSQL (dados operacionais).
2. **Pipeline:** cada estágio transforma e passa adiante.

Fluxo-alvo (quando a extração estiver implementada):

```
PDF bruto
  → extração local (PyMuPDF; pdfplumber só na shortlist)
  → filtro por palavras-chave
  → heurísticas de posição e densidade
  → classificação e extração Gemini (só páginas candidatas)
  → validação
  → Excel (openpyxl)
  → download no React
  → descarte imediato
```

O pipeline **roda** com triagem local e Gemini nas páginas candidatas (máx. 5 chamadas). Sem `GEMINI_API_KEY`, a triagem local funciona mas as candidatas não são classificadas. PDFs escaneados sem texto extraível retornam extração vazia.

## 5. Privacidade (Privacy by Design)

Decisão de arquitetura, não detalhe de implementação. Processos trabalhistas contêm CPF, salários e jornadas.

**Não existem:** contas de usuário, histórico de extrações, armazenamento persistente de dados processuais.

Fluxo de dados: Upload PDF → processamento em memória → download Excel → descarte.

Regras obrigatórias:

- Nenhum dado extraído do PDF vai para o banco.
- PostgreSQL só recebe metadados operacionais: timestamps, status, `pdf_page_count`, `candidate_page_count`, `gemini_call_count`, `error_code`. Sem nome de arquivo, hash de conteúdo, JSON, trechos, CPF, número de processo.
- O PDF é apagado no `finally` imediatamente após o processamento (triagem + Gemini).
- O Excel é apagado imediatamente após o stream de download.
- Sem autenticação, cadastro ou histórico neste TCC.
- Produção deve ser HTTPS. Dev local é HTTP.

Justificativa acadêmica (resumo): Cavoukian (2009), Privacy by Design; LGPD (Lei 13.709/2018), minimização e necessidade. Autenticação e auditoria completa são trabalhos futuros, condicionados à adequação jurídica.

Se uma funcionalidade exigir retenção de dado sensível, recuse e proponha alternativa stateless.

## 6. Anti-gargalo (triagem em 3 camadas)

Para PDFs grandes, **nunca** envie todas as páginas ao Gemini. Funil:

**Camada 1 — leitura local (PyMuPDF):** texto de todas as páginas (`page.get_text`), sem custo de API. Filtrar por palavras-chave, em dois pesos:

```
fortes: cartão de ponto, horas trabalhadas, holerite, salário bruto, contracheque
fracas: entrada, saída, INSS, FGTS   (aparecem também em petições)
```

E contar padrões tabulares por regex: horários (`08:00`) e valores monetários (`3.500,00`). Página só com palavra fraca e sem nenhum padrão numérico não é candidata; página sem palavra-chave mas com muitos padrões (continuação de cartão de ponto) é.

**Camada 2 — heurísticas (Python):** TOC do PDF (`fitz.get_toc()`), vizinhos ±1 com padrão numérico, densidade de texto. A detecção de tabelas do pdfplumber (`extract_tables`, cara) roda só na shortlist (top 10), para confirmar e reordenar.

**Camada 3 — Gemini:** só páginas suspeitas, renderizadas como imagem (JPEG em escala de cinza, 150 DPI). As chamadas rodam em paralelo (uma por candidata, timeout de 90 s cada), então a latência é a da chamada mais lenta, não a soma. Classificar `CARTAO_PONTO | HOLERITE | IRRELEVANTE` e extrair JSON. Meta: 2 a 5 chamadas por processo.

Medição da triagem local sem Gemini: `python scripts/benchmark_pipeline.py [paginas]`.

As camadas 1–3 estão implementadas. `classifier.py` não deve ser chamado para o PDF inteiro. Sem `GEMINI_API_KEY`, o stub marca candidatas como não classificadas.

## 7. Contratos de extração

Definição canônica: [docs/SCHEMA_EXTRACAO.md](docs/SCHEMA_EXTRACAO.md). Código: `backend/schemas/extraction.py`.

Todo registro precisa de confiança, página de origem e, quando possível, trecho fonte (só na sessão). Marcar campos ausentes, ambíguos e conflitantes. Fallback: não inventar valor; listar em `missing_fields`.

Excel: [docs/PJE_CALC_LAYOUT.md](docs/PJE_CALC_LAYOUT.md). `LAYOUT_VERSION = provisional-0.1`. **Não é o layout oficial do PJe-Calc.** Não apresente essas colunas como norma. Quando houver modelo oficial, substitua builder + doc juntos.

## 8. O que já existe vs. TODO

Já existe:

- Estrutura de pastas e este AGENTS.md
- FastAPI com jobs stateless (`POST/GET/DELETE`, preview JSON, download xlsx)
- Store in-memory com TTL
- Triagem em 3 camadas (PyMuPDF + heurísticas + Gemini em paralelo)
- Stubs tipados para testes e fallback sem API key
- `excel_builder` com abas provisórias
- `ProcessingRun` + Alembic
- UI: upload, processamento, revisão (empty state), download, erros
- Descarte de PDF/Excel/sessão

TODO (trabalho futuro):

- [x] Camada 1: PyMuPDF + palavras-chave + padrões tabulares
- [x] Camada 2: TOC, posição, densidade
- [x] Camada 3: Gemini (padrão `gemini-3.6-flash`, via `GEMINI_MODEL`) só nas candidatas
- [ ] Tratamento de PDF nativo vs. escaneado
- [ ] Revisão humana editável (hoje a tabela é somente leitura / vazia)
- [ ] Layout oficial PJe-Calc
- [ ] HTTPS / deploy
- [ ] Autenticação e histórico (fora de escopo; só como trabalho futuro acadêmico)

## 9. Como rodar

Portas de desenvolvimento: API `8765`, frontend `4174`, Postgres `5433`.

```bash
# opcional — metadados operacionais
docker compose up -d

cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env   # ou backend/.env
alembic upgrade head         # requer Postgres; a API sobe mesmo se o banco estiver fora
uvicorn main:app --host 0.0.0.0 --port 8765 --reload

cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 4174
```

A API funciona **sem** Postgres: jobs e Excel continuam in-memory; só a linha de `processing_runs` é omitida. Isso permite preview em ambientes sem Docker.

## 10. Premissas de domínio

- Um PDF mistura tipos documentais.
- Qualidade varia; escaneados vão exigir tratamento visual antes do Gemini (futuro).
- Layouts de cartão de ponto e holerite variam entre empresas.
- Extração deve ser auditável na sessão, sem persistência.
- Gemini faz OCR + interpretação semântica nas páginas candidatas (PDFs com texto extraível).
- Nada processual sobrevive ao fim da sessão.

## 11. Como responder e implementar (para agentes)

1. Identifique o problema exato.
2. Responda no contexto do Veritas AI (TCC), não com teoria genérica.
3. Solução prática e justificável, dentro da stack e das pastas.
4. Se houver alternativas, compare prós/contras e recomende.
5. Arquitetura/fluxo: tópicos, etapas ou tabelas.
6. Texto acadêmico: formal e reutilizável na monografia, só quando pedido.
7. Código: stack e pastas deste arquivo.
8. Incerteza: explicite hipóteses. Layout PJe-Calc oficial é incerto até haver modelo.
9. Não invente normas, campos oficiais ou regras de negócio sem sinalizar.
10. Extração: JSON validável, confiança, página, trecho, ausentes/ambiguidades — só em memória.

Ao propor software: modularidade, falhas por estágio, observabilidade **sem conteúdo processual**, validação antes do Excel, processamento stateless.

### Anti-padrões (não faça)

- Chamar Gemini para todas as páginas
- Persistir dados processuais
- Autenticação/histórico sem marcar como fora de escopo + LGPD
- Trocar a stack sem limitação técnica real
- Assumir extração 100% perfeita
- Ignorar PDF nativo vs. escaneado
- Arquitetura de plataforma (filas, multi-tenant, IdP) além do TCC
- Tratar `provisional-0.1` como layout oficial do PJe-Calc
- Logar `source_excerpt`, nomes, CPF ou texto de página

## 12. Portas e URLs

| Serviço | URL |
|---|---|
| Frontend (Vite) | http://127.0.0.1:4174 |
| API | http://127.0.0.1:8765 |
| Health | http://127.0.0.1:8765/health |
| OpenAPI | http://127.0.0.1:8765/docs |
| Postgres local | 127.0.0.1:5433 |

Rotas da API: prefixo `/api/v1`.

| Método | Caminho | Sensível? |
|---|---|---|
| POST | `/api/v1/jobs` | PDF só em tempfile |
| GET | `/api/v1/jobs/{id}` | metadados da sessão |
| GET | `/api/v1/jobs/{id}/preview` | JSON extraído, memória |
| GET | `/api/v1/jobs/{id}/excel` | xlsx temporário + descarte |
| DELETE | `/api/v1/jobs/{id}` | zera a sessão |
| GET | `/health` | público |
