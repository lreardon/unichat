import posixpath
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    hostname = (parsed.hostname or "").lower()

    if not hostname:
        return ""

    netloc = hostname
    if parsed.port and not ((scheme == "https" and parsed.port == 443) or (scheme == "http" and parsed.port == 80)):
        netloc = f"{hostname}:{parsed.port}"

    path = parsed.path or "/"
    normalized_path = posixpath.normpath(path)
    if path.endswith("/") and not normalized_path.endswith("/"):
        normalized_path = f"{normalized_path}/"
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"

    query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    normalized_query = urlencode(sorted(query_pairs), doseq=True)

    return urlunparse((scheme, netloc, normalized_path, "", normalized_query, ""))
