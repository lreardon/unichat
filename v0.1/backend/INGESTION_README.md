# Ingestion (Current Behavior)

This is the exact flow used by `POST /ingest` today.

## 1) Entry point

- API route: `POST /ingest`
- Handler calls: `ingest_curated(session, curated_dir_override)`
- Source index default: `<CURATED_DIR>/index.json` from env (default `universities/unsw-edu-au/domains/index.json`)
- Request `curated_dir` override still supported: pass either a directory (expects `index.json` inside) or a direct `.json` index path

## 2) Corpus loading

Input must provide a curated index JSON file.
For each entry:

- Read `path` (or `filename`) and `url`
- Load HTML from `<index_parent_dir>/<path>`
- Compute `document_id = sha1(url)[:12]`
- Infer `domain` from first path segment
- Extract `title` from `<title>` (fallback `<h1>`, else `Untitled`)

## 3) Text extraction

Sections are extracted from `main`/`article`/`body` with BeautifulSoup.

- Removed tags before extraction: `script`, `style`, `noscript`, `svg`, `header`, `footer`, `nav`, `aside`, `form`
- Content nodes considered: `h1..h4`, `p`, `li`
- Heading starts a new section; paragraph/list items are appended as section text

## 4) Chunking

Chunker: sentence-aware split per section (syntok) with word-boundary fallback for oversized sentences.

- Defaults from settings:
  - `chunk_size_chars = 1400`
  - `chunk_overlap_chars = 250`
- Chunks are plain text spans, trimmed
- `chunk_id` format: `<document_id>:<position>` where `position` is 0-based in that document

## 5) Stored fields

`documents` table stores:
- `document_id`, `url`, `path`, `domain`, `title`

`chunks` table stores:
- `chunk_id`, `document_id`, `domain`, `url`, `heading`, `text`, `position`, `embedding`

Embedding is generated per chunk text during ingest.

## 6) Upsert + cleanup behavior

- Documents/chunks are upserted via `session.merge(...)`
- For each ingested document, stale chunk rows are deleted if their `chunk_id` is no longer present

## 7) Context model (important)

What is preserved:
- Document-level metadata (`url`, `domain`, `title`)
- Section heading (`heading`)
- Chunk order (`position`)

What is not explicitly stored:
- No `prev_chunk_id` / `next_chunk_id`
- No precomputed surrounding-window text
- No parent section hierarchy beyond one `heading` string

So your suspicion is plausible: if extracted sections are short, chunk text can be small, and retrieval currently treats chunks mostly independently.

## 8) Quick DB checks

Use these to inspect chunk size distribution and heading/context quality:

```sql
-- size distribution
select
  count(*) as chunks,
  round(avg(length(text))) as avg_chars,
  percentile_cont(0.5) within group (order by length(text)) as p50,
  percentile_cont(0.9) within group (order by length(text)) as p90,
  min(length(text)) as min_chars,
  max(length(text)) as max_chars
from chunks;

-- shortest chunks
select chunk_id, domain, heading, length(text) as chars
from chunks
order by chars asc
limit 30;

-- per-document chunk counts and average size
select document_id, count(*) as chunk_count, round(avg(length(text))) as avg_chars
from chunks
group by document_id
order by chunk_count desc
limit 30;
```
