"""Sitemap discovery and parsing.

Fetches robots.txt → extracts sitemap URLs → parses sitemap XML (including indexes)
→ returns deduplicated list of page URLs.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


async def discover_urls(
    domain: str,
    *,
    client: httpx.AsyncClient | None = None,
    user_agent: str = "UniChatBot/0.2",
) -> list[str]:
    """Discover all page URLs for a domain via sitemaps.

    1. Fetch robots.txt, extract Sitemap: directives.
    2. Fetch each sitemap (handles sitemap index files recursively).
    3. Return deduplicated URL list.
    """
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=30.0, headers={"User-Agent": user_agent})

    try:
        sitemap_urls = await _get_sitemap_urls_from_robots(client, domain)
        if not sitemap_urls:
            sitemap_urls = [f"https://{domain}/sitemap.xml"]

        all_page_urls: list[str] = []
        seen: set[str] = set()
        for sitemap_url in sitemap_urls:
            await _parse_sitemap(client, sitemap_url, all_page_urls, seen, depth=0)

        return all_page_urls
    finally:
        if own_client:
            await client.aclose()


async def _get_sitemap_urls_from_robots(
    client: httpx.AsyncClient, domain: str
) -> list[str]:
    """Extract Sitemap: directives from robots.txt."""
    try:
        resp = await client.get(f"https://{domain}/robots.txt")
        if resp.status_code != 200:
            return []
    except httpx.HTTPError:
        return []

    sitemaps: list[str] = []
    for line in resp.text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            url = stripped.split(":", 1)[1].strip()
            if url:
                sitemaps.append(url)
    return sitemaps


async def _parse_sitemap(
    client: httpx.AsyncClient,
    url: str,
    out: list[str],
    seen: set[str],
    depth: int,
) -> None:
    """Parse a sitemap or sitemap index XML. Recurse into indexes up to depth 3."""
    if depth > 3:
        return

    try:
        resp = await client.get(url)
        if resp.status_code != 200:
            return
    except httpx.HTTPError:
        return

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return

    tag = _strip_ns(root.tag)

    if tag == "sitemapindex":
        for sitemap_el in root.findall(f"{{{SITEMAP_NS}}}sitemap"):
            loc_el = sitemap_el.find(f"{{{SITEMAP_NS}}}loc")
            if loc_el is not None and loc_el.text:
                await _parse_sitemap(client, loc_el.text.strip(), out, seen, depth + 1)
    elif tag == "urlset":
        for url_el in root.findall(f"{{{SITEMAP_NS}}}url"):
            loc_el = url_el.find(f"{{{SITEMAP_NS}}}loc")
            if loc_el is not None and loc_el.text:
                page_url = loc_el.text.strip()
                if page_url not in seen:
                    seen.add(page_url)
                    out.append(page_url)


def _strip_ns(tag: str) -> str:
    """Remove XML namespace prefix from tag."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag
