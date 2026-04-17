# Backend MVP (FastAPI + Postgres + pgvector)

## 1) Start local Postgres

Option A (Docker):

From repository root:

```bash
cd backend
docker compose up -d
```

Option B (Homebrew PostgreSQL 16 + pgvector):

```bash
brew services start postgresql@16
brew install pgvector
createdb unichat
```

## 2) Create backend environment

From repository root:

```bash
python -m venv .venv-backend
source .venv-backend/bin/activate
pip install -r backend/requirements.txt
pip install -e .
cp backend/.env.example backend/.env
```

Embedding configuration defaults to semantic vectors with automatic fallback:

```bash
EMBEDDING_BACKEND=auto
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_ALLOW_DOWNLOAD=false
EMBEDDING_DIMENSIONS=256
RERANKER_BACKEND=auto
RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
RERANKER_ALLOW_DOWNLOAD=false
```

`EMBEDDING_BACKEND=auto` tries sentence-transformers first, then falls back to hashing embeddings if model initialization fails.
Use `EMBEDDING_BACKEND=hashing` to force legacy behavior.
Set `EMBEDDING_ALLOW_DOWNLOAD=true` if you want the backend to download missing model files from Hugging Face on startup.

Retrieval now uses dense recall + sparse recall, fuses candidates with reciprocal rank fusion (RRF), reranks with an optional cross-encoder, and expands each selected chunk with neighbor chunks from the same document (`position-1` and `position+1` by default).
If the cross-encoder is unavailable and `RERANKER_BACKEND=auto`, reranking falls back to the heuristic reranker automatically.

Useful knobs in `backend/.env`:

```bash
RETRIEVAL_DENSE_CANDIDATES=120
RETRIEVAL_SPARSE_CANDIDATES=120
RETRIEVAL_FUSED_CANDIDATES=80
RETRIEVAL_RRF_K=60
RETRIEVAL_NEIGHBOR_WINDOW=1
```

Answer generation is adapter-driven so you can switch providers without changing retrieval code.

```bash
ANSWER_GENERATION_BACKEND=ollama
ANSWER_GENERATION_MODEL=gemma4
ANSWER_GENERATION_BASE_URL=http://127.0.0.1:11434
```

Supported generation backends:
- `ollama` (local model via Ollama)

This build enforces `ANSWER_GENERATION_BACKEND=ollama` and a Gemma model name so all answers are model-generated and no extractive fallback path is used.

### Local Gemma via Ollama

Run Ollama and pull Gemma:

```bash
ollama serve
ollama pull gemma4
```

Then set:

```bash
ANSWER_GENERATION_BACKEND=ollama
ANSWER_GENERATION_MODEL=gemma4
ANSWER_GENERATION_BASE_URL=http://127.0.0.1:11434
ANSWER_GENERATION_TIMEOUT_S=180
```

Restart the API after changing these settings.

If you are using Homebrew Postgres instead of Docker, set this in `backend/.env`:

```bash
DATABASE_URL=postgresql+psycopg:///unichat
```

## 3) Run API

From repository root:

```bash
uvicorn app.main:app --app-dir backend --reload --port 8000
```

## 4) Ingest domain corpus

```bash
curl -X POST http://127.0.0.1:8000/ingest -H 'content-type: application/json' -d '{}'
```

If embedding settings change, run ingest again so stored chunk vectors are refreshed.

Default index path is `universities/unsw-edu-au/domains/index.json` (derived from `CURATED_DIR`).

## 5) Query

```bash
curl -X POST http://127.0.0.1:8000/query \
  -H 'content-type: application/json' \
  -d '{"question":"What scholarships are available?","domains":["future-students"]}'
```

Endpoints:
- `GET /health`
- `GET /health/generation`
- `GET /domains`
- `POST /ingest`
- `POST /query`
- `POST /query/stream`

`GET /health` now includes a `generation` object and can return `status=degraded` if the configured answer-generation backend cannot be reached.

Use `GET /health/generation` for a focused adapter probe (for example, Ollama/model availability in local dev).

## 6) Streaming query (NDJSON)

`POST /query/stream` returns newline-delimited JSON (`application/x-ndjson`) so the client can render answer text incrementally.

Event types:
- `{"type":"delta","delta":"..."}`
- `{"type":"final","answer":"...","insufficient_evidence":false,"citations":[...]}`

Example:

```bash
curl -N -X POST http://127.0.0.1:8000/query/stream \
  -H 'content-type: application/json' \
  -d '{"question":"How do I apply?","domains":["business"]}'
```
