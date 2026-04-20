from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

@dataclass(frozen=True)
class CrawlScope:
    """Per-university crawl scope configuration.

    allowed_subdomains: hostnames to crawl.
        e.g. ["www.unsw.edu.au"]
        If empty, all subdomains of the base domain are allowed.
    allowed_paths: URL path prefixes to crawl.
        e.g. ["/engineering", "/science", "/staff"]
        If empty, all paths on allowed hosts are crawled.
        When set, only URLs whose path starts with one of these prefixes
        (plus their children) are in scope.
    outside_depth: link-hops outside scope to follow.
        0 = strict scope only.
        1 = follow links one hop outside for additional content.
    """

    allowed_subdomains: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    outside_depth: int = 0

    @classmethod
    def from_university_config(
        cls, config: dict[str, Any], domain: str
    ) -> CrawlScope:
        """Build CrawlScope from universities.config JSONB."""
        subdomains = config.get("allowed_subdomains", [])
        paths = config.get("allowed_paths", [])
        outside_depth = config.get("outside_depth", 0)
        return cls(
            allowed_subdomains=subdomains,
            allowed_paths=paths,
            outside_depth=outside_depth,
        )

    def is_in_scope(self, url: str, domain: str) -> bool:
        """Check if a URL is within the crawl scope."""
        parsed = urlparse(url)
        host = parsed.netloc

        # Check host
        if self.allowed_subdomains:
            if host not in self.allowed_subdomains:
                return False
        else:
            if host != domain and not host.endswith(f".{domain}"):
                return False

        # Check path prefix
        if self.allowed_paths:
            path = parsed.path.rstrip("/")
            return any(
                path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/")
                for prefix in self.allowed_paths
            )

        return True

    def is_under_base_domain(self, url: str, domain: str) -> bool:
        """Check if URL is under the base domain at all."""
        host = urlparse(url).netloc
        return host == domain or host.endswith(f".{domain}")

    def seed_urls(self, domain: str) -> list[str]:
        """Generate seed URLs from the scope config."""
        hosts = self.allowed_subdomains or [domain]
        if self.allowed_paths:
            return [
                f"https://{host}{path}"
                for host in hosts
                for path in self.allowed_paths
            ]
        return [f"https://{host}/" for host in hosts]

__all__ = ["CrawlScope"]
