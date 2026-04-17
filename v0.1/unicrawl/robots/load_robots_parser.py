from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx


async def load_robots_parser(root_url: str, timeout_seconds: float = 10.0) -> RobotFileParser | None:
    host = (urlparse(root_url).hostname or "").lower()
    if not host:
        return None

    robots_url = f"https://{host}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            response = await client.get(robots_url)
    except httpx.HTTPError:
        return None

    if response.status_code >= 400:
        return None

    parser.parse(response.text.splitlines())
    return parser
