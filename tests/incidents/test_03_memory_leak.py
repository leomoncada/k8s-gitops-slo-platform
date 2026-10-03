"""Incident #3: a release with a memory leak, OOM-killed by Kubernetes.

orders 1.2.0 (incidents/03-memory-leak/v1.2.0.patch) keeps a buffer per request
in a cache that never evicts. Memory climbs to the container limit and the
kernel kills the process: a real OOM of the application, not of a stressor.
The fix is `git revert`.
"""

from platform_lib import (
    Timeouts,
    alert_firing,
    orders_pods,
    rollout_complete,
    wait_until,
)

ALERT = "OrdersContainerOOMKilled"


def oom_restarts() -> int:
    total = 0
    for pod in orders_pods():
        for status in pod.get("status", {}).get("containerStatuses", []):
            last = status.get("lastState", {}).get("terminated", {})
            if status["name"] == "orders" and last.get("reason") == "OOMKilled":
                total += status.get("restartCount", 0)
    return total


def test_memory_leak(gitops, report, baseline, compressed):
    # OOM takes ~4 minutes of traffic at the 256Mi limit, whatever the windows.
    t = Timeouts.for_profile(compressed, detect=480, recover=360)
    t.detect = max(t.detect, 600)
    baseline([(ALERT, None)], timeout=t.recover)
    r = report("03-memory-leak", "a release with a memory leak")

    sha = gitops.set_orders_image(
        "1.2.0",
        "release: orders 1.2.0\n\nShips incidents/03-memory-leak/v1.2.0.patch "
        "(request replay cache for debugging).",
    )
    r.mark("injected")
    reverted = False
    try:
        wait_until("1.2.0 fully rolled out", lambda: rollout_complete("orders:1.2.0"), t.rollout)
        wait_until("OOM-kill alert fires", lambda: alert_firing(ALERT), t.detect)
        r.mark("detected")
        restarts = oom_restarts()
        assert restarts > 0, "the alert fired but no container reports an OOMKilled restart"
        r.facts["oom_restarts_at_detection"] = restarts

        gitops.revert(sha)
        reverted = True
        r.mark("mitigated")
    finally:
        if not reverted:
            gitops.revert(sha)  # never leave the leaking release behind
    wait_until("1.0.0 rolled back", lambda: rollout_complete("orders:1.0.0"), t.rollout)
    wait_until("OOM-kill alert resolves", lambda: not alert_firing(ALERT), t.recover)
    r.mark("resolved")
