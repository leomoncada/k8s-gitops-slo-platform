# Incident 3: memory leak

| | |
|---|---|
| Expected alert | `OrdersContainerOOMKilled`, `severity=ticket` |
| Runbook | [OrdersContainerOOMKilled](../../docs/runbooks/OrdersContainerOOMKilled.md) |
| Test | `tests/incidents/test_03_memory_leak.py` |
| Run | `make incident-3` |

## What happens

orders `1.2.0` adds a debugging feature, "replay snapshots"
([`v1.2.0.patch`](v1.2.0.patch)). For every request it keeps a fixed 256 KiB
record, keyed by trace ID, in a dictionary that never evicts anything. Memory
grows with traffic until the container reaches its 256 Mi limit, and the
kernel kills the application process. That is a real OOM, not a stressor's
([ADR 8](../../docs/adr/0008-memory-incident-real-leaking-release.md)).

## Injection

A release commit to the in-cluster repository, the same way as incident #1:

1. Change `image: orders:1.0.0` to `image: orders:1.2.0` in
   `deploy/workloads/values.yaml` in a clone of
   `http://localhost:30232/platform.git`.
2. Commit with the message "release: orders 1.2.0" and push to `main`.
3. Force an Argo CD refresh.

The `orders:1.2.0` image is built from the patch by `scripts/build-images.sh`
and loaded into kind by `make up`.

## What the test asserts

1. Clean baseline: `Watchdog` is firing, no page is firing, and
   `OrdersContainerOOMKilled` is not firing.
2. `orders:1.2.0` rolls out completely.
3. `OrdersContainerOOMKilled` fires. The detection timeout is at least 10
   minutes, because time to OOM depends on traffic per replica.
4. At least one orders container reports a restart whose last termination
   reason is `OOMKilled`. The count is recorded in the report.
5. Remediation: `git revert` of the release commit. `orders:1.0.0` rolls out
   again. The schema init container, rather than a sync hook, is what lets
   this revert sync while the Deployment is in an OOM loop (ADR 8).
6. Recovery: the alert resolves. That happens once no OOM restart has occurred
   for a full window: 10m locally, 3m in CI.

Clean baseline means `Watchdog` firing, no page, and none of this incident's
expected alerts. Tickets left over from earlier incidents are tolerated.

## Run it

```sh
make up            # once; OVERLAYS="kind ci" make up for compressed windows
make incident-3
```

The report is written to `reports/incidents/03-memory-leak.json`. For measured
times, see the latest CI run of the `incidents` workflow.
