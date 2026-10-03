"""Incident #4: someone changes the cluster by hand; Argo CD puts Git back.

A hotfix-style `kubectl set env` and a deleted PodDisruptionBudget. With
self-heal on, Argo CD restores both in seconds and nobody is paged.
GitOpsDriftNotHealed exists for the case self-heal cannot fix and is proven by
a promtool unit test (alerts/tests/platform-alerts.test.yaml).
"""

import json

from platform_lib import (
    Timeouts,
    alert_firing,
    deployment,
    kubectl,
    narrate,
    wait_until,
)

HEAL_BUDGET_S = 60


def log_level() -> str:
    env = deployment()["spec"]["template"]["spec"]["containers"][0].get("env", [])
    return next((e.get("value") for e in env if e["name"] == "LOG_LEVEL"), "")


def pdb_exists() -> bool:
    out = kubectl("-n", "orders", "get", "pdb", "orders", "-o", "json", "--ignore-not-found")
    return bool(out) and json.loads(out)["spec"].get("minAvailable") == 2


def test_manual_drift(report, baseline, compressed):
    t = Timeouts.for_profile(compressed, detect=60, recover=120)
    baseline([("GitOpsDriftNotHealed", None)], timeout=t.recover)
    r = report("04-manual-drift", "a manual change outside Git")
    assert log_level() == "info"
    assert pdb_exists()

    kubectl("-n", "orders", "set", "env", "deployment/orders", "LOG_LEVEL=debug")
    kubectl("-n", "orders", "delete", "pdb", "orders")
    r.mark("injected")
    narrate("drift: LOG_LEVEL=debug set by hand, PodDisruptionBudget deleted")

    healed = wait_until(
        "Argo CD self-heal restores the env var and the PodDisruptionBudget",
        lambda: log_level() == "info" and pdb_exists(),
        HEAL_BUDGET_S,
        interval=2,
    )
    r.mark("detected")  # for drift, detection and repair are the same event
    r.mark("resolved")
    r.facts["self_heal_seconds"] = round(healed, 1)
    assert not alert_firing("GitOpsDriftNotHealed")
    assert not any(
        alert_firing(a, "page") for a in ("OrdersAvailabilityBurnRate", "OrdersLatencyBurnRate")
    )
