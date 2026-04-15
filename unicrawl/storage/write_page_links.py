import json
from pathlib import Path

from unicrawl.storage.url_hash_for_normalized_url import url_hash_for_normalized_url


def write_page_links(
    base_output_dir: Path,
    normalized_url: str,
    outgoing_links: list[str],
    *,
    redirect_to: str | None = None,
) -> None:
    url_hash = url_hash_for_normalized_url(normalized_url)
    page_dir = base_output_dir / "pages" / "by-url-hash" / url_hash
    page_dir.mkdir(parents=True, exist_ok=True)
    links_path = page_dir / "outgoing-links.json"
    edges: list[dict[str, str]] = []
    if redirect_to is not None:
        edges.append({"target": redirect_to, "type": "redirect"})
    for target in outgoing_links:
        edges.append({"target": target, "type": "link"})
    links_path.write_text(
        json.dumps(
            {
                "source_normalized_url": normalized_url,
                "outgoing_links": outgoing_links,
                "redirect_to": redirect_to,
                "edges": edges,
            },
            indent=2,
        ),
        encoding="utf-8",
    )