from fastapi import Request

from packages.core.config import Settings

# Safe methods that do not require CSRF validation
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class CSRFValidationError(Exception):
    """Raised when CSRF double-submit validation fails."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def validate_csrf(request: Request, settings: Settings) -> None:
    """Validate CSRF double-submit token for state-changing requests.

    Compares the csrf cookie value against the X-CSRF-Token header.
    Only applies to non-safe HTTP methods (POST, PUT, DELETE, PATCH).
    """
    if request.method in _SAFE_METHODS:
        return

    cookie_value = request.cookies.get(settings.csrf_cookie_name)
    header_value = request.headers.get("X-CSRF-Token")

    if not cookie_value:
        raise CSRFValidationError("Missing CSRF cookie")

    if not header_value:
        raise CSRFValidationError("Missing X-CSRF-Token header")

    if cookie_value != header_value:
        raise CSRFValidationError("CSRF token mismatch")
