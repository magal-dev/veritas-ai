# Extração Inteligente de Dados Processuais para PJe-Calc

Trabalho de Conclusão de Curso: aplicação web para contadores e peritos trabalhistas extraírem, a partir do PDF do processo, dados de cartões de ponto e holerites e exportá-los em planilha no formato esperado pelo PJe-Calc.

Este repositório está na **fundação**: estrutura, contratos, fluxo de interface e descarte de dados. A extração com Gemini e a triagem em três camadas ainda não estão ligadas — os módulos existem como stubs tipados.

Leia [AGENTS.md](AGENTS.md) antes de implementar. Contratos: [docs/SCHEMA_EXTRACAO.md](docs/SCHEMA_EXTRACAO.md) e [docs/PJE_CALC_LAYOUT.md](docs/PJE_CALC_LAYOUT.md).

## O que o sistema fará

1. Receber upload de processos em PDF (inclusive volumes grandes).
2. Localizar cartões de ponto e holerites sem varrer o Gemini em todas as páginas.
3. Extrair horários, salário-base e verbas para JSON validado.
4. Gerar planilha para importação no PJe-Calc.
5. Descartar PDF, JSON e Excel ao fim da sessão. Não há login nem histórico.

A planilha atual usa o layout **provisório** `provisional-0.1`. Não é o modelo oficial do PJe-Calc.

## Stack

React (Vite) · FastAPI · PostgreSQL · PyMuPDF · pdfplumber · Gemini 1.5 Flash · openpyxl · SQLAlchemy async · Alembic

## Como rodar

Portas: frontend `4174`, API `8765`, Postgres `5433`.

```bash
# 1. (Opcional) banco só para metadados operacionais — duração, status, contagem de páginas
docker compose up -d

# 2. API
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp ../.env.example ../.env
alembic upgrade head          # precisa do Postgres; se falhar, a API ainda sobe
uvicorn main:app --host 0.0.0.0 --port 8765 --reload

# 3. Interface
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 4174
```

Abra http://127.0.0.1:4174. A API responde em http://127.0.0.1:8765/health.

Sem Docker/Postgres a aplicação continua utilizável: jobs ficam só em memória. O que deixa de ser gravado é a linha de `processing_runs`.

## Privacidade

Nenhum dado extraído do PDF é persistido. O PostgreSQL não recebe texto, JSON, CPF ou número de processo. Arquivos temporários são apagados após o uso. Em produção a comunicação deve ser HTTPS; o ambiente local usa HTTP.

## Licença

Uso acadêmico do TCC. Defina a licença quando o repositório público for criado.
