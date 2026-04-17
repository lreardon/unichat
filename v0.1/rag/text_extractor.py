from __future__ import annotations

import re
from bs4 import BeautifulSoup


_WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return _clean_text(soup.title.string)
    h1 = soup.find("h1")
    if h1:
        return _clean_text(h1.get_text(" ", strip=True))
    return "Untitled"


def extract_sections(html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")

    for tag_name in ("script", "style", "noscript", "svg", "header", "footer", "nav", "aside", "form"):
        for node in soup.find_all(tag_name):
            node.decompose()

    container = soup.find("main") or soup.find("article") or soup.body or soup

    sections: list[tuple[str, str]] = []
    current_heading = "General"
    current_lines: list[str] = []

    for node in container.find_all(["h1", "h2", "h3", "h4", "p", "li"], recursive=True):
        text = _clean_text(node.get_text(" ", strip=True))
        if not text:
            continue

        if node.name in {"h1", "h2", "h3", "h4"}:
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines)))
                current_lines = []
            current_heading = text
            continue

        current_lines.append(text)

    if current_lines:
        sections.append((current_heading, "\n".join(current_lines)))

    if not sections:
        raw_text = _clean_text(container.get_text(" ", strip=True))
        if raw_text:
            sections.append(("General", raw_text))

    return sections
