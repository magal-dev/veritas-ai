# CLAUDE.md — Veritas AI

Guia operacional para o Claude Code. A fonte de verdade de produto, stack, privacidade e arquitetura é o `AGENTS.md`, importado abaixo. Em caso de conflito, vale o `AGENTS.md`.

@AGENTS.md

---

## Resumo rápido

TCC: app web stateless que recebe PDF de processo trabalhista, faz triagem em 3 camadas (PyMuPDF + regex → heurísticas, pdfplumber só na shortlist → Gemini em paralelo só nas candidatas), valida o JSON extraído e gera um `.xlsx` provisório para o PJe-Calc. Nada processual é persistido.

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

# Frontend (a partir de frontend/)
npm install
npm run dev -- --host 127.0.0.1 --port 4174
npm run build                            # tsc -b + vite build (serve como typecheck)
npm run lint                             # oxlint
```

## Fluxo de uma requisição (`POST /api/v1/jobs`)

`api/jobs.py` → `services/job_service.py::JobService.create_from_upload`:

1. `_assert_pdf` e `_write_temp_pdf` (tempfile, limite `MAX_UPLOAD_MB`).
2. `pipeline/extractor.py::LocalDocumentExtractor.extract` → `ExtractionSignals` (camadas 1–2).
3. `pipeline/classifier.py::build_classifier(...).classify` em `asyncio.to_thread` (camada 3; `StubDocumentClassifier` sem API key).
4. Monta `ExtractionResult` → `pipeline/validator.py`.
5. `finally`: fecha o upload e apaga o PDF.
6. Sessão vai para `services/session_store.py` (in-memory, TTL `JOB_TTL_SECONDS`); `ProcessingRun` recebe só metadados (falha de banco é tolerada).

O Excel (`pipeline/excel_builder.py`) é gerado sob demanda em `GET /jobs/{id}/excel` e descartado após o stream.

Códigos de erro são strings estáveis (`INVALID_FILE_TYPE`, `FILE_TOO_LARGE`, `EMPTY_FILE`, `GEMINI_ERROR`, `PIPELINE_ERROR`, `EXTRACTION_MISSING`). O frontend depende deles, então não renomeie sem atualizar `frontend/src/lib/api.ts` e os componentes.

## Onde mexer

| Mudança | Arquivos |
|---|---|
| Novo campo extraído | `docs/SCHEMA_EXTRACAO.md`, `schemas/extraction.py`, prompt em `pipeline/classifier.py`, `pipeline/validator.py`, `pipeline/excel_builder.py` + `docs/PJE_CALC_LAYOUT.md`, `frontend/src/lib/types.ts`, testes |
| Palavras-chave, TOC, densidade | `pipeline/extractor.py`, `tests/test_extractor.py` |
| Prompt, parsing ou limite de chamadas do Gemini | `pipeline/classifier.py`, `tests/test_classifier.py` |
| Colunas/abas do Excel | `pipeline/excel_builder.py` + `docs/PJE_CALC_LAYOUT.md` juntos, `tests/test_excel_builder.py` |
| Rota ou resposta da API | `api/jobs.py`, `schemas/jobs.py`, `services/job_service.py`, `frontend/src/lib/api.ts`, `tests/test_jobs_api.py` |
| Nova variável de ambiente | `core/config.py` + `.env.example` |
| Metadado operacional no banco | `models/processing_run.py`, nova migration em `alembic/versions/`, `repositories/processing_run_repository.py` (nunca conteúdo processual) |
| Telas | `frontend/src/components/*Step.tsx`, `frontend/src/App.tsx`; primitivos shadcn em `frontend/src/components/ui/` |

## Testes

- Nunca chame o Gemini real em testes. Use `StubDocumentClassifier` ou faça patch de `pipeline.classifier.genai.GenerativeModel` (padrão em `tests/test_classifier.py`).
- Gere PDFs de teste em memória com `fitz` (PyMuPDF) dentro do `tmp_path`. Não commite PDFs com dados reais.
- `asyncio_mode = "auto"`: testes `async def` não precisam de decorator.
- A API deve funcionar sem Postgres; os testes não podem depender de banco.

## Convenções

- Texto de UI, docs e mensagens ao usuário em português (pt-BR). Identificadores de código em inglês.
- Python: type hints, `from __future__ import annotations`, dataclasses/Pydantic para contratos. Siga o estilo do módulo vizinho.
- Logs: formato `evento.acao chave=valor` só com metadados (`job_id`, contagens, duração). Nunca texto de página, `source_excerpt`, nomes, CPF ou nome de arquivo.
- Não adicione dependências fora da stack do `AGENTS.md` sem justificar.

## Antes de concluir uma tarefa

1. `pytest` verde em `backend/`.
2. Se tocou no frontend: `npm run build` e `npm run lint` em `frontend/`.
3. Se mudou algum contrato (JSON, Excel, API), atualize o doc correspondente em `docs/` e os tipos do frontend.
4. Se concluiu um item do TODO, marque-o na seção 8 do `AGENTS.md`.
5. Revise se algum dado processual passou a ser logado, persistido ou retido além da sessão.
