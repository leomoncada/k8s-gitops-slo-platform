# Incident 6: traffic spike

| | |
|---|---|
| Expected alert | `OrdersHPAMaxedOut`, `severity=ticket` |
| Runbook | [OrdersHPAMaxedOut](../../docs/runbooks/OrdersHPAMaxedOut.md) |
| Test | `tests/incidents/test_06_traffic_spike.py` |
| Run | `make incident-6` |

## What happens

A second load generator ramps traffic to about 350 requests per second, well
beyond what six replicas can absorb at the HPA's 60% CPU target. The HPA
scales orders from 3 to its maximum of 6. With no headroom left,
`OrdersHPAMaxedOut` fires. When the load ends, the HPA scales back down and
the alert resolves. Argo CD does not interfere, because it ignores
`/spec/replicas` ([ADR 11](../../docs/adr/0011-hpa-owns-replicas.md)).

## Injection

```sh
kubectl apply -f incidents/06-traffic-spike/spike.yaml
```

This creates a ConfigMap with a k6 script and a Job named `traffic-spike` in
the `orders` namespace.

- The script uses the `ramping-arrival-rate` executor: from 10 to 350 requests
  per second in 30 s, then held for 6 minutes.
- Every request is `GET /orders?limit=20` with a 2 s timeout.
- The Job runs on the infra node, has an `activeDeadlineSeconds` of 480, and
  pushes its metrics to Prometheus under `scenario="spike"`.

## What the test asserts

1. Clean baseline: `Watchdog` is firing, no page is firing, and
   `OrdersHPAMaxedOut` is not firing.
2. The HPA's current replicas reach its `maxReplicas` (6). The detection
   timeout is capped at 420 s, because the spike itself lasts 6.5 minutes.
3. `OrdersHPAMaxedOut` fires.
4. Remediation: the load ends. The test deletes the Job and ConfigMap with
   `kubectl delete -f` in a `finally` block.
5. Recovery: the HPA scales back below its maximum and the alert resolves.
   Scale-down waits for the HPA stabilization window: 300 s locally, 30 s in
   CI (`deploy/workloads/values-ci.yaml`).

Clean baseline means `Watchdog` firing, no page, and none of this incident's
expected alerts. Tickets left over from earlier incidents are tolerated.

## Run it

```sh
make up            # once; OVERLAYS="kind ci" make up for compressed windows
make incident-6
```

The report is written to `reports/incidents/06-traffic-spike.json`. For
measured times, see the latest CI run of the `incidents` workflow.
