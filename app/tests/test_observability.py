"""Metrics, traces and logs: the contract the SLOs, dashboards and runbooks rely on."""

import io
import json
import logging
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider as SDKMeterProvider
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from prometheus_client import REGISTRY

from orders.config import Settings
from orders.main import create_app

ORDER = {"customer_id": "c", "items": [{"sku": "A", "qty": 1}], "note": "n"}


def requests_total(method: str, route: str, status: str) -> float:
    labels = {"method": method, "route": route, "status": status}
    return REGISTRY.get_sample_value("http_requests_total", labels) or 0.0


def test_requests_are_counted_by_route_template_and_status(client: TestClient) -> None:
    before_ok = requests_total("GET", "/orders/{id}", "200")
    before_missing = requests_total("GET", "/orders/{id}", "404")
    before_created = requests_total("POST", "/orders", "201")
    before_invalid = requests_total("POST", "/orders", "422")

    order_id = client.post("/orders", json=ORDER).json()["id"]
    client.post("/orders", json={})
    client.get(f"/orders/{order_id}")
    client.get("/orders/424242")

    assert requests_total("POST", "/orders", "201") == before_created + 1
    assert requests_total("POST", "/orders", "422") == before_invalid + 1
    assert requests_total("GET", "/orders/{id}", "200") == before_ok + 1
    assert requests_total("GET", "/orders/{id}", "404") == before_missing + 1


def test_unmatched_paths_share_one_label(client: TestClient) -> None:
    before = requests_total("GET", "unmatched", "404")

    client.get("/nope/123")
    client.get("/nope/456")

    assert requests_total("GET", "unmatched", "404") == before + 2


def test_metrics_exposition(client: TestClient) -> None:
    client.get("/orders/1")
    client.get("/healthz")
    client.get("/readyz")
    client.get("/metrics")

    response = client.get("/metrics")
    text = response.text

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# TYPE http_requests_total counter" in text
    assert "# TYPE http_request_duration_seconds histogram" in text
    assert (
        'http_request_duration_seconds_bucket{le="0.3",method="GET",route="/orders/{id}"}' in text
    )
    buckets = re.findall(
        r'http_request_duration_seconds_bucket\{le="([^"]+)",method="GET",route="/orders/\{id\}"\}',
        text,
    )
    assert buckets == [
        "0.005", "0.01", "0.025", "0.05", "0.1", "0.2", "0.3", "0.5", "1.0", "2.5", "5.0", "+Inf",
    ]  # fmt: skip
    # Raw paths never become labels, and probes/scrapes are not instrumented.
    assert 'route="/orders/1"' not in text
    for path in ("/healthz", "/readyz", "/metrics"):
        assert f'route="{path}"' not in text
    assert "_created" not in text


def test_build_info_carries_the_version(clean_db: str) -> None:
    with TestClient(create_app(Settings(database_url=clean_db, app_version="9.9.9"))) as client:
        text = client.get("/metrics").text

    assert 'orders_build_info{version="9.9.9"} 1.0' in text
    assert REGISTRY.get_sample_value("orders_build_info", {"version": "9.9.9"}) == 1


def test_build_info_defaults_to_the_code_version(client: TestClient) -> None:
    assert REGISTRY.get_sample_value("orders_build_info", {"version": "1.0.0"}) == 1


@pytest.fixture
def spans(client: TestClient) -> Iterator[InMemorySpanExporter]:
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    yield exporter
    exporter.shutdown()  # the processor stays registered but drops spans from now on


def test_database_spans_are_children_of_the_request_span(
    client: TestClient, spans: InMemorySpanExporter
) -> None:
    order_id = client.post("/orders", json=ORDER).json()["id"]
    spans.clear()

    client.get(f"/orders/{order_id}")

    finished = spans.get_finished_spans()
    server = [s for s in finished if s.kind is SpanKind.SERVER]
    database = [
        s
        for s in finished
        if s.kind is SpanKind.CLIENT
        and "postgresql" in (s.attributes.get("db.system"), s.attributes.get("db.system.name"))
    ]
    assert len(server) == 1
    assert server[0].name == "GET /orders/{id}"
    assert database, [s.name for s in finished]
    for span in database:
        assert span.parent is not None
        assert span.parent.span_id == server[0].context.span_id
        assert span.context.trace_id == server[0].context.trace_id


def test_probes_and_scrapes_are_not_traced(client: TestClient, spans: InMemorySpanExporter) -> None:
    client.get("/healthz")
    client.get("/readyz")
    client.get("/metrics")

    assert spans.get_finished_spans() == ()


@pytest.fixture
def log_stream(client: TestClient) -> Iterator[io.StringIO]:
    (handler,) = logging.getLogger().handlers
    assert isinstance(handler, logging.StreamHandler)
    stream = io.StringIO()
    original = handler.setStream(stream)
    yield stream
    handler.setStream(original)


def access_lines(stream: io.StringIO) -> list[dict]:
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    return [line for line in lines if line.get("event") == "request"]


def test_one_json_access_log_line_per_request(client: TestClient, log_stream: io.StringIO) -> None:
    client.post("/orders", json=ORDER)
    client.get("/orders/31337")
    client.get("/healthz")

    lines = access_lines(log_stream)

    assert [(line["method"], line["route"], line["status"]) for line in lines] == [
        ("POST", "/orders", 201),
        ("GET", "/orders/{id}", 404),
    ]
    for line in lines:
        assert re.fullmatch(r"[0-9a-f]{32}", line["trace_id"])
        assert re.fullmatch(r"[0-9a-f]{16}", line["span_id"])
        assert isinstance(line["duration_ms"], float)
        assert line["duration_ms"] >= 0
        assert {"timestamp", "level"} <= line.keys()
    assert lines[0]["trace_id"] != lines[1]["trace_id"]


def test_log_trace_id_matches_the_exported_trace(
    client: TestClient, spans: InMemorySpanExporter, log_stream: io.StringIO
) -> None:
    client.get("/orders/5")

    (line,) = access_lines(log_stream)
    (server,) = [s for s in spans.get_finished_spans() if s.kind is SpanKind.SERVER]
    assert line["trace_id"] == format(server.context.trace_id, "032x")
    assert line["span_id"] == format(server.context.span_id, "016x")


def test_unhandled_errors_count_as_5xx(settings: Settings) -> None:
    app = create_app(settings)

    async def boom() -> None:
        raise RuntimeError("bug")

    app.add_api_route("/boom", boom)
    before = requests_total("GET", "/boom", "500")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/boom")

    assert response.status_code == 500
    assert requests_total("GET", "/boom", "500") == before + 1


def test_server_logs_share_the_json_shape(client: TestClient, log_stream: io.StringIO) -> None:
    logging.getLogger("uvicorn.error").info("server message")
    logging.getLogger("uvicorn.access").info("duplicate access line")

    lines = [json.loads(line) for line in log_stream.getvalue().splitlines()]

    assert [(line["logger"], line["event"]) for line in lines] == [
        ("uvicorn.error", "server message")
    ]
    assert list(lines[0])[:4] == ["timestamp", "level", "logger", "event"]


def test_otlp_env_does_not_add_exporters_behind_our_back(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FastAPI's own telemetry must not attach extra OTLP pipelines from the env."""
    create_app(settings)  # make sure our tracer provider is installed
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    processors_before = len(provider._active_span_processor._span_processors)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9")

    with TestClient(create_app(settings)) as client:
        client.get("/orders")

    assert len(provider._active_span_processor._span_processors) == processors_before
    assert not isinstance(metrics.get_meter_provider(), SDKMeterProvider)
