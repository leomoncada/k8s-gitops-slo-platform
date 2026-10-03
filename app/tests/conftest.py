"""Shared fixtures. Tests run against a real Postgres, never a mock.

Set TEST_DATABASE_URL to use an existing database (CI's service container).
Otherwise a throwaway ``postgres:17`` container is started on a free port and
removed when the session ends.
"""

import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from orders.config import Settings
from orders.main import create_app

APP_DIR = Path(__file__).resolve().parents[1]
SCHEMA = APP_DIR / "schema.sql"
POSTGRES_IMAGE = "postgres:17"


def _wait_for_postgres(url: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with psycopg.connect(url, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.25)


def _start_postgres_container() -> tuple[str, str]:
    if shutil.which("docker") is None:
        pytest.exit("Set TEST_DATABASE_URL or install Docker to run the tests", returncode=2)
    name = f"orders-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        [
            "docker", "run", "--detach", "--rm", "--name", name,
            "--env", "POSTGRES_USER=orders",
            "--env", "POSTGRES_PASSWORD=orders",
            "--env", "POSTGRES_DB=orders",
            "--publish", "127.0.0.1::5432",  # Docker picks a free host port
            "--tmpfs", "/var/lib/postgresql/data",
            POSTGRES_IMAGE,
            "-c", "fsync=off", "-c", "synchronous_commit=off", "-c", "full_page_writes=off",
        ],
        check=True,
        capture_output=True,
    )  # fmt: skip
    try:
        port = (
            subprocess.run(
                ["docker", "port", name, "5432/tcp"], check=True, capture_output=True, text=True
            )
            .stdout.split()[0]
            .rsplit(":", 1)[1]
        )
    except BaseException:
        subprocess.run(["docker", "rm", "--force", name], check=False, capture_output=True)
        raise
    return name, f"postgresql://orders:orders@127.0.0.1:{port}/orders"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = os.environ.get("TEST_DATABASE_URL")
    container = None
    if not url:
        container, url = _start_postgres_container()
    try:
        _wait_for_postgres(url)
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(SCHEMA.read_text())
        yield url
    finally:
        if container:
            subprocess.run(["docker", "rm", "--force", container], check=False, capture_output=True)


@pytest.fixture
def clean_db(database_url: str) -> str:
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE orders RESTART IDENTITY")
    return database_url


@pytest.fixture
def settings(clean_db: str) -> Settings:
    return Settings(database_url=clean_db, db_pool_timeout=1.0)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
