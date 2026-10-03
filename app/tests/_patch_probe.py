"""Exercise a patched copy of the service. Run by test_patches.py, not by pytest.

Usage: python _patch_probe.py <bad-release|memory-leak> <result.json>

PYTHONPATH must point at the patched app/ directory and PROBE_DATABASE_URL at
the test database. The result is written as JSON to the given path (stdout
carries the service's own logs).
"""

import gc
import json
import os
import subprocess
import sys
from datetime import UTC, datetime

from fastapi.testclient import TestClient

import orders
from orders.config import Settings
from orders.main import create_app

ORDER = {"customer_id": "probe", "items": [{"sku": "A", "qty": 1}]}


def settings() -> Settings:
    return Settings(database_url=os.environ["PROBE_DATABASE_URL"])


def rss_kib() -> int:
    """Current resident set size: /proc on Linux, ps(1) elsewhere (macOS)."""
    try:
        with open("/proc/self/statm", encoding="ascii") as statm:
            return int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") // 1024
    except FileNotFoundError:
        return int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())]))


def bad_release() -> dict:
    from orders.serialization import serialize_order  # noqa: PLC0415

    row = {
        "id": 1,
        "customer_id": "c",
        "items": [],
        "note": None,
        "created_at": datetime.now(UTC),
    }
    try:
        serialize_order(row)
        null_note_error = None
    except Exception as exc:  # noqa: BLE001 - the probe reports whatever it raised
        null_note_error = type(exc).__name__

    with TestClient(create_app(settings()), raise_server_exceptions=False) as client:
        return {
            "null_note_error": null_note_error,
            "normalised_note": serialize_order({**row, "note": " ring\n\n twice "})["note"],
            "post_with_note": client.post("/orders", json={**ORDER, "note": "hi"}).status_code,
            "post_null_note": client.post("/orders", json={**ORDER, "note": None}).status_code,
            "healthz": client.get("/healthz").status_code,
            "readyz": client.get("/readyz").status_code,
        }


def memory_leak(requests: int = 32) -> dict:
    from orders import replay  # noqa: PLC0415

    default_bytes = replay.REPLAY_BUFFER_BYTES
    # Bigger records make the resident-memory growth unmistakable in a short run.
    replay.REPLAY_BUFFER_BYTES = 1024 * 1024

    with TestClient(create_app(settings())) as client:
        client.get("/orders")  # warm up the pool and first-request allocations
        gc.collect()
        snapshots_before, rss_before = len(replay._snapshots), rss_kib()
        for _ in range(requests):
            client.get("/orders")
        snapshots_after, rss_after = len(replay._snapshots), rss_kib()
        client.get("/healthz")
        snapshots_after_probe = len(replay._snapshots)

    return {
        "default_buffer_bytes": default_bytes,
        "requests": requests,
        "record_bytes": replay.REPLAY_BUFFER_BYTES,
        "snapshot_growth": snapshots_after - snapshots_before,
        "probe_growth": snapshots_after_probe - snapshots_after,
        "rss_growth_kib": rss_after - rss_before,
    }


if __name__ == "__main__":
    scenario, output = sys.argv[1], sys.argv[2]
    result = {"bad-release": bad_release, "memory-leak": memory_leak}[scenario]()
    result["version"] = orders.__version__
    result["module"] = orders.__file__
    with open(output, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
