import uuid

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from packages.api.dependencies import get_db_session, get_settings
from packages.api.middleware.csrf_middleware import validate_csrf
from packages.api.middleware.session_middleware import SessionData, resolve_session
from packages.core.config import Settings
from packages.core.models import Message

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    university_id: uuid.UUID
    message: str


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    reply: str


@router.post("", response_model=ChatResponse)
async def send_message(
    body: ChatRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ChatResponse:
    validate_csrf(request, settings)

    session_data: SessionData = await resolve_session(
        request=request,
        response=response,
        db=db,
        settings=settings,
        university_id=body.university_id,
    )

    # Store user message
    user_msg = Message(
        conversation_id=session_data.conversation_id,
        role="user",
        content=body.message,
    )
    db.add(user_msg)
    await db.flush()

    # TODO: Phase 4 — invoke retrieval + generation pipeline
    reply_text = "This is a placeholder response. Generation pipeline not yet implemented."

    assistant_msg = Message(
        conversation_id=session_data.conversation_id,
        role="assistant",
        content=reply_text,
    )
    db.add(assistant_msg)
    await db.commit()

    return ChatResponse(
        conversation_id=session_data.conversation_id,
        message_id=assistant_msg.id,
        reply=reply_text,
    )
