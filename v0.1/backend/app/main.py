from __future__ import annotations

from collections.abc import Iterator
import json
import logging

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import SessionLocal, init_db
from app.schemas import DomainsResponse, IngestRequest, IngestResponse, QueryRequest, QueryResponse
from app.service import answer_generation_health, health_summary, ingest_curated, list_domains, query, query_stream

app = FastAPI(title="Unichat RAG API", version="0.1.0")
_LOGGER = logging.getLogger(__name__)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def startup() -> None:
    init_db()
    generation = answer_generation_health()
    backend = str(generation.get("backend", "unknown"))
    model = str(generation.get("model", "n/a"))
    detail = str(generation.get("detail", ""))
    if generation.get("ok", False):
        _LOGGER.info(
            "Answer generation backend ready backend=%s model=%s detail=%s",
            backend,
            model,
            detail,
        )
    else:
        _LOGGER.warning(
            "Answer generation backend unhealthy backend=%s model=%s detail=%s",
            backend,
            model,
            detail,
        )


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, object]:
    generation = answer_generation_health()
    status = "ok" if generation.get("ok", False) else "degraded"
    return {"status": status, **health_summary(db), "generation": generation}


@app.get("/health/generation")
def health_generation() -> dict[str, object]:
    return answer_generation_health()


@app.get("/domains", response_model=DomainsResponse)
def domains(db: Session = Depends(get_db)) -> DomainsResponse:
    return DomainsResponse(domains=list_domains(db))


@app.post("/ingest", response_model=IngestResponse)
def ingest(payload: IngestRequest, db: Session = Depends(get_db)) -> IngestResponse:
    documents, chunks = ingest_curated(db, curated_dir_override=payload.curated_dir)
    return IngestResponse(documents=documents, chunks=chunks)


@app.post("/query", response_model=QueryResponse)
def ask(payload: QueryRequest, response: Response, db: Session = Depends(get_db)) -> QueryResponse:
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    result = query(db, question=payload.question, domains=payload.domains, top_k=payload.top_k)
    return QueryResponse(**result)


@app.post("/query/stream")
def ask_stream(payload: QueryRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    def stream() -> Iterator[str]:
        try:
            for event in query_stream(db, question=payload.question, domains=payload.domains, top_k=payload.top_k):
                yield json.dumps(event) + "\n"
        except Exception as exc:  # pragma: no cover - defensive stream guard
            _LOGGER.exception("Unhandled stream error: %s", exc)
            yield json.dumps(
                {
                    "type": "final",
                    "answer": "Insufficient evidence.",
                    "insufficient_evidence": True,
                    "citations": [],
                }
            ) + "\n"

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
