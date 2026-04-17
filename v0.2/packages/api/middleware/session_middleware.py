import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.core.config import Settings
from packages.core.models import Conversation, Session
from packages.core.session_token import generate_session_token, hash_token


class SessionData:
    """Resolved session state attached to request."""

    def __init__(
        self,
        *,
        session_id: uuid.UUID,
        university_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
    ) -> None:
        self.session_id = session_id
        self.university_id = university_id
        self.conversation_id = conversation_id


async def resolve_session(
    request: Request,
    response: Response,
    db: AsyncSession,
    settings: Settings,
    university_id: uuid.UUID,
) -> SessionData:
    """Resolve or create a session from the request cookie.

    Returns SessionData. Sets cookie on response if new session created.
    """
    cookie_value = request.cookies.get(settings.session_cookie_name)

    if cookie_value:
        return await _load_existing_session(cookie_value, db, settings)

    return await _create_new_session(response, db, settings, university_id)


async def _load_existing_session(
    cookie_value: str,
    db: AsyncSession,
    settings: Settings,
) -> SessionData:
    token_hash_value = hash_token(cookie_value)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(Session).where(
            Session.token_hash == token_hash_value,
            Session.expires_at > now,
        )
    )
    session_row = result.scalar_one_or_none()

    if session_row is None:
        raise SessionNotFoundError(token_hash=token_hash_value)

    # Rolling window: extend expiry on each use
    new_expires = now + timedelta(days=settings.session_ttl_days)
    await db.execute(
        update(Session)
        .where(Session.id == session_row.id)
        .values(last_seen_at=now, expires_at=new_expires)
    )
    await db.commit()

    return SessionData(
        session_id=session_row.id,
        university_id=session_row.university_id,
        conversation_id=session_row.conversation_id,
    )


async def _create_new_session(
    response: Response,
    db: AsyncSession,
    settings: Settings,
    university_id: uuid.UUID,
) -> SessionData:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=settings.session_ttl_days)

    # Create conversation — expires_at is GENERATED ALWAYS from created_at,
    # so we only set university_id
    conversation = Conversation(university_id=university_id)
    db.add(conversation)
    await db.flush()

    # Create session
    raw_token = generate_session_token()
    session_row = Session(
        university_id=university_id,
        token_hash=hash_token(raw_token),
        conversation_id=conversation.id,
        expires_at=expires,
    )
    db.add(session_row)
    await db.commit()

    # Set session cookie
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=settings.session_ttl_days * 86400,
    )

    # Set CSRF double-submit cookie
    csrf_token = generate_session_token()
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        httponly=False,
        secure=True,
        samesite="none",
        path="/",
        max_age=settings.session_ttl_days * 86400,
    )

    return SessionData(
        session_id=session_row.id,
        university_id=university_id,
        conversation_id=conversation.id,
    )


class SessionNotFoundError(Exception):
    """Raised when a session cookie maps to no valid session row."""

    def __init__(self, *, token_hash: str) -> None:
        self.token_hash = token_hash
        super().__init__(f"No active session for token_hash={token_hash[:8]}...")
