from urllib.parse import urlparse


def should_skip_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return True

    blocked_suffixes = (
        ".pdf",
        ".zip",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".svg",
        ".webp",
        ".mp4",
        ".mp3",
        ".avi",
        ".mov",
        ".dmg",
        ".exe",
    )
    return parsed.path.lower().endswith(blocked_suffixes)
