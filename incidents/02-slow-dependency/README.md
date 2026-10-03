# Incident 2: slow dependency

| | |
|---|---|
| Expected alert | `OrdersLatencyBurnRate`, `severity=page` |
| Runbook | [OrdersLatencyBurnRate](../../docs/runbooks/OrdersLatencyBurnRate.md) |
| Test | `tests/incidents/test_02_slow_dependency.py` |
| Run | `make incident-2` |

## What happens

Postgres gets slow. Every packet the Postgres pod sends is delayed by 400 ms,
so every query reply arrives late and every orders request goes over the
300 ms latency threshold. Requests still succeed.

All orders pods stay Ready because readiness does not check the database
([ADR 2](../../docs/adr/0002-readiness-does-not-depend-on-database.md)). The
Postgres pod is not restarted either, because its probes run `pg_isready` via
exec.

## Injection

```sh
kubectl apply -f incidents/02-slow-dependency/network-delay.yaml
```

This is a Chaos Mesh `NetworkChaos` named `slow-postgres` in the `orders`
namespace: `action: delay`, latency 400 ms, `mode: all`, applied to pods
labelled `app: postgres`. Its 30m `duration` is a safety net in case the test
dies before removing it.

The delay covers all egress of the Postgres pod, not a targeted delay from
orders to Postgres. Targeted delays miss traffic sent to a Service ClusterIP
([ADR 7](../../docs/adr/0007-chaos-mesh-delay-on-postgres-egress.md), with the
spike evidence).

## What the test asserts

1. Clean baseline: `Watchdog` is firing, and no page is firing.
2. `OrdersLatencyBurnRate` fires with `severity=page` within the detection
   timeout.
3. The runbook's diagnosis path works. Within 120 s, Tempo returns at least
   one orders trace matching
   `{ resource.service.name = "orders" && kind = client && duration > 350ms }`,
   which means a database span slower than 350 ms. The test searches from 30 s
   before the injection, and records the trace ID in the report.
4. Remediation: the experiment is deleted with `kubectl delete -f`. This runs
   in a `finally` block, so it happens even if a check fails.
5. Recovery: the share of requests over 300 ms in the last minute is back at
   or below 1%.
   - With CI windows, the page must also clear.
   - With real windows, the page clearing is recorded rather than required.

Clean baseline means `Watchdog` firing, no page, and none of this incident's
expected alerts. Tickets left over from earlier incidents are tolerated.

## Run it

```sh
make up            # once; OVERLAYS="kind ci" make up for compressed windows
make incident-2
```

The report is written to `reports/incidents/02-slow-dependency.json`. For
measured times, see the latest CI run of the `incidents` workflow.
