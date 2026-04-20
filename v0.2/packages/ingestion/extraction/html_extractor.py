"""HTML content extraction using trafilatura with BeautifulSoup fallback."""

from __future__ import annotations

import trafilatura
from bs4 import BeautifulSoup


def extract_text(html: str) -> str:
    """Extract clean text from HTML using trafilatura.

    Uses favor_precision=True for aggressive boilerplate removal.
    Falls back to BeautifulSoup body text if trafilatura returns nothing.
    """
    result = trafilatura.extract(
        html,
        favor_precision=True,
        include_tables=True,
        include_links=False,
        include_images=False,
    )
    if result:
        return result

    soup = BeautifulSoup(html, "lxml")
    body = soup.body
    if body:
        return body.get_text(separator="\n", strip=True)
    return soup.get_text(separator="\n", strip=True)


def extract_title(html: str) -> str:
    """Extract page title from HTML."""
    meta = trafilatura.extract_metadata(html)
    if meta and meta.title:
        return meta.title

    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("title")
    if title_tag and title_tag.string:
        return title_tag.string.strip()

    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)

    return ""
