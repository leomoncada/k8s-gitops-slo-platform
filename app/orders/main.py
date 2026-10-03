"""Application factory. Run with ``uvicorn --factory orders.main:create_app``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg
import structlog
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from orders import db
from orders.api import router
from orders.config import Settings
from orders.logs import configure_logging
from orders.observability import RequestObservabilityMiddleware, set_build_info
from orders.telemetry import configure_tracing, instrument_app

log = structlog.get_logger("orders")


async def database_unavailable(request: Request, exc: Exception) -> Response:
    """Pool timeouts, connection errors and statement timeouts become a 503."""
    log.warning("database_unavailable", error=type(exc).__name__, detail=str(exc))
    return JSONResponse(
        {"detail": "database unavailable"}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
    )


async def database_error(request: Request, exc: Exception) -> Response:
    log.error("database_error", error=type(exc).__name__, detail=str(exc))
    return JSONResponse(
        {"detail": "database error"}, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
    )


async def metrics_endpoint(request: Request) -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(json_logs=settings.log_json, level=settings.log_level)
    provider = configure_tracing(settings)
    set_build_info(settings.app_version)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        pool = db.create_pool(settings)
        await pool.open(wait=False)
        app.state.pool = pool
        log.info("startup", version=settings.app_version)
        try:
            yield
        finally:
            await pool.close()
            provider.force_flush()
            log.info("shutdown")

    app = FastAPI(
        title="orders",
        version=settings.app_version,
        lifespan=lifespan,
        # FastAPI's built-in OpenTelemetry support is switched off: tracing is
        # done by opentelemetry-instrumentation-fastapi (orders.telemetry), and
        # its OTLP auto-configuration would add a second span exporter to our
        # provider plus an OTLP metrics pipeline nobody scrapes.
        telemetry={
            "auto_configure": False,
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
        },
    )
    app.include_router(router)
    app.add_route("/metrics", metrics_endpoint, include_in_schema=False)
    # psycopg's PoolTimeout and QueryCanceled are both OperationalErrors.
    app.add_exception_handler(psycopg.OperationalError, database_unavailable)
    app.add_exception_handler(psycopg.Error, database_error)
    app.add_middleware(RequestObservabilityMiddleware)
    instrument_app(app, provider)
    return app
