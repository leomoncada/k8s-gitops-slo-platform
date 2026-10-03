"""Database failures must turn into fast 5xx responses, and must not touch readiness."""

import socket
import time
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from orders.config import Settings
from orders.main import create_app

ORDER = {"customer_id": "c", "items": [{"sku": "A", "qty": 1}], "note": None}


def _closed_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def unreachable_db_client() -> Iterator[TestClient]:
    settings = Settings(
        database_url=f"postgresql://orders:orders@127.0.0.1:{_closed_port()}/orders",
        db_pool_timeout=0.5,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def test_probes_pass_while_the_database_is_unreachable(
    unreachable_db_client: TestClient,
) -> None:
    assert unreachable_db_client.get("/healthz").status_code == 200
    assert unreachable_db_client.get("/readyz").status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/orders"), ("GET", "/orders/1"), ("GET", "/orders")],
)
def test_unreachable_database_is_a_fast_503(
    unreachable_db_client: TestClient, method: str, path: str
) -> None:
    started = time.monotonic()
    response = unreachable_db_client.request(method, path, json=ORDER if method == "POST" else None)

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
    assert time.monotonic() - started < 3


def test_statement_timeout_is_a_503(clean_db: str) -> None:
    settings = Settings(database_url=clean_db, db_statement_timeout_ms=300)
    with TestClient(create_app(settings)) as client:
        assert client.get("/orders").status_code == 200  # pool is warm
        # Hold a lock that blocks every read and write on the table.
        with psycopg.connect(clean_db) as locker:
            locker.execute("LOCK TABLE orders IN ACCESS EXCLUSIVE MODE")
            started = time.monotonic()
            response = client.post("/orders", json=ORDER)
            elapsed = time.monotonic() - started
            locker.rollback()

        assert response.status_code == 503
        assert 0.3 <= elapsed < 2
        # Once the lock is gone the same pool serves again.
        assert client.post("/orders", json=ORDER).status_code == 201
