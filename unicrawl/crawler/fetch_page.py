import asyncio

import httpx


EMPTY_HTML_RETRY_STATUSES = {202}
EMPTY_HTML_RETRY_DELAYS_SECONDS = (0.5, 1.0, 2.0)


def _should_retry_empty_html(status_code: int, content_type: str, html: str) -> bool:
    return status_code in EMPTY_HTML_RETRY_STATUSES and "text/html" in content_type.lower() and not html.strip()


async def fetch_page(client: httpx.AsyncClient, url: str) -> tuple[int, str, str, str] | None:
    for attempt_index in range(len(EMPTY_HTML_RETRY_DELAYS_SECONDS) + 1):
        try:
            response = await client.get(url)
        except httpx.HTTPError:
            return None

        content_type = response.headers.get("content-type", "")
        html = response.text
        if not _should_retry_empty_html(response.status_code, content_type, html):
            return response.status_code, content_type, html, str(response.url)

        if attempt_index >= len(EMPTY_HTML_RETRY_DELAYS_SECONDS):
            return response.status_code, content_type, html, str(response.url)

        await asyncio.sleep(EMPTY_HTML_RETRY_DELAYS_SECONDS[attempt_index])

    return None
