"""Prometheus metrics and the per-request middleware that records them.

The middleware also writes the one access-log line per request. Probes and
the metrics endpoint are skipped: they would dominate the counters without
saying anything about what users experience.
"""

import time

import structlog
from prometheus_client import Counter, Gauge, Histogram, disable_created_metrics
from starlette.types import ASGIApp, Message, Receive, Scope, Send

UNINSTRUMENTED_PATHS = frozenset({"/healthz", "/readyz", "/metrics"})

# Label used when no route matched, so random paths cannot explode cardinality.
UNMATCHED_ROUTE = "unmatched"

# 0.3 s is the latency SLO threshold, so it must be an exact bucket boundary.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2.5, 5)

disable_created_metrics()

HTTP_REQUESTS = Counter(
    "http_requests",
    "HTTP requests served, by route template and status code.",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency, by route template.",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
)
BUILD_INFO = Gauge("orders_build_info", "Running build of the orders service.", ["version"])

access_log = structlog.get_logger("orders.access")


def set_build_info(version: str) -> None:
    BUILD_INFO.clear()
    BUILD_INFO.labels(version=version).set(1)


def route_template(scope: Scope) -> str:
    """The matched route's template (``/orders/{id}``), never the raw path."""
    route = scope.get("route")
    return getattr(route, "path", None) or UNMATCHED_ROUTE


class RequestObservabilityMiddleware:
    """Pure ASGI middleware: counts, times and logs every instrumented request.

    It runs inside the OpenTelemetry server span, so the log line carries the
    request's trace and span ids.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in UNINSTRUMENTED_PATHS:
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        # If the app raises before sending a response, the client gets a 500.
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - start
            method = scope["method"]
            route = route_template(scope)
            HTTP_REQUESTS.labels(method=method, route=route, status=str(status)).inc()
            HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(elapsed)
            log = access_log.error if status >= 500 else access_log.info
            log(
                "request",
                method=method,
                route=route,
                status=status,
                duration_ms=round(elapsed * 1000, 2),
            )
