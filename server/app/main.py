"""App factory: middleware, honest errors, API routes, then the SPA."""

from contextlib import asynccontextmanager
from pathlib import Path

import psycopg
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import PoolTimeout
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import router
from .db import make_pool
from .ratelimit import RateLimitMiddleware
from .settings import Settings

DIST = Path(__file__).resolve().parents[2] / "dist"

ERROR_NAMES = {404: "not_found", 422: "validation_error", 429: "rate_limited",
               503: "service_unavailable"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool = make_pool(settings.database_url)
        app.state.pool.open()
        yield
        app.state.pool.close()

    app = FastAPI(title="StanzaBonanza", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def on_validation(request, exc):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", []) if p != "query")
        detail = f"{where}: {first.get('msg', 'invalid')}" if where else "invalid request"
        return JSONResponse(
            {"error": "validation_error", "detail": detail, "status": 422},
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request, exc):
        name = ERROR_NAMES.get(exc.status_code, "error")
        return JSONResponse(
            {"error": name, "detail": str(exc.detail), "status": exc.status_code},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(psycopg.OperationalError)
    @app.exception_handler(PoolTimeout)
    async def on_db_down(request, exc):
        return JSONResponse(
            {"error": "service_unavailable", "detail": "database unreachable",
             "status": 503},
            status_code=503,
        )

    if settings.origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.origins,
            allow_methods=["GET"],
            allow_headers=["*"],
            allow_credentials=False,
        )
    app.add_middleware(
        RateLimitMiddleware,
        per_minute=settings.rate_limit_per_minute,
        burst=settings.rate_limit_burst,
    )

    app.include_router(router)

    @app.get("/api/{rest:path}")
    def api_not_found(rest: str):
        return JSONResponse(
            {"error": "not_found", "detail": f"no such endpoint: /api/{rest}",
             "status": 404},
            status_code=404,
        )

    if DIST.exists():
        app.mount("/", StaticFiles(directory=DIST, html=True), name="spa")

    return app


app = create_app()
