import json
from pathlib import Path

from unicrawl.storage.url_hash_for_normalized_url import url_hash_for_normalized_url


def read_persisted_page_links(base_output_dir: Path, normalized_url: str) -> list[tuple[str, str]] | None:
    url_hash = url_hash_for_normalized_url(normalized_url)
    links_path = base_output_dir / "pages" / "by-url-hash" / url_hash / "outgoing-links.json"
    if not links_path.exists():
        return None

    try:
        payload = json.loads(links_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    edges = payload.get("edges")
    if isinstance(edges, list):
        parsed_edges: list[tuple[str, str]] = []
        for entry in edges:
            if not isinstance(entry, dict):
                return None
            target = entry.get("target")
            edge_type = entry.get("type")
            if not isinstance(target, str) or edge_type not in {"link", "redirect"}:
                return None
            parsed_edges.append((edge_type, target))
        return parsed_edges

    outgoing_links = payload.get("outgoing_links")
    if not isinstance(outgoing_links, list):
        return None

    parsed_edges = []
    redirect_to = payload.get("redirect_to")
    if isinstance(redirect_to, str):
        parsed_edges.append(("redirect", redirect_to))
    for entry in outgoing_links:
        if not isinstance(entry, str):
            return None
        parsed_edges.append(("link", entry))
    return parsed_edges