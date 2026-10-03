# Incident 5: node failure

| | |
|---|---|
| Expected alert | `KubeNodeDown`, `severity=ticket` |
| Runbook | [KubeNodeDown](../../docs/runbooks/KubeNodeDown.md) |
| Test | `tests/incidents/test_05_node_failure.py` |
| Run | `make incident-5` |

## What happens

A worker node dies. `docker stop` on a kind node container is equivalent to
pulling the power cord.

- The orders replicas on that node become unreachable.
- The node controller marks the node NotReady and taints it.
- The orders pods leave 30 s later, because of their lowered
  `tolerationSeconds`
  ([ADR 10](../../docs/adr/0010-lowered-toleration-seconds.md)), and come back
  on the surviving worker.
- Postgres, Prometheus, Alertmanager, Argo CD and the load generator are not
  affected, because they all run on the infra node
  ([ADR 9](../../docs/adr/0009-single-postgres-on-infra-node.md)).

The incident also measures a blind spot. Requests sent to pods on the dead
node never reach a server, so the server-side availability SLI barely moves
while clients see failures. k6 pushes its client-side counts to Prometheus
(`k6_http_reqs_total`, with `expected_response`), and the test reports both
numbers.

## Injection

The test picks the worker that runs the most orders replicas and stops it:

```sh
docker stop <worker>    # slo-platform-worker or slo-platform-worker2
```

## What the test asserts

1. Clean baseline: `Watchdog` is firing, no page is firing, and `KubeNodeDown`
   is not firing.
2. `KubeNodeDown` fires within the detection timeout.
3. Three orders replicas are Ready on nodes other than the stopped one, and
   none of them is terminating.
4. During the incident (from the injection until the three replicas are back,
   plus 30 s), the share of failed client requests is at most 10%. That is
   `k6_http_reqs_total{scenario="baseline", expected_response="false"}` divided
   by all baseline requests. The test also records the server-side 5xx share
   for the same window, next to the client-side figure.
5. Remediation: `docker start <worker>`. This runs in a `finally` block, so it
   happens even if a check fails.
6. Recovery: the node is Ready again and `KubeNodeDown` resolves.

The replicas stay on the surviving worker after the node returns, because
Kubernetes does not rebalance running pods.

Clean baseline means `Watchdog` firing, no page, and none of this incident's
expected alerts. Tickets left over from earlier incidents are tolerated.

## Run it

```sh
make up            # once; OVERLAYS="kind ci" make up for compressed windows
make incident-5
```

The report, written to `reports/incidents/05-node-failure.json`, includes the
victim node, the replicas it ran, `client_failed_share` and
`server_5xx_share`. For measured values, see the latest CI run of the
`incidents` workflow.
