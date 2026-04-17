# UniChat

Multi-tenant university knowledge-base chatbot. Prospective students ask questions about programs, deadlines, supervisors, and scholarships via an embeddable widget. Answers are grounded in crawled university content with inline citations.

## Architecture

```
packages/
  core/            Config, DB, Embedder + VectorStore abstractions, domain models
  api/             FastAPI service (routes, auth, session middleware)
  ingestion/       Crawl → extract → chunk → embed pipeline
  retrieval/       Hybrid search (vector + full-text), reranking
  generation/      LLM generation with citations + guardrails
  tui/             Textual-based terminal UI (internal tool)
  eval/            Golden set, metrics, eval runner
apps/
  flutter_widget/  Flutter web-embed widget (iframe + postMessage)
infra/             Terraform for GCP (Cloud SQL, Cloud Run, CDN)
migrations/        Alembic (Postgres 18 + pgvector)
adrs/              Architecture decision records
scripts/           Dev/ops scripts
tests/             Unit, integration, contract, eval
```

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker + Docker Compose
- 64GB+ RAM (for harrier-oss-v1 27B embedding model)

## Quick Start

```bash
# 1. Clone and enter project
cd v0.2

# 2. Install Python dependencies
uv sync --all-extras

# 3. Copy environment config
cp .env.example .env

# 4. Start Postgres 18 + embedding sidecar, run migrations, start API
make dev
```

That's it. The API is at `http://localhost:8000`. Health check: `GET /health`.

## Make Targets

| Command | What it does |
|---|---|
| `make dev` | Start infrastructure + migrate + run API with hot reload |
| `make services` | Start Postgres + embedder only (no API) |
| `make api` | Run API server with hot reload |
| `make migrate` | Run Alembic migrations |
| `make test` | Run unit tests (no infrastructure needed) |
| `make test-all` | Run all tests including integration |
| `make lint` | Ruff check + format check |
| `make typecheck` | Mypy strict mode |
| `make eval` | Run retrieval eval harness |
| `make ingest` | Run ingestion on fixture university |
| `make down` | Stop all services |

## API Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | None | Database connectivity check |
| POST | `/chat` | Session cookie + CSRF | Send message, get response |
| POST | `/ingest` | API key (Bearer) | Trigger document ingestion |

Two auth paths:
- **End-users (widget):** HttpOnly session cookies with CSRF double-submit
- **Server-to-server (university backends):** `Authorization: Bearer <api_key>`

## Running Tests

```bash
# Unit tests only (no infrastructure needed)
uv run pytest tests/ -v -m "not integration"

# All tests (requires running Postgres)
make services
make migrate
uv run pytest tests/ -v
```

## Project Decisions

Architecture Decision Records live in [adrs/](adrs/). Key decisions:

- [ADR-0001](adrs/0001-monorepo-structure.md) — Monorepo structure

## Hardware Notes (Dev)

- Apple Silicon M4 Max or equivalent with 64GB+ RAM runs `harrier-oss-v1` (27B) locally
- If your machine can't run the embedder locally, set `UNICHAT_EMBEDDER_TYPE=remote` and point `UNICHAT_EMBEDDER_URL` at a shared dev instance
