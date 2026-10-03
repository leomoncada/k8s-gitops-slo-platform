# Postmortem: Postgres replies 400 ms late

Blameless: this describes what the system and the process allowed. Numbers come
from `reports/incidents/02-slow-dependency.json`, Prometheus and Tempo, from a
local run with the CI overlay (compressed SLO windows, [ADR 6](../adr/0006-compressed-slo-windows-in-ci.md)).

| | |
|---|---|
| Date | 2026-10-03 |
| Incident | [`incidents/02-slow-dependency/`](../../incidents/02-slow-dependency/README.md) |
| Severity | page (`OrdersLatencyBurnRate`) |
| Status | resolved |
| Time to detect | 30 s from the first delayed packet to the page |
| Time to recover | 66 s from the page to the SLI back within objective |
| Error budget consumed | 0.14% of the 30-day latency budget |

## Summary

Every packet leaving the Postgres pod was delayed by 400 ms (a Chaos Mesh
`NetworkChaos` experiment standing in for a degraded database host). Each
orders request runs at least one query, so requests went from a few
milliseconds to over 400 ms, past the 300 ms latency threshold. The latency
burn-rate alert paged 30 seconds in. It did not stay a latency problem: each
request held a pooled connection for several delayed round trips, the pool ran
dry, and reads started failing with 503 after the 2 s pool timeout. No pod
restarted or went unready.

## Impact

- 371 of 1,092 requests in the incident window were slower than 300 ms (34%).
  During the delay itself, nearly every request was.
- 67 requests failed with 503 during the 35 seconds of delay (about 19%),
  all reads (`GET /orders/{id}` and `GET /orders`), all pool timeouts. The
  latency incident cascaded into an availability incident.
- 0.14% of the 30-day latency budget, plus availability budget for the 503s.

## Timeline (UTC)

| Time | Event |
|---|---|
| 15:49:32 | 400 ms delay applied to all egress of the Postgres pod |
| 15:50:02 | `OrdersLatencyBurnRate` page fires |
| 15:50:08 | Tempo shows orders traces with a database (client) span above 350 ms; delay removed |
| 15:51:08 | Share of requests over 300 ms back under 1% |
| 15:51:13 | Page clears |

## Root cause

Injected: network latency on the database host. In production the same
symptom comes from a saturated disk, a noisy neighbour, or cross-zone traffic
after a failover.

Why it became errors: each replica has a pool of 10 connections and waits at
most 2 s for one. With every query reply 400 ms late, a request holds its
connection for several round trips, so demand for connections outgrew the pool
and waiting requests timed out with 503.

## Detection

The latency SLO caught it because the histogram has a bucket exactly at the
300 ms threshold, so the SLI counts slow requests exactly instead of
interpolating. The trace answered the next question, where the time went,
without guessing: TraceQL
`{ resource.service.name = "orders" && kind = client && duration > 350ms }`
returns database (client) spans that account for the delay.

## What went well

- Readiness does not depend on Postgres ([ADR 2](../adr/0002-readiness-does-not-depend-on-database.md)).
  If it did, all three replicas would have gone unready at once and a
  degradation would have become a full outage.
- Postgres probes use `pg_isready` via exec, so the network delay never
  restarted the database.
- Logs carry the `trace_id`, and the Loki and Tempo datasources are linked both
  ways in Grafana, so a slow span leads straight to its request's log line.

## What went badly

- A slower dependency turned into errors within seconds: the pool size and the
  2 s pool timeout had never been sized against a slow database.
- No metric shows pool saturation, so the 503s were the first sign of it.
- There is no database-side latency metric; the diagnosis depends on traces.

## Action items

| Action | Type | Status |
|---|---|---|
| Export pool usage (in use, waiting) as metrics and alert before it is exhausted | detect | future work |
| Size the pool and its timeout against a degraded database, and shed load early with a clear 503 instead of queueing | mitigate | future work |
| Add a Postgres exporter and a query latency panel | detect | future work |
