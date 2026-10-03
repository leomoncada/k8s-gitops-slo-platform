"""Incident #6: a traffic spike larger than autoscaling can absorb.

A k6 Job ramps to ~350 requests per second. The HPA scales orders from 3 to its
maximum of 6, OrdersHPAMaxedOut fires because there is no headroom left, and
everything settles once the load ends.
"""

import json

from platform_lib import ROOT, Timeouts, alert_firing, kubectl, narrate, wait_until

ALERT = "OrdersHPAMaxedOut"
SPIKE = str(ROOT / "incidents/06-traffic-spike/spike.yaml")


def hpa() -> dict:
    return json.loads(kubectl("-n", "orders", "get", "hpa", "orders", "-o", "json"))


def test_traffic_spike(report, baseline, compressed):
    t = Timeouts.for_profile(compressed, detect=300, recover=240)
    t.detect = min(t.detect, 420)  # the spike itself lasts 6.5 minutes
    baseline([(ALERT, None)], timeout=t.recover)
    r = report("06-traffic-spike", "a traffic spike beyond autoscaling")
    max_replicas = hpa()["spec"]["maxReplicas"]

    try:
        kubectl("apply", "-f", SPIKE)
        r.mark("injected")
        narrate("k6 spike: ramping to ~350 requests per second")
        wait_until(
            f"HPA reaches its maximum of {max_replicas}",
            lambda: hpa()["status"].get("currentReplicas", 0) >= max_replicas,
            t.detect,
        )
        r.mark("hpa_maxed")
        wait_until("HPA-maxed-out alert fires", lambda: alert_firing(ALERT), t.detect)
        r.mark("detected")
    finally:
        kubectl("delete", "-f", SPIKE, "--ignore-not-found", "--wait=true")
    r.mark("mitigated")
    narrate("spike over")

    wait_until(
        "HPA scales back below its maximum",
        lambda: hpa()["status"].get("currentReplicas", 0) < max_replicas,
        t.recover * 2,
    )
    wait_until("HPA-maxed-out alert resolves", lambda: not alert_firing(ALERT), t.recover)
    r.mark("resolved")
