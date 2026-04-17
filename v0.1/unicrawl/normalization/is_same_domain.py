from urllib.parse import urlparse


def is_same_domain(root_url: str, candidate_url: str) -> bool:
    root_host = (urlparse(root_url).hostname or "").lower()
    candidate_host = (urlparse(candidate_url).hostname or "").lower()

    if not root_host or not candidate_host:
        return False

    return candidate_host == root_host or candidate_host.endswith(f".{root_host}")
