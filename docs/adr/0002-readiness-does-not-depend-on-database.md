# 2. Readiness does not depend on the database

Date: 2026-10-03

Status: Accepted

## Context

Every business request to orders needs Postgres, so it is tempting to make
`/readyz` check the database. But all three replicas share one Postgres. If
the database becomes slow or unreachable, the check fails on every replica at
the same moment. Kubernetes then removes all of them from the Service
endpoints, and a partial degradation (slow queries, as in incident #2) turns
into a total outage: connections are refused and nobody gets a useful
response. `/api/health/ready` in `aws-ecs-fargate-platform` follows the same
reasoning.

## Decision

- `GET /readyz` reports only whether the process can serve. It never touches
  Postgres (`app/orders/api.py`). `GET /healthz` is liveness only. Both probes
  are wired in `deploy/workloads/templates/orders.yaml`.
- Database failures show up as fast errors instead. A request waits at most
  2 s for a pooled connection, every statement is capped at 3 s by
  `statement_timeout`, and `psycopg.OperationalError` becomes a 503
  (`app/orders/db.py`, `app/orders/main.py`).
- The connection pool opens without waiting, so a running replica stays Ready
  while Postgres is down and keeps reconnecting in the background.
- Postgres's own probes run `pg_isready` via exec, so network chaos on its pod
  never restarts it (`deploy/workloads/templates/postgres.yaml`, ADR 7).

## Consequences

- In incident #2 every replica stays Ready and serves slowly. The latency SLO
  catches it, not the probes.
- A database outage shows up as 5xx responses on the availability SLO, which
  can be measured and alerted on, instead of as a Service with no endpoints.
- Readiness cannot route around a single replica with a broken connection
  pool: that replica stays in rotation and keeps returning 503s. The SLO alerts
  are the only signal, and the fix is to delete that pod.
- "All pods Ready" does not mean healthy. Runbooks say so explicitly.
- New pods are different from running ones. The schema init container (ADR 8)
  has to reach Postgres before the app container starts, so rollouts, HPA
  scale-ups and rescheduling after a node failure all stall while the database
  is unreachable.
- Probes and `/metrics` are left out of the metrics and traces
  (`app/orders/observability.py`, `app/orders/telemetry.py`), so probe traffic
  does not dilute the SLIs.
