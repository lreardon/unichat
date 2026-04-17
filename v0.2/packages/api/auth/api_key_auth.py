import hashlib
import uuid

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.models import University


class InvalidAPIKeyError(Exception):
    """Raised when the provided API key does not match any university."""

    def __init__(self) -> None:
        super().__init__("Invalid or missing API key")


async def authenticate_api_key(request: Request, db: AsyncSession) -> uuid.UUID:
    """Authenticate a server-to-server request via Bearer token.

    Returns the university_id for the matched API key.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise InvalidAPIKeyError

    raw_key = auth_header[7:]
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    result = await db.execute(
        select(University.id).where(University.api_key_hash == key_hash)
    )
    university_id = result.scalar_one_or_none()

    if university_id is None:
        raise InvalidAPIKeyError

    return university_id
