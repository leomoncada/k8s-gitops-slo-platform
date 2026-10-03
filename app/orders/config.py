"""Runtime configuration, read from environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from orders import __version__

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _bool(value: str | None, *, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    normalized = value.strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    raise ValueError(f"not a boolean: {value!r}")


def _otlp_traces_endpoint(env: Mapping[str, str]) -> str | None:
    """Resolve the traces URL the way the OTLP/HTTP spec does."""
    if signal_specific := env.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "").strip():
        return signal_specific
    if base := env.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        return f"{base.rstrip('/')}/v1/traces"
    return None


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    service_name: str = "orders"
    app_version: str = __version__
    log_json: bool = True
    log_level: str = "INFO"
    # Full OTLP/HTTP traces URL. Spans are always created in-process (logs
    # carry trace ids); they are only exported when this is set.
    otlp_traces_endpoint: str | None = None
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10
    # A request waits at most this long for a pooled connection, then gets a 503.
    db_pool_timeout: float = 2.0
    db_connect_timeout: int = 2
    db_statement_timeout_ms: int = 3000

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        database_url = env.get("DATABASE_URL", "").strip()
        if not database_url:
            raise RuntimeError("DATABASE_URL is required")
        return cls(
            database_url=database_url,
            service_name=env.get("OTEL_SERVICE_NAME") or "orders",
            app_version=env.get("APP_VERSION") or __version__,
            log_json=_bool(env.get("LOG_JSON"), default=True),
            log_level=(env.get("LOG_LEVEL") or "INFO").upper(),
            otlp_traces_endpoint=_otlp_traces_endpoint(env),
            db_pool_min_size=int(env.get("DB_POOL_MIN_SIZE", "1")),
            db_pool_max_size=int(env.get("DB_POOL_MAX_SIZE", "10")),
            db_pool_timeout=float(env.get("DB_POOL_TIMEOUT_SECONDS", "2")),
            db_connect_timeout=int(env.get("DB_CONNECT_TIMEOUT_SECONDS", "2")),
            db_statement_timeout_ms=int(env.get("DB_STATEMENT_TIMEOUT_MS", "3000")),
        )
