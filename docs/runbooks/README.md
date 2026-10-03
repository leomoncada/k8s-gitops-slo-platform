# Runbooks

There is one runbook per alert, not per incident, as in real operations. Every
alert carries a `runbook_url` annotation that points here. Each incident in
`incidents/` names the runbook to follow.

| Alert | Severity | Source | Fires when | Related incident |
|---|---|---|---|---|
| [OrdersAvailabilityBurnRate](OrdersAvailabilityBurnRate.md) | page / ticket | Sloth (`slos/orders.yaml`) | 5xx responses burn the 99.9% availability budget too fast | [#1 bad release](../../incidents/01-bad-release/README.md) |
| [OrdersLatencyBurnRate](OrdersLatencyBurnRate.md) | page / ticket | Sloth (`slos/orders.yaml`) | Requests over 300 ms burn the 99% latency budget too fast | [#2 slow dependency](../../incidents/02-slow-dependency/README.md) |
| [OrdersContainerOOMKilled](OrdersContainerOOMKilled.md) | ticket | `alerts/templates/rules.yaml` | An orders container restarted after an OOM kill | [#3 memory leak](../../incidents/03-memory-leak/README.md) |
| [GitOpsDriftNotHealed](GitOpsDriftNotHealed.md) | ticket | `alerts/templates/rules.yaml` | An auto-synced Argo CD Application stays OutOfSync despite self-heal | [#4 manual drift](../../incidents/04-manual-drift/README.md) (must not fire) |
| [KubeNodeDown](KubeNodeDown.md) | ticket | `alerts/templates/rules.yaml` | A node is not Ready | [#5 node failure](../../incidents/05-node-failure/README.md) |
| [OrdersHPAMaxedOut](OrdersHPAMaxedOut.md) | ticket | `alerts/templates/rules.yaml` | The orders HPA runs at its maximum replica count | [#6 traffic spike](../../incidents/06-traffic-spike/README.md) |
| [OrdersMetricsAbsent](OrdersMetricsAbsent.md) | page | `alerts/templates/rules.yaml` | No orders scrape target is up, so the SLO alerts are blind | None (promtool tests only) |

Hold times for the rules in `alerts/` are set per overlay: real-time values
in `alerts/values.yaml`, shorter ones for CI in `alerts/values-ci.yaml`. The
Sloth alerts use real 30-day windows locally and compressed 1-hour windows in
CI ([ADR 6](../adr/0006-compressed-slo-windows-in-ci.md)).

## Page and ticket

- Alertmanager sends `severity=page` to the `page` receiver and everything
  else to `ticket`. `Watchdog` goes nowhere: it only proves the pipeline is
  alive.
- Both receivers post to a minimal webhook sink, `alert-sink` in the
  `monitoring` namespace, which writes one JSON line per notification. Read
  those lines in Loki with
  `{k8s_namespace_name="monitoring"} | json | receiver=~"page|ticket"`.

## Where things are (local)

All ports are NodePorts bound to 127.0.0.1 by `cluster/kind.yaml`.

| What | URL | Notes |
|---|---|---|
| Grafana | http://localhost:30300 | The anonymous viewer sees the dashboards `orders: service` (`/d/orders-service`) and `orders: SLOs` (`/d/orders-slo`). Explore requires logging in as admin/admin (local only) |
| Prometheus | http://localhost:30090 | Graph, Alerts, Status > Targets |
| Alertmanager | http://localhost:30093 | `curl -s 'http://localhost:30093/api/v2/alerts?active=true'` |
| Argo CD | http://localhost:30080 | Anonymous read-only. The admin password is in the `argocd-initial-admin-secret` Secret. CLI: `argocd login localhost:30080 --plaintext` |
| Tempo API | http://localhost:30320 | TraceQL search at `/api/search?q=...` |
| In-cluster Git | http://localhost:30232/platform.git | The repository Argo CD reads from. Fixes and reverts go here locally |
| orders API | http://localhost:30800 | |

## Conventions used in every runbook

- **Logs.** In Loki, orders logs carry the label `k8s_namespace_name="orders"`.
  Each line is JSON, so add `| json` and filter on `event`, `route`, `status`,
  `duration_ms` or `trace_id`.
- **Traces.** orders spans have `resource.service.name = "orders"`, and
  `resource.service.version` holds the release. `kind = server` spans are HTTP
  requests; `kind = client` spans are Postgres calls.
- **Changes go through Git.** Never use `kubectl edit` on anything Argo CD
  manages: self-heal reverts it within seconds, and the cause stays in Git. Fix
  a bad release with `git revert` of the release commit, pushed to the
  repository Argo CD reads from. The single exception is restoring replicas
  after a scale to zero (see [OrdersMetricsAbsent](OrdersMetricsAbsent.md) and
  [ADR 11](../adr/0011-hpa-owns-replicas.md)).
- **`make sync` publishes your working tree** to the in-cluster repository. If
  you run it in the middle of an incident, it also overwrites the incident's
  commit.
