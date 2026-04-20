"""Tests for sitemap XML parsing."""

import httpx
import pytest

from packages.ingestion.crawler.sitemap import discover_urls

SAMPLE_ROBOTS_TXT = """\
User-agent: *
Disallow: /admin/

Sitemap: https://example.edu/sitemap.xml
Sitemap: https://example.edu/sitemap-news.xml
"""

SAMPLE_SITEMAP_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://example.edu/</loc></url>
    <url><loc>https://example.edu/about</loc></url>
    <url><loc>https://example.edu/programs</loc></url>
    <url><loc>https://example.edu/faculty</loc></url>
</urlset>
"""

SAMPLE_SITEMAP_INDEX = """\
<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://example.edu/sitemap-main.xml</loc></sitemap>
    <sitemap><loc>https://example.edu/sitemap-faculty.xml</loc></sitemap>
</sitemapindex>
"""

SAMPLE_FACULTY_SITEMAP = """\
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://example.edu/faculty/chen</loc></url>
    <url><loc>https://example.edu/faculty/williams</loc></url>
</urlset>
"""


@pytest.fixture
def mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=SAMPLE_ROBOTS_TXT)
        elif url.endswith(("/sitemap.xml", "/sitemap-news.xml", "/sitemap-main.xml")):
            return httpx.Response(200, text=SAMPLE_SITEMAP_XML)
        elif url.endswith("/sitemap-faculty.xml"):
            return httpx.Response(200, text=SAMPLE_FACULTY_SITEMAP)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_discover_urls_from_sitemap(mock_transport: httpx.MockTransport) -> None:
    async with httpx.AsyncClient(transport=mock_transport) as client:
        urls = await discover_urls("example.edu", client=client)

    assert len(urls) >= 4
    assert "https://example.edu/" in urls
    assert "https://example.edu/about" in urls
    assert "https://example.edu/faculty" in urls


async def test_deduplicates_urls(mock_transport: httpx.MockTransport) -> None:
    async with httpx.AsyncClient(transport=mock_transport) as client:
        urls = await discover_urls("example.edu", client=client)

    # Same URL shouldn't appear twice even if in multiple sitemaps
    assert len(urls) == len(set(urls))


async def test_handles_sitemap_index() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="Sitemap: https://example.edu/sitemap-index.xml")
        elif url.endswith("/sitemap-index.xml"):
            return httpx.Response(200, text=SAMPLE_SITEMAP_INDEX)
        elif url.endswith("/sitemap-main.xml"):
            return httpx.Response(200, text=SAMPLE_SITEMAP_XML)
        elif url.endswith("/sitemap-faculty.xml"):
            return httpx.Response(200, text=SAMPLE_FACULTY_SITEMAP)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        urls = await discover_urls("example.edu", client=client)

    assert "https://example.edu/faculty/chen" in urls
    assert "https://example.edu/" in urls


async def test_handles_missing_robots_txt() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/robots.txt"):
            return httpx.Response(404)
        elif url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=SAMPLE_SITEMAP_XML)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        urls = await discover_urls("example.edu", client=client)

    # Should fall back to /sitemap.xml
    assert len(urls) >= 4
