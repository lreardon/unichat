# unicrawl

Minimal crawler for collecting HTML pages from a university root URL.

## Usage

```bash
unicrawl https://www.unsw.edu.au/
unicrawl https://www.unsw.edu.au/ --force
unicrawl graph https://www.unsw.edu.au/
```

- `--force` bypasses robots.txt allow/disallow checks.
- `unicrawl graph <root-url>` regenerates `link-graph.json` and `link-graph-viewer.html`
  from the existing persisted crawl output without crawling again.
- Crawling is completion-oriented (no page-count cap).
- Existing persisted pages are skipped by default (`skip_existing_pages=True`), but their
  stored outgoing links are reused to continue traversal without reparsing HTML on every rerun.
- Redirects are persisted as explicit `redirect` edges, so redirected content is not treated as
  if it belonged to the originally requested URL.
- Resume is default-on: if `frontier-checkpoint.json` exists, the crawler restores queue/visited
  state automatically and continues.
- Frontier checkpoint state is persisted after every processed batch.
- Output is written to `./universities/<university-name>/`.
- Each saved page also stores its normalized outgoing links, and each crawl writes
  `link-graph.json` plus `link-graph-viewer.html` for interactive exploration.

## Concurrency

- Throughput-optimized worker-pool autoscaling.
  The crawler starts from `initial_pool_size`, samples throughput,
  and adjusts concurrency every `autoscale_monitor_interval_seconds`.
  If throughput increased versus the previous interval, it keeps moving in
  the same direction; if throughput decreased, it reverses direction.

Default autoscaling controls in `CrawlConfig`:

- `initial_pool_size=32`
- `autoscale_monitor_interval_seconds=10.0`

Autoscaling is throughput-seeking, not memory-threshold-seeking.

## Output Layout

```text
universities/
  <university-name>/
    pages/
      by-url-hash/
        <hash>/
          page.html
          metadata.json
          normalized-url.txt
          outgoing-links.json
    frontier-checkpoint.json
    crawl-manifest.json
    link-graph.json
    link-graph-viewer.html
```
