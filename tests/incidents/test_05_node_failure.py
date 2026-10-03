"""Incident #5: a worker node dies.

`docker stop` on a kind worker is a node losing power. KubeNodeDown fires, the
orders replicas on it move to the surviving worker within the lowered
tolerationSeconds (ADR 10), and the node rejoins when it comes back.

It also measures a blind spot: requests sent to pods on the dead node never
reach the server, so the server-side availability SLI barely moves while
clients (k6) see failures. Both numbers go in the report.
"""

from platform_lib import (
    Timeouts,
    alert_firing,
    kubectl,
    narrate,
    orders_pods,
    prom_value,
    run,
    wait_until,
)

ALERT = "KubeNodeDown"
FAILED = 'expected_response="false"'
CLIENT_FAILURE_BUDGET = 0.10  # share of client requests allowed to fail during the incident


def ready_orders_off(node: str) -> int:
    count = 0
    for pod in orders_pods():
        conditions = {c["type"]: c["status"] for c in pod.get("status", {}).get("conditions", [])}
        if (
            pod["spec"].get("nodeName") != node
            and conditions.get("Ready") == "True"
            and pod["metadata"].get("deletionTimestamp") is None
        ):
            count += 1
    return count


def node_ready(node: str) -> bool:
    status = kubectl(
        "get",
        "node",
        node,
        "-o",
        'jsonpath={.status.conditions[?(@.type=="Ready")].status}',
    )
    return status == "True"


def test_node_failure(report, baseline, compressed):
    t = Timeouts.for_profile(compressed, detect=180, recover=300)
    baseline([(ALERT, None)], timeout=t.recover)
    r = report("05-node-failure", "a worker node dies")

    counts: dict[str, int] = {}
    for pod in orders_pods():
        counts[pod["spec"]["nodeName"]] = counts.get(pod["spec"]["nodeName"], 0) + 1
    victim = max(counts, key=counts.get)
    r.facts["victim_node"] = victim
    r.facts["replicas_on_victim"] = counts[victim]

    run("docker", "stop", victim)
    r.mark("injected")
    narrate(f"node {victim} stopped ({counts[victim]} orders replicas on it)")
    try:
        wait_until("KubeNodeDown fires", lambda: alert_firing(ALERT), t.detect)
        r.mark("detected")
        wait_until(
            "3 Ready orders replicas on the surviving worker",
            lambda: ready_orders_off(victim) >= 3,
            t.recover,
        )
        r.mark("mitigated")
        window = f"{int(r.marks['mitigated'] - r.marks['injected']) + 30}s"
        client = prom_value(
            f'sum(increase(k6_http_reqs_total{{scenario="baseline", {FAILED}}}[{window}]))'
        ) / max(
            prom_value(f'sum(increase(k6_http_reqs_total{{scenario="baseline"}}[{window}]))'),
            1,
        )
        server = prom_value(
            f'sum(increase(http_requests_total{{job="orders", status=~"5.."}}[{window}]))'
        ) / max(
            prom_value(f'sum(increase(http_requests_total{{job="orders"}}[{window}]))'),
            1,
        )
        r.facts["client_failed_share"] = round(client, 4)
        r.facts["server_5xx_share"] = round(server, 4)
        narrate(f"failed requests: client-side {client:.2%}, server-side 5xx {server:.2%}")
        assert client <= CLIENT_FAILURE_BUDGET, f"{client:.1%} of client requests failed"
    finally:
        run("docker", "start", victim)
        narrate(f"node {victim} started again")

    wait_until(f"{victim} Ready again", lambda: node_ready(victim), t.recover)
    wait_until("KubeNodeDown resolves", lambda: not alert_firing(ALERT), t.recover)
    r.mark("resolved")
