import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from packages.api.auth.api_key_auth import authenticate_api_key
from packages.api.dependencies import (
    get_db_session,
    get_embedder,
    get_session_factory,
    get_settings,
    get_vector_store,
)
from packages.api.error_models import ErrorResponse
from packages.ingestion.config import IngestionSettings
from packages.ingestion.pipeline import IngestPipeline

router = APIRouter(prefix="/ingest", tags=["ingest"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class IngestRequest(BaseModel):
    url: str
    title: str | None = None


class IngestResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    pages_crawled: int = 0
    chunks_created: int = 0


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

    settings = get_settings()
    session_factory = await get_session_factory()
    embedder = await get_embedder()
    vector_store = await get_vector_store()

    pipeline = IngestPipeline(
        session_factory=session_factory,
        embedder=embedder,
        vector_store=vector_store,
        settings=IngestionSettings(),
    )

    doc_id, report = await pipeline.ingest_url(university_id, body.url)

    return IngestResponse(
        document_id=doc_id,
        status="completed",
        pages_crawled=report.pages_crawled,
        chunks_created=report.chunks_created,
    )
