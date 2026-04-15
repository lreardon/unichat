from pathlib import Path

from unicrawl.storage.read_persisted_page_links import read_persisted_page_links
from unicrawl.storage.url_hash_for_normalized_url import url_hash_for_normalized_url


def is_page_persisted(base_output_dir: Path, normalized_url: str) -> bool:
    url_hash = url_hash_for_normalized_url(normalized_url)
    page_dir = base_output_dir / "pages" / "by-url-hash" / url_hash
    page_html_path = page_dir / "page.html"
    if page_html_path.exists() and page_html_path.stat().st_size > 0:
        return True

    persisted_edges = read_persisted_page_links(base_output_dir, normalized_url)
    if persisted_edges is None:
        return False
    return any(edge_type == "redirect" for edge_type, _ in persisted_edges)
