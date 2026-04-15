from pathlib import Path

from unicrawl.storage.url_hash_for_normalized_url import url_hash_for_normalized_url


def read_persisted_page_html(base_output_dir: Path, normalized_url: str) -> str | None:
    url_hash = url_hash_for_normalized_url(normalized_url)
    page_html_path = base_output_dir / "pages" / "by-url-hash" / url_hash / "page.html"
    if not page_html_path.exists():
        return None
    if page_html_path.stat().st_size == 0:
        return None

    html = page_html_path.read_text(encoding="utf-8", errors="ignore")
    if not html.strip():
        return None
    return html
