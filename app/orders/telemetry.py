"""OpenTelemetry tracing: FastAPI server spans with psycopg spans as children.

Spans are always created, so logs carry real trace ids. They are exported over
OTLP/HTTP only when ``OTEL_EXPORTER_OTLP_ENDPOINT`` (or the traces-specific
variable) is set.
"""

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from orders.config import Settings

# Regexes matched against the request URL. Probes and scrapes are not traced.
EXCLUDED_URLS = "/healthz$,/readyz$,/metrics$"

_provider: TracerProvider | None = None


def configure_tracing(settings: Settings) -> TracerProvider:
    """Install the global tracer provider and psycopg instrumentation, once.

    The provider is process-global in OpenTelemetry, so repeated calls (one per
    app built in tests) reuse the first one.
    """
    global _provider  # noqa: PLW0603 - process-wide singleton by design
    if _provider is None:
        provider = TracerProvider(
            resource=Resource.create(
                {SERVICE_NAME: settings.service_name, SERVICE_VERSION: settings.app_version}
            )
        )
        if settings.otlp_traces_endpoint:
            exporter = OTLPSpanExporter(endpoint=settings.otlp_traces_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        # Must run before the pool opens its first connection.
        PsycopgInstrumentor().instrument(tracer_provider=provider)
        _provider = provider
    return _provider


def instrument_app(app: FastAPI, provider: TracerProvider) -> None:
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=EXCLUDED_URLS,
        # Skip the per-message "http send"/"http receive" spans; they add noise
        # to every trace without explaining latency.
        exclude_spans=["receive", "send"],
    )
