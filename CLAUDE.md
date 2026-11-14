# CLAUDE.md — Veritas AI

Guia operacional para o Claude Code. A fonte de verdade de produto, stack, privacidade e arquitetura é o `AGENTS.md`, importado abaixo. Em caso de conflito, vale o `AGENTS.md`.

@AGENTS.md

---

## Resumo rápido

TCC: app web stateless que recebe o PDF do processo trabalhista, ou só as folhas do cartão de ponto e do holerite (PDFs e/ou fotos), faz triagem em 3 camadas (PyMuPDF + regex → heurísticas, pdfplumber só na shortlist → Gemini em paralelo só nas candidatas), valida o JSON extraído e gera os CSVs de importação do PJe-Calc 2.16 (em um `.zip`). Páginas escaneadas são pontuadas localmente por sinais visuais e ocupam só as vagas restantes. Cartão de ponto escaneado de layout reconhecido é lido por OCR local (Tesseract) e só faixas anônimas de horários duvidosos vão ao Gemini; as demais escaneadas vão como página (o Gemini faz o OCR). Nada processual é persistido.

- Backend: `backend/` (FastAPI, Python ≥ 3.11). Imports absolutos a partir de `backend/` (`from core.config import settings`), pois `pythonpath = ["."]`.
- Frontend: `frontend/` (Vite + React 19 + TypeScript + Tailwind 4 + shadcn/ui).
- Contratos: `docs/SCHEMA_EXTRACAO.md` ↔ `backend/schemas/extraction.py` ↔ `frontend/src/lib/types.ts`.

## Comandos

Ambiente principal do autor: Windows + PowerShell. Use `python` (não `python3`) e ative a venv com `.\.venv\Scripts\Activate.ps1`.

```powershell
# Backend (a partir de backend/)
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest                                   # suíte completa (não precisa de Postgres nem de GEMINI_API_KEY)
pytest tests/test_extractor.py -k nome   # teste específico
uvicorn main:app --host 127.0.0.1 --port 8765 --reload
alembic upgrade head                     # requer Postgres (docker compose up -d na raiz)
alembic revision -m "descricao"          # nova migration (só metadados operacionais)

# Smoke test ponta a ponta (API rodando)
python scripts/generate_sample_pdf.py    # gera tests/fixtures/processo_exemplo.pdf
python scripts/test_sample_pdf.py        # POST /jobs + GET /preview e imprime o resumo
python scripts/benchmark_pipeline.py 300 # tempo da triagem local (sem Gemini) em PDF sintético
python scripts/evaluate_extraction.py processo.pdf gabarito.json  # métricas contra gabarito (PDF real fica fora do repo)
python scripts/evaluate_cell_fallback.py gabarito.json folha*.jpg   # cartão escaneado via OCR local; --send mede com o Gemini
python scripts/generate_synthetic_cases.py ../avaliacao-sintetica --cases 24   # processos fictícios + gabarito
python scripts/evaluate_synthetic.py ../avaliacao-sintetica         # mede em lote (retoma; ritmo da cota gratuita)

# Frontend (a partir de frontend/)
npm install
npm run dev -- --host 127.0.0.1 --port 4174
npm run build                            # tsc -b + vite build (serve como typecheck)
npm run lint                             # oxlint
npm test                                 # vitest (lógica de revisão e cliente da API)
```

## Fluxo de uma requisição (`POST /api/v1/jobs`)

`api/jobs.py` → `services/job_service.py::JobService.create_from_upload`:

1. `_assert_files` e `_write_temp_file` (um tempfile por arquivo; campo `file` repetido, até `MAX_UPLOAD_FILES`; `MAX_UPLOAD_MB` vale para o envio inteiro). Mais de um arquivo, ou foto, é juntado num PDF temporário por `services/upload_bundle.py::assemble_pdf` (foto = uma página, EXIF aplicado).
2. `pipeline/extractor.py::LocalDocumentExtractor.extract(..., keep_all_up_to=SELECTED_PAGES_LIMIT)` → `ExtractionSignals` (camadas 1–2). Envio de fotos ou de vários arquivos com até 25 páginas no total (folhas escolhidas pelo perito): todas viram candidatas sem triagem (`all_pages`). PDF único de até 15 páginas (`SHORT_PDF_PAGES`, `keep_visual_up_to`): texto passa pela triagem e toda página sem texto (scan ou foto) vira candidata (`short_document`). PDF único maior ou envio acima de 25 páginas: triagem normal, com páginas de cálculo (marcadores em `CALCULATION_MARKERS`) fora.
3. `pipeline/classifier.py::build_classifier(...).classify` em `asyncio.to_thread` (camada 3; `StubDocumentClassifier` sem API key). Páginas visuais candidatas passam antes por `pipeline/time_card_ocr.py::TimeCardReader` (se `TIME_CARD_OCR` e Tesseract disponíveis): reconhecidas viram registros + faixas ao Gemini; as outras vão como página.
4. Monta `ExtractionResult` → `pipeline/validator.py`.
5. `finally`: fecha os uploads e apaga todos os tempfiles (arquivos enviados e PDF montado).
6. Sessão vai para `services/session_store.py` (in-memory, TTL `JOB_TTL_SECONDS`), com os recortes de célula da revisão em `review_crops`; `ProcessingRun` recebe só metadados (falha de banco é tolerada).

Os CSVs do PJe-Calc (`pipeline/pjecalc_exporter.py`) são gerados em memória sob demanda em `GET /jobs/{id}/export`, como `.zip`.

Códigos de erro são strings estáveis (`INVALID_FILE_TYPE`, `FILE_TOO_LARGE`, `EMPTY_FILE`, `TOO_MANY_FILES`, `PIPELINE_ERROR`, `EXTRACTION_MISSING`, `SESSION_LIMIT`). `PIPELINE_ERROR` sai como HTTP 500 com esse `error_code`. Se o Gemini não classifica nenhuma página, o job conclui e as candidatas ficam em `unclassified_candidate_pages`. O frontend depende dos códigos, então não renomeie sem atualizar `frontend/src/lib/api.ts` e os componentes.

## Onde mexer

| Mudança | Arquivos |
|---|---|
| Novo campo extraído | `docs/SCHEMA_EXTRACAO.md`, `schemas/extraction.py`, prompt em `pipeline/classifier.py`, `pipeline/validator.py`, `pipeline/pjecalc_exporter.py` + `docs/PJE_CALC_LAYOUT.md` (se o PJe-Calc importar o campo), `frontend/src/lib/types.ts`, testes |
| Palavras-chave, marcadores de cálculo, TOC, densidade, limite do documento curto | `pipeline/extractor.py`, `tests/test_extractor.py` |
| Tipos aceitos no envio, fotos | `services/upload_bundle.py`, `frontend/src/lib/upload.ts`, `tests/test_upload_bundle.py` |
| Prompt, parsing ou limite de chamadas do Gemini | `pipeline/classifier.py`, `tests/test_classifier.py` |
| OCR local do cartão escaneado (layout, trava, faixas) | `pipeline/time_card_ocr.py`, `tests/test_time_card_ocr.py`; medir com `scripts/evaluate_cell_fallback.py` |
| Regras de validação, duplicatas e conflitos | `pipeline/validator.py`, `tests/test_validator.py`, seção "Validação" de `docs/SCHEMA_EXTRACAO.md` |
| CSVs de importação do PJe-Calc | `pipeline/pjecalc_exporter.py` + `docs/PJE_CALC_LAYOUT.md` juntos (leiaute em `docs/PJE_CALC_IMPORTACAO.md`), `tests/test_pjecalc_exporter.py` |
| Rota ou resposta da API | `api/jobs.py`, `schemas/jobs.py`, `services/job_service.py`, `frontend/src/lib/api.ts`, `tests/test_jobs_api.py` |
| Nova variável de ambiente | `core/config.py` + `.env.example` |
| Metadado operacional no banco | `models/processing_run.py`, nova migration em `alembic/versions/`, `repositories/processing_run_repository.py` (nunca conteúdo processual) |
| Telas | `frontend/src/components/*Step.tsx`, `frontend/src/components/HomeScreen.tsx` (apresentação), `frontend/src/App.tsx`; primitivos shadcn em `frontend/src/components/ui/` |

## Testes

- Nunca chame o Tesseract real em testes: `TimeCardReader` recebe o executor de OCR (`OcrRunner`) e os testes passam um falso com TSV pronto (padrão em `tests/test_time_card_ocr.py`).
- Nunca chame o Gemini real em testes. Use `StubDocumentClassifier` ou faça patch de `pipeline.classifier.genai.Client` (o mock responde em `.return_value.models.generate_content`) (padrão em `tests/test_classifier.py`).
- Gere PDFs de teste em memória com PyMuPDF (`import pymupdf as fitz`; o módulo `fitz` está depreciado) dentro do `tmp_path`. Não commite PDFs com dados reais.
- `asyncio_mode = "auto"`: testes `async def` não precisam de decorator.
- A API deve funcionar sem Postgres; os testes não podem depender de banco.

## Convenções

- Texto de UI, docs e mensagens ao usuário em português (pt-BR). Identificadores de código em inglês.
- Python: type hints, `from __future__ import annotations`, dataclasses/Pydantic para contratos. Siga o estilo do módulo vizinho.
- Logs: formato `evento.acao chave=valor` só com metadados (`job_id`, contagens, duração). Nunca texto de página, `source_excerpt`, nomes, CPF ou nome de arquivo.
- Não adicione dependências fora da stack do `AGENTS.md` sem justificar.

## CI

`.github/workflows/ci.yml` roda em todo PR e push na `main`: bloqueio de PDF/.env versionados, `pytest` com cobertura mínima de 85% (`fail_under` no `pyproject.toml`; Python 3.11 e 3.13, resumo no job), ida e volta das migrations em Postgres de serviço, e lint + testes (Vitest) + build do frontend. Depreciação conhecida do `TestClient` com `httpx` vira erro no pytest (`filterwarnings`). O job de imagem constrói o `Dockerfile` da raiz; o deploy de teste é pelo `render.yaml` (Render), sem deploy automático pelo CI. Dependabot semanal para pip e npm.

## Antes de concluir uma tarefa

1. `pytest` verde em `backend/`.
2. Se tocou no frontend: `npm run build`, `npm run lint` e `npm test` em `frontend/`.
3. Se mudou algum contrato (JSON, CSVs do PJe-Calc, API), atualize o doc correspondente em `docs/` e os tipos do frontend.
4. Se concluiu um item do TODO, marque-o na seção 8 do `AGENTS.md`.
5. Revise se algum dado processual passou a ser logado, persistido ou retido além da sessão.
