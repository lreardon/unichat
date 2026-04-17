# University Knowledge Base Platform
## Development Plan — v3 (final, consolidated)

**Audience:** Senior Engineer (implementation lead)
**Author:** CTO
**Status:** Ready for execution

---

## Guiding principles

1. **Retrieval quality is the product.** Generation is commodity; our moat is ingestion completeness, chunk quality, and metadata richness. Phases are ordered to stress-test retrieval before layering on polish.
2. **Evaluate before optimizing.** Every phase ends with measurable outputs. Do not proceed without passing the exit criteria.
3. **Boring tech, owned orchestration.** pgvector on Postgres, plain Python, FastAPI. No LangChain in the hot path. We own retrieval logic.
4. **Multi-tenant from day one.** `university_id` is a first-class column everywhere. Adding tenancy later is painful.
5. **Prefer deletion over configuration.** If a component isn't earning its keep against the eval set, rip it out.
6. **Interfaces protect migrations.** VectorStore and Embedder are abstractions. Code does not reach past them.

---

## Resolved decisions

| Item | Decision |
|---|---|
| Embedding model | Best freely available open-weight retrieval model at Phase 1 kickoff. As of April 2026, candidates are `Qwen3-Embedding` family (Apache 2.0) and `BGE-M3`. 1-day bake-off on Phase 1 Day 1 commits the winner. Dimension is locked after decision. |
| Embedding hosting | Co-located via docker-compose. Dev and prod both run locally. Clean service boundary so it can be split out later. |
| Crawler | Crawlee (Python) |
| Observability | Langfuse Cloud (hobby tier) for v1. Self-host decision triggered when we hit tier limits or need data residency. |
| Backend | Python 3.13, FastAPI |
| Tests | Mandatory per phase. Coverage thresholds + test-type requirements in exit criteria. |
| IDs | UUIDv7 (time-ordered, index-friendly, non-enumerable). Postgres 18 has native `uuidv7()`. |
| Session model | HttpOnly cookies, server-issued on first request, 14-day rolling TTL. No JWT for end-users. |
| Conversation retention | 14 days. Nightly purge job. |
| Frontends | TUI (Textual) for internal use + Flutter web-embed widget (iframe) for end-users. Both consume the same HTTP/SSE API. |
| Database | Postgres 18 with pgvector ≥0.8, pg_trgm, pgcrypto, uuid-ossp. VectorStore abstraction for future migration. |
| Dependency versions | Latest stable compatible versions at Phase 0. Manual updates via `uv lock --upgrade`. |

---

## Target architecture (end state)

```
Crawl (scheduled via cron in docker-compose)
  → Extract (trafilatura + unstructured)
  → Chunk (structural) + entity extraction (LLM)
  → Embed (local Embedder interface, co-located)
  → Postgres (pgvector + tsvector + pg_trgm)

Query → Intent classifier → {
  structured route (supervisor match, deadline lookup, scholarship filter) → SQL
  RAG route → query rewrite → hybrid retrieve → rerank → generate with citations
}
  → Guardrail pass → Response + citations + freshness stamps (SSE stream)

Frontends: TUI (internal) + Flutter web-embed widget (end-users)
Auth: HttpOnly cookies for end-users, Bearer API keys for server-to-server
```

---

## Cross-cutting architectural commitments

### VectorStore abstraction

We stay on pgvector for v1 but write code against an interface, not a table.

```python
# packages/retrieval/vector_store.py
class VectorStore(Protocol):
    async def upsert(self, items: list[VectorItem]) -> None: ...
    async def search(
        self,
        embedding: list[float],
        university_id: UUID,
        filters: MetadataFilters,
        limit: int,
    ) -> list[VectorSearchResult]: ...
    async def delete_by_document(self, document_id: UUID) -> None: ...
```

Implementations:
- `PgVectorStore` — the only concrete implementation for v1
- `FakeVectorStore` — in-memory, for unit tests

Future: `QdrantStore` or `WeaviateStore` drops in without touching retrieval logic. The rest of the system (hybrid fusion, reranking, filtering) stays on Postgres regardless — we only migrate the vector component if pgvector becomes the bottleneck, and only when data says so.

**Trigger for migration:** p95 vector search latency >200ms at the index filter stage, or HNSW index rebuilds blocking writes for >5 min. Not before.

**Enforcement:** reaching into `chunks.embedding` directly from retrieval code is a build failure. Add a lint rule in Phase 0.

### Embedder abstraction

```python
# packages/core/embedding.py
class Embedder(Protocol):
    dimension: int
    model_id: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
```

Implementations:
- `LocalEmbedder` — wraps `text-embeddings-inference` (TEI) or `sentence-transformers`, running as a sidecar on the same host as the API. Used for dev and v1 prod.
- `RemoteEmbedder` — HTTP client against a standalone TEI service. Drop-in replacement when we split it out.
- `FakeEmbedder` — deterministic hash-based vectors for tests.

**Deployment for v1 prod:** embedder runs as a sidecar container in docker-compose alongside the API, communicating over localhost. The `RemoteEmbedder` interface exists as an escape hatch if we later split to a dedicated host.

### Testing strategy (applies to every phase)

- **Unit tests:** pure functions, domain logic. pytest. Target ≥90% coverage on `core/` and `ingestion/chunking`, ≥80% overall.
- **Integration tests:** against real ephemeral Postgres (testcontainers-python) and stubbed embedding/LLM services. Never mock Postgres — it ships bugs.
- **Contract tests:** Schemathesis fuzzes the OpenAPI spec in CI. Catches API drift.
- **Eval tests:** retrieval and generation metrics on the golden set. Run in CI, block on regression.
- **End-to-end tests:** at least one per phase, asserting the full pipeline on a small fixture university.
- Every PR runs unit + integration + contract. Eval + E2E run on merge to main.
- **Test flakiness is not acceptable.** Fix or delete the same week it appears.

### Session management

End-user sessions are anonymous via HttpOnly cookies. We don't force universities to issue JWTs and we avoid student PII.

Flow:
1. Widget makes first API call with no session cookie
2. Server creates a `conversations` row, generates a session token (opaque, random 32-byte base64url), sets `Set-Cookie: kb_session=<token>; HttpOnly; Secure; SameSite=None; Path=/; Max-Age=1209600`
3. Subsequent calls include the cookie automatically (cross-origin from embedded widget requires `SameSite=None` + `Secure`)
4. Server looks up session by `sha256(token)` → conversation, extends `expires_at` on each use (rolling 14-day window)
5. Nightly job deletes expired conversations and sessions

We store `sha256(cookie_value)` not the raw token — compromised DB doesn't leak valid session cookies.

**Tenant API keys** (university backends calling us server-to-server) remain as `Authorization: Bearer` headers. Two distinct auth paths: cookie for end-users, API key for server-to-server.

**CSRF:** Since `SameSite=None` is required for the embed, we use double-submit CSRF tokens. Server sets a non-HttpOnly `kb_csrf=<random>` cookie; widget echoes it as `X-CSRF-Token` header. Server validates match on state-changing requests.

---

## Phase 0 — Foundations (Week 1)

**Goal:** Infrastructure, repo, CI, tenancy model, test harness. No ML yet.

### 0.1 Repo layout (monorepo, `uv` for Python deps)

```
/
├── packages/
│   ├── core/              # Shared domain models (Pydantic), types, errors, Embedder interface
│   ├── ingestion/         # Crawler, extractor, chunker, embedder implementations
│   ├── retrieval/         # VectorStore interface + pgvector impl, hybrid search, rerank
│   ├── api/               # FastAPI service
│   ├── tui/               # Textual TUI
│   └── eval/              # Golden set, metrics, eval runner
├── apps/
│   └── flutter_widget/    # Flutter web-embed widget (generated API client included)
├── migrations/            # Alembic
├── adrs/                  # Architecture Decision Records
├── docker-compose.yml     # Local dev stack
└── scripts/
```

### 0.2 Docker infrastructure

All services run via `docker-compose.yml`. Dockerized architecture allows quick deployment to any host.

- Postgres 18 + pgvector (container)
- Embedder TEI sidecar (container)
- API runs on host with hot reload (dev) or in container (prod)
- Raw HTML stored on local filesystem (`data/raw/{university_id}/`)
- Scheduled jobs (recrawl, purge) run as `docker compose run` commands triggered by host cron

### 0.3 Database schema (Alembic migration 0001)

```sql
-- Postgres 18 features leveraged:
-- - Native uuidv7() function
-- - Improved btree/GIN performance

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector >=0.8 required

CREATE TABLE universities (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    name TEXT NOT NULL,
    domain TEXT NOT NULL UNIQUE,
    config JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    university_id UUID NOT NULL REFERENCES universities(id),
    url TEXT NOT NULL,
    title TEXT,
    content_hash TEXT NOT NULL,
    page_type TEXT NOT NULL,
    raw_html_path TEXT,
    last_crawled TIMESTAMPTZ NOT NULL,
    last_modified TIMESTAMPTZ,
    status TEXT NOT NULL,  -- 'active', 'stale', 'error'
    UNIQUE (university_id, url)
);
CREATE INDEX ON documents (university_id, page_type);
CREATE INDEX ON documents (university_id, last_crawled);

-- Embedding dimension TBD until Phase 1 Day 1 bake-off.
-- Candidates: 1024 (BGE-M3, Qwen3-Embedding-0.6B), 2560 (Qwen3-Embedding-4B), 4096 (Qwen3-Embedding-8B).
-- Update this migration to concrete dimension before first ingest.
CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    university_id UUID NOT NULL,
    position INT NOT NULL,
    text TEXT NOT NULL,
    heading_trail TEXT[],
    metadata JSONB NOT NULL DEFAULT '{}',
    embedding vector(TBD),
    tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(array_to_string(heading_trail, ' '), '')), 'A') ||
        setweight(to_tsvector('english', text), 'B')
    ) STORED,
    last_verified TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON chunks USING GIN (tsv);
CREATE INDEX ON chunks USING HNSW (embedding vector_cosine_ops);
CREATE INDEX ON chunks USING GIN (metadata jsonb_path_ops);
CREATE INDEX ON chunks (university_id, document_id);

CREATE TABLE entities (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    university_id UUID NOT NULL,
    entity_type TEXT NOT NULL,  -- 'supervisor', 'program', 'scholarship', 'deadline'
    name TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    embedding vector(TBD),
    source_document_id UUID REFERENCES documents(id)
);
CREATE INDEX ON entities (university_id, entity_type);
CREATE INDEX ON entities USING GIN (metadata jsonb_path_ops);
CREATE INDEX ON entities USING HNSW (embedding vector_cosine_ops)
    WHERE entity_type = 'supervisor';

CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    university_id UUID NOT NULL REFERENCES universities(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL GENERATED ALWAYS AS (created_at + INTERVAL '14 days') STORED
);
CREATE INDEX ON conversations (expires_at);

CREATE TABLE messages (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    retrieved_chunk_ids UUID[],
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    university_id UUID NOT NULL REFERENCES universities(id),
    token_hash TEXT NOT NULL UNIQUE,  -- sha256 of cookie value
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON sessions (expires_at);
CREATE INDEX ON sessions (token_hash);
CREATE INDEX ON sessions (university_id, last_seen_at);

CREATE TABLE feedback (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    rating SMALLINT NOT NULL,  -- -1, 0, 1
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Index strategy notes:
- Use HNSW not IVFFlat in pgvector — better recall at our scale and no training step.
- Every tenant-scoped table has `university_id NOT NULL` with it as leading column in composite indexes. Enforce via lint check.
- pgvector ≥0.8 required for iterative index scans with metadata filters.

### 0.4 CI (GitHub Actions)

- `lint`: ruff, mypy --strict on `packages/core`, `packages/retrieval`, `packages/api`
- `test-unit`: pytest, all packages, coverage report to Codecov
- `test-integration`: testcontainers Postgres, runs on PR
- `test-contract`: Schemathesis against FastAPI OpenAPI spec
- `build-flutter`: `flutter analyze` + `flutter test` on Flutter package changes
- All required; merge blocked on any failure

### 0.5 Dev environment

`docker-compose.yml`:
```yaml
services:
  postgres:
    image: postgres:18
    environment: [...]
    volumes: [postgres-data:/var/lib/postgresql/data]
    ports: ["5432:5432"]

  embedder:
    image: ghcr.io/huggingface/text-embeddings-inference:latest  # or cpu-variant
    command: ["--model-id", "<model-from-bake-off>", "--port", "8080"]
    ports: ["8080:8080"]
    # GPU access if available; CPU-only fallback documented

  # API and ingestion run on host (hot reload), not in compose
```

`make` targets:
```
make dev          # spins up postgres + embedder, runs api with uvicorn --reload
make ingest       # runs ingestion against fixture university
make test         # full test suite
make eval         # runs eval harness against golden set
make migrate      # applies alembic migrations
```

Hardware guidance for engineers:
- Apple Silicon M2+ with ≥16GB RAM runs `Qwen3-Embedding-0.6B` comfortably on CPU
- Larger variants need GPU or substantial RAM; document as "dev uses 0.6B, prod uses {winner}" if bake-off picks differently
- If dev machine can't run prod model, use `RemoteEmbedder` against a shared embedding service

### 0.6 Observability

- Langfuse Cloud (hobby tier) for tracing
- Structured logging to stdout (Docker logs)

### Exit criteria
- Migration creates all tables with indexes as specified
- CI blocks merge on any failure
- `make dev` brings up working local stack on a fresh clone in one command

#### CEO checklist
- [x] I can see the repo on GitHub with the documented monorepo structure (`packages/`, `apps/`, `migrations/`)
- [x] A README exists with a single-command dev setup and I can read it top-to-bottom without confusion
- [x] I've watched the engineer run `make dev` on a fresh clone and the stack comes up without manual intervention
- [ ] I can see a green CI run on `main` with lint, typecheck, unit, integration, and contract test jobs all present
- [x] An ADR directory exists in the repo with at least one entry — this is where future decisions will be recorded

---

## Phase 1 — Ingestion pipeline (Weeks 2-3)

**Goal:** One pilot university fully ingested. Chunks are clean, metadata-rich, embedded, tested.

### 1.1 Embedding model bake-off (Day 1 of Phase 1)

**Do this before building the pipeline.** The dimension choice locks the `vector(N)` schema.

- Candidates: top 2-3 open-weight models on the MTEB retrieval leaderboard at kickoff time. Expected: Qwen3-Embedding variants and BGE-M3.
- Manually collect 20 representative queries from pilot university domain.
- Sample 500 chunks (rough ingestion of a subset is fine).
- For each model: embed chunks + queries, run retrieval, measure Recall@10 against manually-judged correct chunks.
- Factors weighed: retrieval quality (primary), dimension (affects storage and HNSW index size), inference latency on target hardware, license (must be permissive — Apache 2.0, MIT, or equivalent).
- Commit the winner in an ADR. Update `chunks.embedding` and `entities.embedding` columns to the concrete dimension in a migration.
- The `vector(N)` column is sticky — changing later is a full re-embed.

### 1.2 Crawler (Crawlee)

- Sitemap-first strategy: parse `robots.txt`, fetch all sitemaps, dedupe URLs.
- BFS fallback with depth limit if sitemap coverage is poor.
- Respect `robots.txt`, rate-limit per domain (start at 2 req/s, configurable per `universities.config`).
- Exponential backoff on 429/5xx.
- Persist raw HTML to local storage (`data/raw/{university_id}/{content_hash}.html`) before processing. This decouples crawl from extraction — we can reprocess without re-crawling.
- Change detection: store `ETag`/`Last-Modified`/content hash on `documents`. Skip re-extraction if hash unchanged.
- Upsert by `(university_id, url)` unique constraint.

Tests:
- Unit: URL normalization, robots.txt handling, rate limiter behavior
- Integration: locally-served fixture site (10 pages) asserting full crawl graph, respect of `robots.txt` disallow, rate-limit enforcement

### 1.3 Extraction

- Primary: `trafilatura` with `favor_precision=True` for main content (best-in-class for boilerplate removal on university sites, which are heavy with nav/footer noise)
- PDFs: `unstructured[pdf]` with `strategy="hi_res"` for program brochures, scholarship terms
- Preserve structure: keep HTML for tables and lists, strip for prose. The chunker needs structure.
- Page-type classifier: URL-pattern rules initially (`/faculty/`, `/programs/`, `/scholarships/`, `/admissions/`). Upgrade to LLM classification only if rules hit <90% accuracy on a sample.

Tests:
- Fixture-based: hand-curate 10 HTML pages + 5 PDFs representing real university content (programs, faculty, scholarships, brochures). Assert extracted text contains expected content and excludes nav/footer.

### 1.4 Structural chunking

This is the part worth spending time on. Fixed-size chunking performs poorly on structured content like faculty directories, scholarship tables, and program requirement pages.

Rules:
- **Never split a table across chunks.**
- **Never split a definition list item** (`<dl><dt><dd>`).
- Use heading hierarchy (`h1`-`h3`) as primary split boundaries.
- Target 400-800 tokens per chunk; hard cap at 1200.
- Include the document title and parent heading trail as a prefix on every chunk ("University X › Graduate Programs › MSc Computer Science › Admission Requirements").
- **For faculty/supervisor profile pages: one chunk per profile**, regardless of length up to the 1200 cap. Splitting supervisor profiles destroys retrieval for "find me a supervisor" queries.

Implementation: a `Chunker` class with an `HTMLStructuralChunker` implementation.

Tests:
- Table preservation (fixture: page with 15-row table, assert single chunk)
- Faculty profile preservation (fixture: 1500-token profile, assert single chunk up to cap)
- Heading trail correctness (fixture with nested h1/h2/h3, assert trail on each chunk)
- Token count boundaries (property-based test with Hypothesis: no chunk exceeds 1200 tokens)

### 1.5 Metadata & entity extraction

**Metadata on every chunk:** source URL, page type, department (from URL path or breadcrumb), `last_modified`, heading trail. These live in the `metadata jsonb` column for filtered retrieval ("only scholarships available to international undergraduates"). Don't rely on embeddings to pick up hard constraints — they won't reliably.

**LLM-extracted entities:** Claude Haiku (or `gpt-4o-mini`) with structured outputs. Batch 20 chunks per call. Extract:
- Program names, degree types
- Supervisor names, research interests (as tags), departments
- Scholarship names, eligibility constraints (citizenship, degree level, field)
- Deadlines (ISO dates)
- Monetary amounts

Write entities to the `entities` table and as chunk metadata. Supervisor entities get an embedding of their aggregated research interests for the supervisor-match route in Phase 3.

Idempotent: keyed by `(chunk_id, extractor_version)`. Bumping version triggers re-extraction.

Tests:
- Mock the LLM call with recorded fixtures (VCR-style)
- Assert structured output validation
- Assert idempotency on repeated calls

### 1.6 Embedding pipeline

- `LocalEmbedder` wrapping TEI sidecar
- Embeds heading-trail-prefixed text (materially improves retrieval)
- Batch 128, retries with backoff, idempotent via content hash
- Content-hash-keyed cache in Postgres (`embeddings_cache` table) so re-ingestion of unchanged chunks is free

Tests: integration test against a running TEI container, asserting determinism and dimension

### Exit criteria
- Pilot university (5-10k pages) fully ingested
- Manual spot-check of 50 random chunks: ≥95% have coherent text, correct page_type, correct heading prefix, and intact tables
- Re-crawl produces zero duplicate chunks and zero new embeddings (idempotency check)
- Unit coverage ≥90% on `chunking/` module
- Integration test runs the full pipeline on a 10-page fixture site in <30s

#### CEO checklist
- [ ] I've seen the embedding bake-off ADR: candidates tested, methodology, Recall@10 numbers per model, and the chosen winner with justification
- [ ] The pilot university is fully ingested — I can see row counts in `documents` and `chunks` matching the site's approximate page count
- [ ] The engineer has shown me 10 random chunks pulled from the database; each is coherent English text with a visible heading trail and sensible metadata
- [ ] Tables from a real program requirements page survived chunking intact (I can see the proof)
- [ ] A supervisor/faculty profile appears as a single chunk, not split
- [ ] A re-run of ingestion on the same content produces zero new embeddings (cache is working)
- [ ] Test coverage report shows ≥90% on the chunking module
- [ ] An integration test runs the full crawl→chunk→embed pipeline on a fixture site in under 30 seconds, and I've seen it pass

---

## Phase 2 — Retrieval & eval harness (Weeks 4-5)

**Goal:** Hybrid retrieval working, measurable, with a golden eval set. Do this before building the chatbot UX.

### 2.1 Eval set (do this first)

- Collect 100-150 real prospective-student questions for the pilot university. Sources: Reddit (r/ApplyingToCollege, r/gradadmissions), university subreddits, admissions FAQs, forums. Augment with questions covering:
  - Eligibility ("can I apply with a 3.0 GPA from a non-target school")
  - Deadlines and process
  - Scholarships (including constraint-heavy: "international PhD student in CS")
  - Supervisor/research matching ("who works on reinforcement learning")
  - Program specifics (credit requirements, prerequisites)
  - Policy/logistics (housing, visa support, tuition)
- For each question, manually identify the correct source URL(s). This is retrieval ground truth.
- Store in `packages/eval/golden_set/{university_id}.jsonl`.

### 2.2 VectorStore abstraction

See cross-cutting commitments above. `PgVectorStore` is the only implementation for v1. `FakeVectorStore` (in-memory) for unit tests.

### 2.3 Hybrid retrieval

- **Lexical:** Postgres `tsvector` with `websearch_to_tsquery`. Weight title/heading higher with `setweight`.
- **Vector:** via `VectorStore.search()` (one call behind the abstraction)
- **Fusion:** Reciprocal Rank Fusion (k=60 standard constant). Implemented in Python after two calls (one to VectorStore, one to Postgres lexical). This costs ~10ms overhead vs pure-SQL fusion but buys the migration escape hatch. Benchmark confirms <10ms.
- **Metadata filtering:** push filters into both sides (`WHERE university_id = $1 AND page_type = ANY($2)`). Never filter post-retrieval in Python.

Why hybrid is non-negotiable here: pure vector search fails on proper nouns (supervisor names, program codes, scholarship names like "Chevening"). BM25/tsvector catches them.

### 2.4 Reranking

- Cohere Rerank v3 API. Simplest, best-in-class.
- Take top 30 from hybrid, rerank to top 5-8.
- Skip local reranking for now. Revisit only if Cohere latency or cost becomes a problem.
- Tests: mock Cohere with recorded responses for deterministic eval runs.

### 2.5 Eval harness

- Metrics: Recall@10, MRR@10, nDCG@10 for retrieval. Measured against the golden set's correct URLs.
- Baseline progression: vector-only → +BM25 → +fusion → +rerank. Record each delta.
- CI: runs on every merge to main. PR runs a 20-question subset for speed. Block merge on regression >2% on any metric.
- Dashboard: simple Streamlit app, reads metrics table. Shows trends per commit.

### Exit criteria
- Recall@10 ≥ 85% on the golden set
- MRR@10 ≥ 0.6
- Eval runs in CI, <5 min wall time
- Regression alerts wired up
- VectorStore abstraction compiles with a second stub implementation (even if non-functional) — proves the seam holds

### Note on thresholds
If below these thresholds, the problem is almost always in ingestion (chunking or metadata), not retrieval. Go back to Phase 1 before tuning retrieval.

#### CEO checklist
- [ ] The golden eval set exists with 100+ real prospective-student questions for the pilot university, each tagged with correct source URLs
- [ ] I can view the eval dashboard and see current retrieval metrics: Recall@10 ≥ 85%, MRR@10 ≥ 0.6
- [ ] The metrics dashboard shows a historical trend — I can see improvement (or regression) commit-over-commit
- [ ] I've picked 5 random questions from the golden set, asked the engineer to retrieve results live, and the top result is clearly relevant in at least 4 of 5
- [ ] I've seen a PR that intentionally degrades retrieval get blocked by CI on the eval regression check (or equivalent demonstration that the gate works)
- [ ] The engineer can show me the `VectorStore` interface and confirm (pointing at the code) that retrieval logic does not reach past the interface into raw SQL
- [ ] Reranking is on and I've seen a before/after comparison showing measurable improvement on the eval set

---

## Phase 3 — Query understanding & routing (Week 6)

**Goal:** Handle the query types that pure RAG handles badly.

### 3.1 Intent classifier

- Small LLM call (Haiku or `gpt-4o-mini`) with structured output classifying queries into: `supervisor_match`, `deadline_lookup`, `scholarship_filter`, `program_requirements`, `general_rag`, `out_of_scope`.
- Confidence threshold; low-confidence falls through to `general_rag`.
- Cache classifications by normalized query in Postgres.

### 3.2 Structured routes

- **`supervisor_match`:** Query the `entities` table filtered to `entity_type='supervisor'`. Use the embedding of research-interest aggregations; retrieve top 10 supervisors by cosine similarity. This is a dedicated supervisor index, not the main chunk index — the partial HNSW index from Phase 0 serves it directly.
- **`deadline_lookup`:** SQL query on extracted deadline entities with date filtering.
- **`scholarship_filter`:** Structured filter over scholarship entities by eligibility metadata (citizenship, degree level, field).

These routes skip the RAG pipeline entirely and return structured data to the generator.

### 3.3 Query rewriting (RAG route only)

- Multi-query expansion: LLM generates 3 alternative phrasings. Retrieve for each, fuse results via RRF before reranking.
- HyDE optional — test against eval set; keep only if it improves metrics.

Why this matters: prospective students ask things like "can I get in with a 3.2 GPA" or "who does research on climate?" — neither of which matches page text well.

Tests:
- Unit: intent classification on labeled fixtures
- Integration: each route end-to-end against fixture data
- Eval: intent classification accuracy ≥90% on labeled subset of golden set

### Exit criteria
- Intent classifier accuracy ≥ 90% on a labeled subset of the golden set
- Supervisor-match queries hit correct supervisor in top 3 ≥ 80% of the time
- No regression on general RAG metrics

#### CEO checklist
- [ ] I can ask "who works on [research area]" and see the system route to the supervisor-match path (visible in logs/traces), returning correct supervisors
- [ ] I can ask "when's the deadline for [program]" and see it route to the deadline path with a direct, structured answer
- [ ] I can ask a general question and see it fall through to RAG — the router isn't over-routing
- [ ] The engineer has shown me the intent classifier accuracy number on a labeled test set: ≥90%
- [ ] A deliberately nonsense / off-topic query ("what's the weather") is classified as out-of-scope and refused cleanly
- [ ] Supervisor-match queries hit the correct supervisor in the top 3 results ≥80% of the time on a test batch
- [ ] No regression on the general RAG eval metrics from Phase 2

---

## Phase 4 — Generation, citations, guardrails (Week 7)

**Goal:** Turn retrieval into trustworthy answers.

### 4.1 Generation

- Claude Sonnet for production quality; Haiku as a fallback for cost-sensitive tenants.
- Prompt structure: system prompt defining role and scope, retrieved context with explicit source IDs, user question, instruction to cite every claim with source IDs.
- Structured output: answer text with inline citation markers, plus a citations list mapping markers to URLs + `last_verified` dates.
- Stream responses. Users perceive <500ms to first token as responsive.

### 4.2 Citation enforcement

- Post-generation check: every factual claim must have a citation marker. Implement as a deterministic check on claim density; escalate to an LLM verifier if needed.
- If citations are missing or malformed, regenerate with stronger instructions, then fall back to "I don't have a reliable source for this" rather than an uncited answer.

### 4.3 Guardrails

- **Scope:** refuse if retrieval confidence is low (top rerank score below threshold) or intent is `out_of_scope`.
- **Hallucination check:** for high-stakes claims (deadlines, eligibility, amounts), verify the generated value appears in the retrieved context. Regex/substring check, not another LLM call.
- **Freshness:** surface `last_verified` date in responses for time-sensitive content. Flag content >90 days old.
- **Prompt injection:** standard sanitization on retrieved content, clearly delimited in the prompt.

### 4.4 Answer eval

- Extend the eval harness: faithfulness (claims supported by citations), answer correctness (LLM-judge against reference answers), citation accuracy (cited URLs actually contain the claim).
- Use Claude Opus as judge. Spot-check judge outputs monthly.

### 4.5 Langfuse integration

- Every generation traced with: retrieved chunks, prompt, response, token usage, latency, user feedback (when received).
- Traces linked to conversation IDs so we can reconstruct full user journeys.

### Exit criteria
- Faithfulness ≥ 95% on golden set
- Citation accuracy ≥ 98%
- Manual review of 50 responses: zero hallucinated facts, zero fabricated citations
- Langfuse traces flowing for every generation

#### CEO checklist
- [ ] I can ask a real question via curl or a test harness and see a streamed response with inline citations, and every citation resolves to a real URL on the university site
- [ ] I've clicked through 10 citations from sample answers and each cited page actually contains the claim being cited
- [ ] Time-sensitive answers (deadlines, tuition) display a freshness/last-verified date
- [ ] I've asked a question the system cannot answer from its knowledge base and watched it refuse cleanly rather than hallucinate
- [ ] Faithfulness score on the eval set is ≥95% and citation accuracy is ≥98%
- [ ] Langfuse Cloud dashboard shows traces for every generation — I can click a trace and see the retrieved chunks, prompt, model output, and latency
- [ ] I've personally reviewed 20 generated answers and found zero fabricated facts and zero fabricated citations

---

## Phase 5 — API, auth, multi-tenancy (Week 8)

**Goal:** Production-ready API.

### 5.1 Endpoints

```
POST /v1/conversations                    → creates conversation, sets session cookie, returns UUID
POST /v1/conversations/{id}/messages      → sends message, streams SSE response
GET  /v1/conversations/{id}               → conversation history (session-scoped)
POST /v1/messages/{id}/feedback           → thumbs up/down + optional comment
GET  /v1/universities/{id}/meta           → public tenant metadata (name, branding) for widget init
GET  /healthz
GET  /readyz
```

### 5.2 SSE event types

```
event: token          data: {"text": "..."}
event: citations      data: {"citations": [{"marker": "[1]", "url": "...", "last_verified": "..."}]}
event: retrieved      data: {"chunk_ids": ["..."]}  // observability / debug
event: done           data: {"message_id": "..."}
event: error          data: {"code": "...", "message": "..."}
```

Both TUI and Flutter widget consume this.

### 5.3 Auth

Two distinct paths:

- **End-user sessions:** HttpOnly cookies (see cross-cutting commitments above). First request without cookie creates session and sets one. CSRF via double-submit token.
- **Tenant server-to-server:** API keys per university, `Authorization: Bearer <key>`. Keys issued manually during onboarding, stored hashed in DB.

Rate limiting: Redis-backed (docker-compose service), per-API-key and per-session tiers.

### 5.4 Tenant configuration

Per-university settings in `universities.config jsonb`:
- Prompt tweaks (system prompt additions, tone)
- Allowed page types (scope restrictions)
- Custom refusal messages
- Rate limit overrides
- Branding (colors, name) returned from `/meta` endpoint

### 5.5 Feedback capture

Thumbs up/down + free text, tied to conversation + retrieved chunks. Goldmine for iteration. Exposed as endpoint, consumed by both frontends.

### 5.6 Contract & tests

- OpenAPI spec generated from FastAPI; published at `/openapi.json`
- Schemathesis fuzzes all endpoints against the spec in CI
- Tenant isolation test: seed two universities' data, query one, assert zero cross-contamination. **Automated, hard CI block.**
- Session lifecycle test: create → use → extend → expire → purge
- CSRF validation test: missing/mismatched token rejected
- Load test: Locust, 100 concurrent conversations, p95 <3s end-to-end

### Exit criteria
- OpenAPI spec published
- All tests green including tenant isolation
- 14-day retention enforced (simulated expired conversation inaccessible)
- Langfuse traces flowing for every conversation
- Rate limits demonstrably active

#### CEO checklist
- [ ] The OpenAPI spec is published at a visible URL and renders correctly in a Swagger/Redoc viewer
- [ ] I can hit the API with curl using a tenant API key and get a streamed response
- [ ] Session cookies work: I can send a first request without a cookie, get one back, and subsequent requests maintain the conversation without me passing an ID
- [ ] The tenant isolation test is visible in CI as a named, required check — the engineer has walked me through what it does
- [ ] The engineer has demonstrated the tenant isolation test failing on a deliberately broken branch, proving it catches real bugs
- [ ] Load test results show p95 latency <3s under 100 concurrent conversations — I've seen the report
- [ ] A conversation created 15+ days ago (simulated in a test) is no longer accessible — the 14-day retention is enforced
- [ ] CSRF protection is active: requests without the CSRF token are rejected on state-changing endpoints (engineer demonstrates with curl)
- [ ] Rate limiting is active: I've seen a demonstration of a rate-limited response when hammering an endpoint

---

## Phase 6 — Frontends (Weeks 9-10)

Both frontends consume the same API and share OpenAPI-generated types. They run in parallel after the API stabilizes.

### 6.1 TUI (Week 9, `packages/tui`, Textual)

**Purpose:** fast iteration tool for engineers, QA, and university admissions staff reviewing answer quality. Not end-user-facing.

**Auth:** dev API key (server-to-server path). No cookies needed for TUI.

**Features:**
- Login with API key
- University picker (multi-tenant view for internal users)
- Conversation view: split pane — chat on left, retrieved chunks on right (scores, URLs, highlight of cited spans)
- Keyboard-driven: `/feedback`, `/reset`, `/debug` toggles
- Shows retrieval latency, generation latency, token counts inline
- Exports conversations as JSON for eval set augmentation

**Tech:**
- Textual (Python)
- httpx for API calls, SSE client for streaming
- Shares Pydantic models with API via `packages/core`

**Distribution:**
- `uv tool install` from internal PyPI, or direct `uv tool install` from the repo

**Tests:**
- Textual snapshot tests for key screens
- Integration test: TUI against a running API in testcontainers

### 6.2 Flutter web-embed widget (Week 10, `apps/flutter_widget`)

**Purpose:** end-user-facing, embeddable in university admissions pages.

**Embed model:** iframe hosted by a tiny `widget.js` loader. The Flutter app itself lives at `widget.ourproduct.com`; `widget.js` is a <5KB script that creates the iframe, passes init params via URL, and handles resize/theme via `postMessage`.

**Why iframe over in-page injection:** complete style/JS isolation from host pages. Universities have arbitrary CSS, analytics, and JS that will conflict with an in-page Flutter widget. Iframe makes this a non-issue.

**Embed interface:**
```html
<div id="kb-widget"></div>
<script src="https://widget.ourproduct.com/v1/widget.js"
        data-university-id="{uuid}"
        data-theme="auto"></script>
```

**Widget init params (URL-encoded to iframe src):**
- `university_id` (required)
- `theme` (`auto` | `light` | `dark`)
- `primary_color` (hex override)
- `locale` (default `en`)

**Widget ↔ host postMessage events:**
- `widget:ready` — widget loaded
- `widget:resize` — new height for host to apply to iframe
- `widget:nav` — user clicked a citation URL; host chooses open behavior

**Features (v1):**
- University-branded chat (theme driven by `GET /v1/universities/{id}/meta`)
- Conversation history (persisted server-side, 14-day TTL)
- Inline citations that open source URLs
- Freshness indicators on time-sensitive answers
- Thumbs up/down + comment feedback
- Suggested questions on empty state, seeded from top queries per university

**Architecture:**
- Riverpod state management
- Generated API client from OpenAPI spec (`openapi-generator-cli`)
- SSE client: `flutter_client_sse` or hand-rolled over `dart:html` `EventSource`
- `freezed` for models, `json_serializable` for codegen
- Cookies handled by browser natively (iframe shares `*.ourproduct.com` cookie scope with API)

**Deployment:**
- `flutter build web --release --wasm` (WASM where supported, JS fallback)
- Served via Caddy reverse proxy (docker-compose service)
- `widget.js` loader: short TTL, separate deploy
- Flutter bundle: long TTL + content-hashed filenames

**Tests:**
- Widget tests for chat components, citation rendering, resize behavior
- Integration tests with mocked API
- Playwright E2E: fixture HTML page with script tag, full conversation flow
- `flutter analyze` zero warnings in CI

### Exit criteria
- Both frontends work against staging API
- Flutter widget embeddable via script tag on a test HTML page in Chrome, Safari, Firefox
- TUI distributable via `uv tool install`

#### CEO checklist

**TUI:**
- [ ] I can `uv tool install` (or equivalent) the TUI and run it on my own machine
- [ ] I can log in with a dev API key, pick the pilot university, and hold a working conversation
- [ ] The split-pane view shows retrieved chunks alongside the answer, with scores and URLs visible
- [ ] I can thumbs-up/down a response and see the feedback recorded in the database
- [ ] I can export a conversation as JSON for later use

**Flutter widget:**
- [ ] I can open a test HTML page with the `<script>` tag embed and see the widget load in an iframe
- [ ] The widget is university-branded (color, name) based on the `university_id` param
- [ ] I can have a full conversation in the widget, with streaming responses and clickable citations
- [ ] The widget works across Chrome, Safari, and Firefox
- [ ] The widget does not break the host page's styling (tested by embedding in a page with aggressive CSS)
- [ ] Cookie-based sessions work from the embedded widget — I can refresh the page and my conversation is still there (within 14 days)
- [ ] The widget's Flutter bundle is served from the CDN with proper caching (engineer shows cache-hit headers)
- [ ] `flutter analyze` shows zero warnings in CI

---

## Phase 7 — Operational maturity (Week 11)

**Goal:** Survive contact with real users.

### 7.1 Scheduled recrawl

- Host cron → `docker compose run` job
- Weekly full recrawl by default
- Daily recrawl of high-change page types (news, deadlines, admissions)
- Per-tenant schedule override in `universities.config`

### 7.2 Nightly purge jobs

- `purge-expired-conversations`: `DELETE FROM conversations WHERE expires_at < now()`. Cascades to `messages` and `feedback`.
- `purge-expired-sessions`: `DELETE FROM sessions WHERE expires_at < now()`
- Logged delete counts for audit

### 7.3 Monitoring

- Metrics: query volume, latency percentiles (p50/p95/p99), retrieval score distribution, refusal rate, thumbs-down rate, cost per query
- Alerts (to Slack or email):
  - Latency p95 spike
  - Refusal rate >20%
  - Embedding/LLM API error rate >1%
  - Purge job failure
  - Recrawl job failure
- Weekly auto-generated report: top queries, lowest-rated responses, stalest content

### 7.4 Content quality loop

- Cron surfaces: chunks never retrieved (dead weight, investigate), queries with no good retrieval (coverage gaps), thumbs-down responses grouped by intent
- Results routed to a review queue for team inspection

### 7.5 Chaos tests

- Kill embedder mid-conversation → assert graceful error, not crash
- Kill LLM API → assert fallback behavior (retry, graceful refusal)
- DB failover → assert in-flight requests fail cleanly and new requests succeed after failover
- Rate-limit burst → assert 429s, not collapse

### Exit criteria
- Recrawl runs unattended for 2 weeks, no manual intervention required
- Purge jobs run nightly with audit log
- Alerting verified via chaos test (break a thing, confirm alert fires)
- Weekly report has been generated at least once

#### CEO checklist
- [ ] I can see the monitoring dashboard: query volume, p50/p95/p99 latency, refusal rate, thumbs-down rate, cost per query
- [ ] Alerts are wired up to a channel I receive (Slack, email, etc.) — I've seen a test alert fire
- [ ] The recrawl schedule has run at least once unattended, and I can see the updated `last_crawled` timestamps in the documents table
- [ ] The nightly purge job has run and removed expired conversations — I've seen the delete count in logs
- [ ] The chaos test demonstration: engineer kills the embedder mid-conversation, and the system returns a graceful error rather than crashing
- [ ] The first weekly automated report has been generated — top queries, lowest-rated responses, stalest content
- [ ] A content-quality review queue exists somewhere I can check, showing coverage gaps and negative feedback for human review

---

## Phase 8 — Second tenant (Week 12)

**Goal:** Validate the "platform" part of "knowledge base platform."

Onboard a second university end-to-end. Time it. Document it.

The target is **<1 day of engineering time to onboard a new tenant.** If it takes longer, something is hardcoded that shouldn't be.

### Deliverables

- Second university fully ingested and serving queries through the widget
- Written onboarding runbook
- Cross-tenant eval report showing both universities meet Phase 2 retrieval thresholds
- Live cross-tenant smoke test confirming zero data leakage in production (not just the automated test)

### Exit criteria
- Second tenant passes golden-set eval with Recall@10 ≥ 85% using the same pipeline, zero code changes
- Runbook exists and has been followed end-to-end by the engineer
- Onboarding time measured and logged

#### CEO checklist
- [ ] The second university is fully ingested and serving queries through the widget
- [ ] The engineer logged their onboarding time and it was under one engineering day — if over, I've reviewed what dragged and signed off on a fix plan
- [ ] A written onboarding runbook exists and I can follow it at a high level without needing to ask questions
- [ ] Cross-tenant eval report shows both universities meet Phase 2 retrieval thresholds (Recall@10 ≥ 85%, MRR@10 ≥ 0.6)
- [ ] I've queried University A through its widget and confirmed I see zero University B content (and vice versa) — live cross-tenant smoke test, not just the automated test
- [ ] Zero code changes were required to onboard tenant 2 — only config/data. Engineer can point at the commit history to confirm this
- [ ] The platform is ready to demo to prospective university customers — I've done a dry run

---

## What's explicitly out of scope for v1

These come later, driven by data:

- Fine-tuning embeddings on university-specific data
- Knowledge graph representation
- Agentic flows (multi-step research, tool use beyond structured routes)
- Voice interface
- Multilingual support (revisit once we have international tenants)
- Self-hosted LLMs
- Native iOS/Android Flutter builds
- Standalone mobile app

Resist adding these until the eval set says we need them.

---

## Timeline summary

| Phase | Weeks | Focus |
|---|---|---|
| 0 | 1 | Foundations |
| 1 | 2-3 | Ingestion |
| 2 | 4-5 | Retrieval + eval |
| 3 | 6 | Query routing |
| 4 | 7 | Generation + guardrails |
| 5 | 8 | API |
| 6 | 9-10 | TUI + Flutter widget (parallel) |
| 7 | 11 | Operational maturity |
| 8 | 12 | Second tenant |

**12 weeks to production-ready, two-frontend, two-tenant platform.**

Weeks 1-3 are the infrastructure and ingestion slog. Weeks 4-7 are the interesting ML/retrieval work. Weeks 8-12 are hardening and validation. The most common failure mode is underinvesting in Phase 1 (chunking and metadata) and trying to make up for it with prompt engineering in Phase 4. Don't.

---

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| University sites have poor sitemaps / aggressive bot blocking | Medium | BFS fallback; contact university IT for allowlist; cache raw HTML so we re-process rather than re-crawl |
| Embedding/rerank/LLM API costs blow up | Medium | Cost dashboard from day one; Haiku fallback for generation; embeddings are self-hosted so no per-call cost |
| PDFs (program brochures) are layout-heavy and extract poorly | High | Buffer time in Phase 1.3; `unstructured` hi_res + manual spot-check; accept some PDFs won't parse well and log them |
| Supervisor data is stale or inconsistent across pages | High | Treat supervisor entities as a first-class curated index; admin UI for universities to correct entries in v2 |
| Eval set is too small or not representative | Medium | Grow continuously from real user queries via feedback loop; target 500 questions per tenant by end of Phase 7 |
| Flutter web bundle too heavy for widget UX | Low-Medium | Iframe isolation limits the pain to the widget itself; WASM build + aggressive caching; fall back to lighter web tech if needed (deferred to v2 if it becomes real) |

---

## Open items for the senior engineer

1. **Embedding model bake-off:** you own it. Pick date within Phase 1, Day 1. Document methodology, results, decision in an ADR.
2. **Widget domain/cookie strategy:** confirm we can set up subdomains for shared cookie scope. If not, we need a cross-origin token exchange instead of cookies — meaningful protocol change.
3. **Production hosting strategy:** when ready to move beyond local Docker, evaluate VPS providers (Hetzner, DigitalOcean, etc.) with enough RAM for the embedding model. Docker-compose deploys directly.

---

## What's unchanged and non-negotiable

- Multi-tenancy from day one; tenant isolation tests as hard CI blocker
- UUIDs everywhere (PG18's native `uuidv7()` makes this free)
- VectorStore + Embedder abstractions; no direct pgvector or model calls outside implementations
- Testing at every phase: unit (coverage thresholds), integration (testcontainers), contract (Schemathesis), eval (golden set), E2E (one per phase)
- Evaluation before optimization: retrieval metrics gate every phase
- Flaky tests get fixed or deleted the same week they appear

Ship the plan, not the planning. Let's go.