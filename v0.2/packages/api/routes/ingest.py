import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from packages.api.auth.api_key_auth import authenticate_api_key
from packages.api.dependencies import get_db_session
from packages.api.error_models import ErrorResponse

router = APIRouter(prefix="/ingest", tags=["ingest"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class IngestRequest(BaseModel):
    url: str
    title: str | None = None


class IngestResponse(BaseModel):
    document_id: uuid.UUID
    status: str


@router.post(
    "",
    response_model=IngestResponse,
    responses={401: {"model": ErrorResponse}},
)
async def trigger_ingest(
    body: IngestRequest,
    request: Request,
    db: DbSession,
) -> IngestResponse:
    university_id = await authenticate_api_key(request, db)

    # TODO: Phase 1 — invoke crawl + chunk + embed pipeline
    _ = university_id
    _ = body

    placeholder_id = uuid.uuid4()
    return IngestResponse(
        document_id=placeholder_id,
        status="queued",
    )
