# Incident 4: manual drift

| | |
|---|---|
| Expected alert | None. Argo CD self-heal repairs the drift, and `GitOpsDriftNotHealed` must not fire |
| Runbook | [GitOpsDriftNotHealed](../../docs/runbooks/GitOpsDriftNotHealed.md), for when self-heal cannot repair it |
| Test | `tests/incidents/test_04_manual_drift.py` |
| Run | `make incident-4` |

## What happens

Someone changes production by hand, outside Git. They set a "hotfix" env var
and delete the PodDisruptionBudget. Argo CD runs with automated sync and
`selfHeal: true`, so it notices the difference from Git and restores both,
without anyone being paged.

The drift is an env var plus a deleted PDB, not "scale to 0". The HPA owns
replicas and Argo CD ignores them, and an HPA does not act on a Deployment
that has been scaled to zero. So scaling to zero would test neither self-heal
nor autoscaling
([ADR 11](../../docs/adr/0011-hpa-owns-replicas.md)).

## Injection

```sh
kubectl -n orders set env deployment/orders LOG_LEVEL=debug
kubectl -n orders delete pdb orders
```

## What the test asserts

1. Clean baseline: `Watchdog` is firing, no page is firing, and
   `GitOpsDriftNotHealed` is not firing. Before the injection, `LOG_LEVEL` is
   `info` and the PDB exists with `minAvailable: 2`.
2. Within 60 s (polled every 2 s), `LOG_LEVEL` is back to `info` and the PDB
   exists again with `minAvailable: 2`. The time it took is recorded as
   `self_heal_seconds`. For drift, detection and repair are the same event.
3. `GitOpsDriftNotHealed` is not firing.
4. Neither `OrdersAvailabilityBurnRate` nor `OrdersLatencyBurnRate` fired a
   page. The two rollouts, one from the manual change and one from the repair,
   did not hurt users.

The firing side of `GitOpsDriftNotHealed`, drift that persists past its hold
time, is proven without a cluster by the promtool test "drift that self-heal
cannot fix fires" in `alerts/tests/platform-alerts.test.yaml`.

Clean baseline means `Watchdog` firing, no page, and none of this incident's
expected alerts. Tickets left over from earlier incidents are tolerated.

## Run it

```sh
make up            # once
make incident-4
```

The report is written to `reports/incidents/04-manual-drift.json`. For the
measured self-heal time, see the latest CI run of the `incidents` workflow.
