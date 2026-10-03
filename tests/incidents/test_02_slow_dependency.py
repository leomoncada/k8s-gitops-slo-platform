"""Incident #2: Postgres gets slow; the latency SLO notices and a trace shows why.

Chaos Mesh delays everything the Postgres pod sends by 400 ms. Every request
then breaks the 300 ms latency threshold. The test also proves the diagnosis
path from the runbook: Tempo has orders traces whose database (client) spans
take longer than 350 ms.
"""

import time

import requests

from platform_lib import (
    ROOT,
    TEMPO,
    Timeouts,
    alert_firing,
    kubectl,
    narrate,
    slow_ratio,
    wait_for_recovery,
    wait_until,
)

ALERT = "OrdersLatencyBurnRate"
CHAOS = str(ROOT / "incidents/02-slow-dependency/network-delay.yaml")


def slow_db_traces(since: float) -> list[dict]:
    response = requests.get(
        f"{TEMPO}/api/search",
        params={
            "q": '{ resource.service.name = "orders" && kind = client && duration > 350ms }',
            "start": int(since),
            "end": int(time.time()),
            "limit": 5,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json().get("traces", [])


def test_slow_dependency(report, baseline, compressed):
    t = Timeouts.for_profile(compressed, detect=240, recover=300)
    baseline([(ALERT, "page")], timeout=t.recover)
    r = report("02-slow-dependency", "Postgres slows down")

    try:
        kubectl("apply", "-f", CHAOS)
        r.mark("injected")
        narrate("Chaos Mesh: +400 ms on every packet the Postgres pod sends")

        wait_until(
            "latency burn-rate page fires",
            lambda: alert_firing(ALERT, "page"),
            t.detect,
        )
        r.mark("detected")

        traces = []
        wait_until(
            "Tempo shows orders database spans slower than 350 ms",
            lambda: traces.extend(slow_db_traces(r.marks["injected"] - 30)) or traces,
            120,
        )
        r.facts["slow_db_trace_example"] = traces[0].get("traceID")
    finally:
        kubectl("delete", "-f", CHAOS, "--ignore-not-found", "--wait=true")
    r.mark("mitigated")

    wait_for_recovery(r, ALERT, slow_ratio, budget=0.01, compressed=compressed, timeout=t.recover)
