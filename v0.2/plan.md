# University Knowledge Base Platform
## Development Plan — v3 (final)

**Audience:** Senior Engineer (implementation lead)
**Author:** CTO

---

## Resolved decisions (v3 deltas)

| Item | v2 | v3 |
|---|---|---|
| Embedding model | BGE-M3 default | **Best freely available at Phase 1 kickoff.** As of April 2026, the leading open-weight retrieval models on MTEB English/multilingual are in the `Qwen3-Embedding` family (`Qwen3-Embedding-8B`, `Qwen3-Embedding-4B`, `Qwen3-Embedding-0.6B`, Apache 2.0) and `BGE-M3`. Do a 1-day bake-off on Phase 1 Day 1; commit to the winner. Default expectation: `Qwen3-Embedding-4B` (4096 dim) if hardware permits, `Qwen3-Embedding-0.6B` (1024 dim) otherwise. |
| Embedding hosting | Self-hosted on Cloud Run | **In-process / co-located on the server.** Dev = engineer's machine. Prod = embedding service on the same host as the API for now, with a clean service boundary so it can be split out later. Details below. |
| Session model | JWT issued by universities | **HttpOnly cookies**, server-issued on first request, 14-day TTL. No JWT for end-users. Details below. |
| Conversation retention | 30 days | **14 days.** `conversations.expires_at = created_at + 14 days`, nightly purge job. |
| Flutter target | Web + iOS/Android/standalone | **Web-embed widget only for v1.** iframe-embeddable, single JS bundle, university-branded via init params. Native targets deferred. |
| Software versions | Latest compatible | **Postgres 18.** All other deps pinned to latest stable compatible versions as of Phase 0 kickoff, with Renovate bot to keep them current. |

---

## Key architectural changes

### 1. Embedding: co-located, interface-bound

We're embedding in-process for now, but we do not want embedding calls scattered through the codebase as direct model invocations. Same discipline as the VectorStore abstraction:

```python
# packages/core/embedding.py
class Embedder(Protocol):
    dimension: int
    model_id: str

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
```

Implementations:
- `LocalEmbedder` — wraps `sentence-transformers` or `text-embeddings-inference` in a sidecar process, running on the same host as the API. Used for dev and v1 prod.
- `RemoteEmbedder` — HTTP client against a standalone TEI service. Drop-in replacement when we split it out.
- `FakeEmbedder` — deterministic hash-based vectors for tests.

**Deployment for v1 prod:** embedder runs as a sidecar container in the same Cloud Run service as the API, communicating over localhost. This keeps "co-located" literal while preserving the boundary. If Cloud Run's CPU-per-service limits bite, we either size up the service or flip to `RemoteEmbedder` with zero code changes.

**Dev:** engineer runs the embedder locally via `docker compose up embedder`. A single command starts Postgres 18, the embedder, and the API.

**Model choice protocol (Phase 1, Day 1):**
- Candidates: top 2-3 open-weight models on the MTEB retrieval leaderboard at the time of kickoff. Expected: Qwen3-Embedding variants and BGE-M3.
- Bake-off: 20 representative queries × 500 chunks from pilot university. Measure Recall@10 against manually judged correct chunks.
- Factors: retrieval quality (primary), dimension (affects storage and HNSW index size), inference latency on target hardware, license (must be permissive — Apache 2.0, MIT, or equivalent).
- Commit the winner. The `vector(N)` column dimension is locked after this decision; changing means a full re-embed.

### 2. Session management via HttpOnly cookies

End-user sessions (prospective students interacting with the Flutter widget) are anonymous by default. We don't want to force universities to issue JWTs, and we don't want student PII if we can avoid it.

**Flow:**
1. Widget makes first API call with no session cookie
2. Server creates a `conversations` row, generates a session token (opaque, random 32-byte base64url), sets `Set-Cookie: kb_session=<token>; HttpOnly; Secure; SameSite=None; Path=/; Max-Age=1209600`
3. Subsequent calls include the cookie automatically (including cross-origin from embedded widget, which is why `SameSite=None` + `Secure` are required)
4. Server looks up session by `session_token` → conversation, extends `expires_at` on each use (rolling 14-day window)
5. Nightly job deletes conversations where `expires_at < now()`

**Tables updated:**
```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    university_id UUID NOT NULL REFERENCES universities(id),
    token_hash TEXT NOT NULL UNIQUE,  -- sha256 of the cookie value
    conversation_id UUID REFERENCES conversations(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON sessions (expires_at);
CREATE INDEX ON sessions (university_id, last_seen_at);
```

We store `sha256(cookie_value)` not the raw token — compromised DB doesn't leak valid session cookies.

**Tenant API keys (for university backends calling us server-to-server) remain as `Authorization: Bearer` headers.** Two distinct auth paths: cookie for end-users, API key for server-to-server.

**CSRF:** Since we're `SameSite=None` for the embed, we need CSRF protection. Approach: double-submit token. Server sets a second non-HttpOnly cookie `kb_csrf=<random>`; Flutter widget reads it and echoes as `X-CSRF-Token` header. Server validates match on state-changing requests. Standard pattern.

**Tests:**
- Session lifecycle: create → use → extend → expire → purge
- CSRF validation (missing token rejected, mismatched token rejected)
- Cross-tenant session isolation (session for university A cannot access university B)

### 3. Web-embed widget (Flutter v1)

**Goal:** a single script tag or iframe that universities drop into their admissions pages.

```html
<div id="kb-widget"></div>
<script src="https://widget.ourproduct.com/v1/widget.js" 
        data-university-id="{uuid}"
        data-theme="auto"></script>
```

**Architecture decision:** Flutter web is viable but heavy for a widget (bundle size, startup time). Two options:

**Option A: Flutter web, compiled to CanvasKit, loaded in iframe**
- Pros: matches your existing Flutter expertise, consistent with other projects, `freezed`/`riverpod` reuse
- Cons: ~2-5MB initial bundle, slower cold start, CanvasKit rendering can look out-of-place on host pages

**Option B: iframe hosting a standalone Flutter web app**
- Same Flutter app, but loaded in an iframe rather than a JS-injected div
- Pros: complete style/JS isolation from host page, trivial to embed, Flutter bundle constraints don't affect host page perf
- Cons: iframe communication for resize/theming needs `postMessage`

**Recommendation: Option B (iframe + postMessage).** The isolation is worth it for a widget that runs on untrusted host pages (universities have arbitrary CSS, analytics, JS that could conflict). The `widget.js` loader is a tiny script (<5KB) that creates the iframe, passes init params via URL, and handles resize/theme via postMessage. The Flutter app itself is served from `widget.ourproduct.com` with aggressive caching.

**Widget init params (via URL):**
- `university_id` (required)
- `theme` (`auto` | `light` | `dark`)
- `primary_color` (hex override)
- `locale` (default `en`)

**Widget ↔ host postMessage events:**
- `widget:ready` — widget loaded
- `widget:resize` — new height for host to apply to iframe
- `widget:nav` — user clicked a citation URL; host can choose to open in new tab or same window

**Tech:**
- Flutter 3.x, web target, CanvasKit renderer
- Riverpod state management
- Generated API client from OpenAPI (`openapi-generator`)
- SSE via `flutter_client_sse` or hand-rolled over `dart:html` `EventSource`
- Cookies handled natively by browser (iframe same-origin to API via subdomain setup: API at `api.ourproduct.com`, widget at `widget.ourproduct.com`, both share `*.ourproduct.com` cookie scope)

**Deployment:**
- Widget built as `flutter build web --release --wasm` (WASM where supported, JS fallback)
- Served from Cloud Run + Caddy (same pattern as Rentogether)
- CDN via Cloud CDN in front of the widget origin for global cache
- `widget.js` loader served separately with short TTL; Flutter bundle with long TTL + content-hashed filenames

**Tests:**
- Widget tests for chat components, citation rendering, resize behavior
- Integration tests with mocked API
- Manual embed test: a fixture HTML page with the script tag, verified in Playwright E2E
- `flutter analyze` zero warnings

### 4. Dependency version strategy

- **Postgres 18** (confirmed)
- Python 3.13 (latest stable)
- Node 22 LTS (for Flutter tooling and any JS bits)
- Flutter latest stable at Phase 0
- All Python deps managed by `uv`, pinned in `uv.lock`
- Dart deps in `pubspec.lock`
- **Renovate bot** configured with:
  - Weekly PRs for patch/minor updates, auto-merge if CI green
  - Separate PRs for major versions, manual review required
  - Security advisories trigger immediate PRs
- CI runs against pinned versions; a weekly scheduled job runs against latest to catch upcoming breakage

---

## Updated schema (deltas from v2)

```sql
-- Postgres 18 features we'll lean on:
-- - UUIDv7 generation native (uuidv7() function added in PG18)
-- - Virtual generated columns (no-op for us, but available)
-- - Improved btree/GIN performance

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector 0.8+ required for good HNSW + filter performance

-- Use Postgres 18's native uuidv7() for defaults; app-side generation still preferred for observability
ALTER TABLE universities ALTER COLUMN id SET DEFAULT uuidv7();
-- ... (same for all tables)

-- Conversations with 14-day retention baked in
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    university_id UUID NOT NULL REFERENCES universities(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL GENERATED ALWAYS AS (created_at + INTERVAL '14 days') STORED
);
CREATE INDEX ON conversations (expires_at);

-- Sessions table (cookie-backed)
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT uuidv7(),
    university_id UUID NOT NULL REFERENCES universities(id),
    token_hash TEXT NOT NULL UNIQUE,
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON sessions (expires_at);
CREATE INDEX ON sessions (token_hash);

-- Embedding dimension is TBD until Phase 1 Day 1 bake-off.
-- Placeholder; update migration to concrete dimension before first ingest.
-- Candidates: 1024 (BGE-M3, Qwen3-Embedding-0.6B), 2560 (Qwen3-Embedding-4B), 4096 (Qwen3-Embedding-8B)
```

**Note on HNSW + metadata filters:** pgvector 0.7+ added iterative index scans that handle metadata filtering efficiently. Confirm we're on ≥0.8 for best behavior with `WHERE university_id = ?` filtered vector search.

**Note on purge job:** Conversations expire via `expires_at`; a scheduled Cloud Run Job runs nightly: `DELETE FROM conversations WHERE expires_at < now()`. Cascades to `messages` and `feedback`. Sessions purged separately by their own `expires_at`.

---

## Revised phase plan

Timeline unchanged at 12 weeks. Phases adjusted for scope changes:

### Phase 0 — Foundations (Week 1)
- Postgres 18 + pgvector ≥0.8 + pgcrypto + pg_trgm
- Python 3.13, `uv`, monorepo
- Embedder sidecar in `docker-compose.yml` for local dev
- Terraform for GCP: Cloud SQL (PG18), Cloud Run services (API + embedder sidecar), Cloud Run Jobs, GCS, Secret Manager, Cloud CDN for widget
- CI with full test matrix
- **Renovate** configured

#### CEO checklist
- [ ] I can see the repo on GitHub with the documented monorepo structure (`packages/`, `apps/`, `infra/`, `migrations/`)
- [ ] A README exists with a single-command dev setup and I can read it top-to-bottom without confusion
- [ ] I've watched the engineer run `make dev` on a fresh clone and the stack comes up without manual intervention
- [ ] I can see a green CI run on `main` with lint, typecheck, unit, integration, and contract test jobs all present
- [ ] `terraform apply` has been run against a dev GCP project and I can see the resources in the console (Cloud SQL instance, Cloud Run services, GCS buckets)
- [ ] Renovate has opened at least one dependency PR, proving it's connected
- [ ] An ADR (architecture decision record) directory exists in the repo with at least one entry — this is where future decisions will be recorded

### Phase 1 — Ingestion (Weeks 2-3)
- **Day 1: Embedding model bake-off.** 20 queries × 500 chunks. Commit to winner. Lock `vector(N)` dimension.
- Crawlee crawler, trafilatura/unstructured extraction, structural chunker, entity extraction, embedding via `LocalEmbedder`
- Full test coverage as specified in v2

#### CEO checklist
- [ ] I've seen the embedding bake-off ADR: candidates tested, methodology, Recall@10 numbers per model, and the chosen winner with justification
- [ ] The pilot university is fully ingested — I can see a row count in the `documents` and `chunks` tables that matches the site's approximate page count
- [ ] The engineer has shown me 10 random chunks pulled from the database, and each one is coherent English text with a visible heading trail and sensible metadata
- [ ] Tables from a real program requirements page survived chunking intact (I can see the proof)
- [ ] A supervisor/faculty profile appears as a single chunk, not split
- [ ] A re-run of ingestion on the same content produces zero new embeddings (cache is working)
- [ ] Test coverage report shows ≥90% on the chunking module
- [ ] An integration test runs the full crawl→chunk→embed pipeline on a fixture site in under 30 seconds, and I've seen it pass

### Phase 2 — Retrieval + eval (Weeks 4-5)
- VectorStore abstraction, `PgVectorStore` implementation
- Hybrid retrieval (tsvector + vector via abstraction + RRF in Python)
- Cohere Rerank
- Eval harness, CI integration
- Exit: Recall@10 ≥ 85%, MRR@10 ≥ 0.6

#### CEO checklist
- [ ] The golden eval set exists with 100+ real prospective-student questions for the pilot university, each tagged with correct source URLs
- [ ] I can view the eval dashboard and see current retrieval metrics: Recall@10 ≥ 85%, MRR@10 ≥ 0.6
- [ ] The metrics dashboard shows a historical trend — I can see improvement (or regression) commit-over-commit
- [ ] I've picked 5 random questions from the golden set, asked the engineer to retrieve results live, and the top result is clearly relevant in at least 4 of 5
- [ ] I've seen a PR that intentionally degrades retrieval get blocked by CI on the eval regression check (or equivalent demonstration that the gate works)
- [ ] The engineer can show me the `VectorStore` interface and confirm (pointing at the code) that retrieval logic does not reach past the interface into raw SQL — this is the migration escape hatch
- [ ] Reranking is on and I've seen a before/after comparison showing measurable improvement on the eval set

### Phase 3 — Query routing (Week 6)
- Intent classifier, structured routes for supervisor/deadline/scholarship, query rewriting

#### CEO checklist
- [ ] I can ask "who works on [research area]" and see the system route to the supervisor-match path (visible in logs/traces), returning correct supervisors
- [ ] I can ask "when's the deadline for [program]" and see it route to the deadline path with a direct, structured answer
- [ ] I can ask a general question and see it fall through to RAG — the router isn't over-routing
- [ ] The engineer has shown me the intent classifier accuracy number on a labeled test set: ≥90%
- [ ] A deliberately nonsense / off-topic query ("what's the weather") is classified as out-of-scope and refused cleanly
- [ ] Supervisor-match queries hit the correct supervisor in the top 3 results ≥80% of the time on a test batch
- [ ] No regression on the general RAG eval metrics from Phase 2

### Phase 4 — Generation + guardrails (Week 7)
- Generation with citations, faithfulness checks, freshness stamps, Langfuse Cloud integration

#### CEO checklist
- [ ] I can ask a real question via curl or a test harness and see a streamed response with inline citations, and every citation resolves to a real URL on the university site
- [ ] I've clicked through 10 citations from sample answers and each cited page actually contains the claim being cited
- [ ] Time-sensitive answers (deadlines, tuition) display a freshness/last-verified date
- [ ] I've asked a question the system cannot answer from its knowledge base and watched it refuse cleanly rather than hallucinate
- [ ] Faithfulness score on the eval set is ≥95% and citation accuracy is ≥98%
- [ ] Langfuse Cloud dashboard shows traces for every generation — I can click a trace and see the retrieved chunks, prompt, model output, and latency
- [ ] I've personally reviewed 20 generated answers and found zero fabricated facts and zero fabricated citations

### Phase 5 — API service (Week 8)
- FastAPI with SSE streaming
- **Cookie-based sessions, CSRF protection, 14-day retention** (new in v3)
- Tenant API keys for server-to-server
- OpenAPI spec, Schemathesis contract tests
- Tenant isolation test as blocking CI check

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

### Phase 6 — Frontends (Weeks 9-10)
- **TUI (week 9):** Textual-based, internal tool, API-key auth (no cookies needed for TUI — it uses the server-to-server path with a dev API key)
- **Flutter web-embed widget (week 10):** iframe-based per Option B, widget loader script, postMessage protocol, CDN deployment
- Shared OpenAPI-generated clients

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
- [ ] The widget's Flutter bundle is served from the CDN with proper caching (verified by the engineer showing cache-hit headers)
- [ ] `flutter analyze` shows zero warnings in CI

### Phase 7 — Operational maturity (Week 11)
- Scheduled recrawl
- Monitoring, alerts
- **Nightly purge jobs for expired conversations and sessions** (new in v3)
- Chaos tests including embedder-down scenario (must gracefully degrade, not hard-fail)

#### CEO checklist
- [ ] I can see the monitoring dashboard: query volume, p50/p95/p99 latency, refusal rate, thumbs-down rate, cost per query
- [ ] Alerts are wired up to a channel I receive (Slack, email, etc.) — I've seen a test alert fire
- [ ] The recrawl schedule has run at least once unattended, and I can see the updated `last_crawled` timestamps in the documents table
- [ ] The nightly purge job has run and removed expired conversations — I've seen the delete count in logs
- [ ] The chaos test demonstration: engineer kills the embedder mid-conversation, and the system returns a graceful error rather than crashing
- [ ] The first weekly automated report has been generated — top queries, lowest-rated responses, stalest content
- [ ] A content-quality review queue exists somewhere I can check, showing coverage gaps and negative feedback for human review

### Phase 8 — Second tenant (Week 12)
- Onboard second university
- Full eval run across both
- <1 engineering day onboarding target

#### CEO checklist
- [ ] The second university is fully ingested and serving queries through the widget
- [ ] The engineer logged their onboarding time and it was under one engineering day — if over, I've reviewed what dragged and signed off on a fix plan
- [ ] A written onboarding runbook exists and I can follow it at a high level without needing to ask questions
- [ ] Cross-tenant eval report shows both universities meet Phase 2 retrieval thresholds (Recall@10 ≥ 85%, MRR@10 ≥ 0.6)
- [ ] I've queried University A through its widget and confirmed I see zero University B content (and vice versa) — live cross-tenant smoke test, not just the automated test
- [ ] Zero code changes were required to onboard tenant 2 — only config/data. Engineer can point at the commit history to confirm this
- [ ] The platform is ready to demo to prospective university customers — I've done a dry run

---

## Dev environment (new section given constraint #2)

Since the embedder runs on the engineer's machine during development, local setup has to be clean.

**`docker-compose.yml`:**
```yaml
services:
  postgres:
    image: postgres:18
    environment: [...]
    volumes: [postgres-data:/var/lib/postgresql/data]
    ports: ["5432:5432"]

  embedder:
    image: ghcr.io/huggingface/text-embeddings-inference:latest  # or cpu-variant
    command: ["--model-id", "Qwen/Qwen3-Embedding-0.6B", "--port", "8080"]
    ports: ["8080:8080"]
    # GPU access if available; CPU-only fallback documented
    
  # API and ingestion run on host (hot reload), not in compose
```

**`make dev` target:**
```
make dev          # spins up postgres + embedder, runs api with uvicorn --reload
make ingest       # runs ingestion against fixture university
make test         # full test suite
make eval         # runs eval harness against golden set
```

**Hardware guidance for engineers:**
- Apple Silicon M2+ or equivalent with ≥16GB RAM runs `Qwen3-Embedding-0.6B` comfortably on CPU
- 4B-parameter variant needs GPU or substantial RAM; document as "dev uses 0.6B, prod uses {winner}" if bake-off picks differently
- If the dev machine can't run the prod model, use `RemoteEmbedder` pointed at a shared dev embedding service on GCP

---

## Open items for the senior engineer

1. **Embedding model bake-off**: you own it. Pick date within Phase 1. Document methodology, results, decision in an ADR.
2. **Widget domain/cookie strategy**: confirm we can register `*.ourproduct.com` and set up `api.` + `widget.` subdomains for shared cookie scope. If not, we need a cross-origin token exchange instead of cookies; that's a meaningful protocol change.
3. **Cloud Run sidecar pattern for embedder**: verify Cloud Run's multi-container support handles our sizing. If not, embedder becomes a separate Cloud Run service from day one (same `Embedder` interface, `RemoteEmbedder` impl).
4. **Postgres 18 availability on Cloud SQL**: confirm GA in our region. If it's still preview/beta, decide: wait, use preview, or drop to PG17 with documented upgrade path.
5. **pgvector version on managed Postgres**: Cloud SQL lags on pgvector releases. We need ≥0.8 for iterative scan with filters. If Cloud SQL is behind, we either self-host PG on a Cloud Run VM or use AlloyDB.

---

## What's unchanged and non-negotiable

- Multi-tenancy from day one; tenant isolation tests as hard CI blocker
- UUIDs everywhere (PG18's native `uuidv7()` makes this free)
- VectorStore + Embedder abstractions; no direct pgvector or model calls outside the implementations
- Testing at every phase: unit (coverage thresholds), integration (testcontainers), contract (Schemathesis), eval (golden set), E2E (one per phase)
- Evaluation before optimization: retrieval metrics gate every phase

Ship it.