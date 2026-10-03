# orders

A small FastAPI service backed by Postgres, built to fail in realistic ways for
the incident tests. Design notes: [`docs/DESIGN.md`](../docs/DESIGN.md), section 4.

| Endpoint | Purpose |
|---|---|
| `POST /orders` | Create an order: `{"customer_id": str, "items": [{"sku": str, "qty": int > 0}], "note": str or null}` → 201 |
| `GET /orders/{id}` | One order, or 404 |
| `GET /orders?limit=N` | Most recent orders (default 20, max 100) |
| `GET /healthz` | Liveness |
| `GET /readyz` | Readiness. Does not check Postgres, so a slow database cannot mark every replica unready |
| `GET /metrics` | Prometheus metrics |

Database failures return 503 quickly: a request waits at most 2 s for a pooled
connection, and every statement is capped at 3 s by `statement_timeout`.

## Configuration

| Variable | Default | |
|---|---|---|
| `DATABASE_URL` | required | libpq URL, e.g. `postgresql://orders:orders@postgres:5432/orders` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | e.g. `http://otel-collector:4318`. Unset: spans exist (logs carry trace ids) but are not exported |
| `OTEL_SERVICE_NAME` | `orders` | |
| `LOG_JSON` | `true` | `false` gives human-readable console logs |
| `APP_VERSION` | `1.0.0` | Baked into the image from the `APP_VERSION` build arg |
| `LOG_LEVEL` | `INFO` | |
| `DB_POOL_MIN_SIZE` / `DB_POOL_MAX_SIZE` | `1` / `10` | Connections per replica |
| `DB_POOL_TIMEOUT_SECONDS` | `2` | Wait for a pooled connection before a 503 |
| `DB_CONNECT_TIMEOUT_SECONDS` | `2` | |
| `DB_STATEMENT_TIMEOUT_MS` | `3000` | |

The schema lives in [`schema.sql`](schema.sql). It is applied by the Kubernetes
initContainer in the orders Deployment (and by the tests); the service never creates schema.

## Telemetry

- `http_requests_total{method, route, status}` and
  `http_request_duration_seconds{method, route}` (a bucket at exactly 0.3 s,
  the latency SLO threshold). `route` is the route template, such as
  `/orders/{id}`; unmatched paths share `route="unmatched"`. Probes and
  `/metrics` are not counted.
- `orders_build_info{version}` is always 1.
- Traces: FastAPI server spans with psycopg spans as children, exported over
  OTLP/HTTP. Probes and `/metrics` are not traced.
- Logs: one JSON line per request on stdout with `method`, `route`, `status`,
  `duration_ms`, `trace_id` and `span_id`.

## Develop

```sh
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
pytest                                   # from app/, or `pytest app/tests` from the repo root
```

Tests run against a real Postgres. With `TEST_DATABASE_URL` set they use that
database; otherwise they start a throwaway `postgres:17` container with Docker
and remove it afterwards.

Run locally against any Postgres:

```sh
DATABASE_URL=postgresql://... LOG_JSON=false uvicorn --factory orders.main:create_app --reload
```

## Images and incident releases

`scripts/build-images.sh` (from the repo root) builds `orders:1.0.0` from this
directory, and `orders:1.1.0` / `orders:1.2.0` by applying the release patches
in `incidents/` to a copy of it:

| Version | Patch | Behaviour |
|---|---|---|
| 1.0.0 | | Correct |
| 1.1.0 | `incidents/01-bad-release/v1.1.0.patch` | Serializer "refactor" raises on orders whose note is null; probes keep passing |
| 1.2.0 | `incidents/03-memory-leak/v1.2.0.patch` | Keeps a 256 KiB resident snapshot per request with no eviction, until OOM |

`tests/test_patches.py` applies both patches to a temporary copy and checks
the failure each one is meant to cause, so a change here that breaks a patch
fails the test suite. The patches are `git format-patch` output: `git am` or
`git apply` them from the repo root.
