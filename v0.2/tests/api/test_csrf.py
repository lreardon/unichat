import pytest
from starlette.testclient import TestClient as StarletteRequest
from unittest.mock import MagicMock

from fastapi import Request

from packages.api.middleware.csrf_middleware import CSRFValidationError, validate_csrf
from packages.core.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings()


def _make_request(*, method: str, cookies: dict, headers: dict) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    request = Request(scope)
    request._cookies = cookies
    return request


def test_safe_methods_skip_csrf(settings: Settings) -> None:
    for method in ("GET", "HEAD", "OPTIONS"):
        request = _make_request(method=method, cookies={}, headers={})
        validate_csrf(request, settings)  # Should not raise


def test_post_without_csrf_cookie_raises(settings: Settings) -> None:
    request = _make_request(method="POST", cookies={}, headers={"X-CSRF-Token": "abc"})
    with pytest.raises(CSRFValidationError, match="Missing CSRF cookie"):
        validate_csrf(request, settings)


def test_post_without_csrf_header_raises(settings: Settings) -> None:
    request = _make_request(
        method="POST",
        cookies={"kb_csrf": "token123"},
        headers={},
    )
    with pytest.raises(CSRFValidationError, match="Missing X-CSRF-Token header"):
        validate_csrf(request, settings)


def test_post_with_mismatched_tokens_raises(settings: Settings) -> None:
    request = _make_request(
        method="POST",
        cookies={"kb_csrf": "token-a"},
        headers={"X-CSRF-Token": "token-b"},
    )
    with pytest.raises(CSRFValidationError, match="CSRF token mismatch"):
        validate_csrf(request, settings)


def test_post_with_matching_tokens_passes(settings: Settings) -> None:
    request = _make_request(
        method="POST",
        cookies={"kb_csrf": "valid-token"},
        headers={"X-CSRF-Token": "valid-token"},
    )
    validate_csrf(request, settings)  # Should not raise
