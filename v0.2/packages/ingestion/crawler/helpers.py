from urllib.parse import urlparse, urlunparse

def normalize_url(url: str) -> str | None:
    """Normalize URL for dedupe and queue stability."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None

    netloc = parsed.netloc.lower()
    if not netloc:
        return None

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=netloc,
        path=path,
        fragment="",
    )
    return urlunparse(normalized)
