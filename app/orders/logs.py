"""Structured logging: one JSON object per line on stdout.

structlog and the standard library (uvicorn, psycopg, OpenTelemetry) share one
handler, so every line has the same shape and, inside a request, the same
``trace_id`` / ``span_id`` that Tempo stores.
"""

import logging
import sys

import structlog
from opentelemetry import trace
from structlog.typing import EventDict, Processor, WrappedLogger

# uvicorn configures its loggers before loading the app; route them to root.
_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error")
# The app writes its own access line per request (with route and trace ids);
# uvicorn's would duplicate it and add every probe hit.
_SILENCED_LOGGERS = ("uvicorn.access",)
_LEADING_KEYS = ("timestamp", "level", "logger", "event")


def add_trace_context(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Attach the current span's ids in the W3C hex form (32 and 16 chars)."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
    return event_dict


def leading_keys_first(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Put timestamp, level, logger and event first so lines scan easily."""
    head = {key: event_dict.pop(key) for key in _LEADING_KEYS if key in event_dict}
    return {**head, **event_dict}


def configure_logging(*, json_logs: bool = True, level: str = "INFO") -> None:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_trace_context,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: list[Processor] = (
        [
            structlog.processors.format_exc_info,
            leading_keys_first,
            structlog.processors.JSONRenderer(),
        ]
        if json_logs
        else [structlog.dev.ConsoleRenderer()]
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *renderer],
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
    for name in _SILENCED_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = False
