# ADR 0002: Embedding Model Selection

## Status
Accepted (2026-04-17)

## Context
We need an embedding model for the vector search component of the university knowledge base.
Requirements:
- Open-weight with permissive license (Apache 2.0, MIT)
- Strong retrieval quality on MTEB benchmarks
- Reasonable dimension size (affects storage and HNSW index performance)
- Can run locally on CPU for dev (Apple Silicon M2+ with 16GB RAM)
- Self-hosted via TEI sidecar in docker-compose

## Candidates Evaluated
1. **Qwen3-Embedding-0.6B** — 1024-dim, Apache 2.0, top MTEB retrieval scores for its size class
2. **Qwen3-Embedding-4B** — 2560-dim, Apache 2.0, higher quality but 4x larger model
3. **BGE-M3** — 1024-dim, MIT, strong multilingual, slightly lower English retrieval quality

## Decision
**Qwen3-Embedding-0.6B** (1024 dimensions)

## Rationale
- Best retrieval quality per parameter on MTEB English benchmarks among open-weight models at decision time (April 2026)
- 1024-dim is a practical sweet spot: strong recall without the storage/index cost of 2560+ dims
- 0.6B parameters runs comfortably on Apple Silicon CPU (dev) and modest GPU (prod)
- Apache 2.0 license — no commercial restrictions
- Supported by HuggingFace TEI out of the box, which we use as our embedding sidecar
- The 4B variant showed ~2% higher Recall@10 but 6x inference latency and much larger index — not justified for v1

## Consequences
- `vector(1024)` column type locked in migration 001. Changing requires full re-embed of all chunks and entities.
- Embedding dimension set in `packages/core/config.py` as `embedding_dimension = 1024`
- TEI sidecar in docker-compose configured with `--model-id Qwen/Qwen3-Embedding-0.6B`
- If retrieval quality proves insufficient in Phase 2 eval, we upgrade to the 4B variant (requires re-embed + migration to `vector(2560)`)
