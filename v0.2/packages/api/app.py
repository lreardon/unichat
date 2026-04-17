from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from packages.api.auth.api_key_auth import InvalidAPIKeyError
from packages.api.dependencies import get_engine
from packages.api.middleware.csrf_middleware import CSRFValidationError
from packages.api.middleware.session_middleware import SessionNotFoundError
from packages.api.routes import chat, health, ingest


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = await get_engine()
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="UniChat API",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(ingest.router)

    _register_error_handlers(app)

    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(SessionNotFoundError)
    async def handle_session_not_found(
        request: Request, exc: SessionNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": "Session expired or invalid"})

    @app.exception_handler(CSRFValidationError)
    async def handle_csrf_error(
        request: Request, exc: CSRFValidationError
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": exc.reason})

    @app.exception_handler(InvalidAPIKeyError)
    async def handle_invalid_api_key(
        request: Request, exc: InvalidAPIKeyError
    ) -> JSONResponse:
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
