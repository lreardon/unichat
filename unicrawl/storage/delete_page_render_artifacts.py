from pathlib import Path

from unicrawl.storage.url_hash_for_normalized_url import url_hash_for_normalized_url


def delete_page_render_artifacts(base_output_dir: Path, normalized_url: str) -> None:
    url_hash = url_hash_for_normalized_url(normalized_url)
    page_dir = base_output_dir / "pages" / "by-url-hash" / url_hash
    for artifact_name in ("page.html", "outgoing-links.json", "metadata.json", "normalized-url.txt"):
        artifact_path = page_dir / artifact_name
        if artifact_path.exists():
            artifact_path.unlink()