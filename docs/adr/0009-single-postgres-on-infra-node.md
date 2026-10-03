# 9. Single Postgres instance and the platform pinned to the infra node

Date: 2026-10-03

Status: Accepted

## Context

Postgres keeps its data on a local-path volume, which is tied to one node.
Incident #5 stops a worker with `docker stop`. If Postgres lived on that
worker, the incident would become a total outage and would tell us nothing
about orders.

The same applies to the observability and delivery stack. During the build,
Prometheus, Alertmanager and the load generator landed on workers, so the
node-failure incident could blind the very tools that watch it, and
`KubeNodeDown` might never be delivered. A highly available Postgres (an
operator such as CloudNativePG) would be out of proportion for v1.

## Decision

Run one Postgres instance: a StatefulSet using `postgres:17.11`, defined in
`deploy/workloads/templates/postgres.yaml`, with no operator and no Bitnami
chart.

The kind control-plane node is the infra node, labelled `platform/role=infra`
in `cluster/kind.yaml`. Everything except the orders replicas and the
DaemonSets runs there, using `nodeSelector: { platform/role: infra }` plus a
toleration for the control-plane taint:

- Argo CD (`deploy/bootstrap/argocd-values.yaml`) and Soft Serve.
- Prometheus, Alertmanager, Grafana, the Prometheus operator and
  kube-state-metrics (`deploy/overlays/common/kube-prometheus-stack.yaml`).
- Loki, Tempo, metrics-server, and the Chaos Mesh controller and DNS server.
- Postgres, the k6 baseline traffic, the incident #6 spike Job and the alert
  sink.

Workers run only orders replicas and DaemonSets (node-exporter, the
OpenTelemetry Collector, chaos-daemon). orders does not tolerate the
control-plane taint, so it never lands on the infra node. Its topology spread
uses `nodeTaintsPolicy: Honor`. Without that, the tainted control-plane counts
as an empty domain, and a third replica can never satisfy `maxSkew: 1` across
two workers.

## Consequences

- A worker failure only ever affects orders replicas. Postgres, the load
  generator and alerting keep running.
- Postgres is a single point of failure, and the README says so. Losing the
  infra node, its container or its volume is a total outage, and there are no
  backups.
- Losing the infra node also takes Prometheus and Alertmanager down, so no
  alert can report it. The only sign is that `Watchdog` notifications stop, and
  in v1 nothing outside the cluster watches for that.
- One node carries the whole platform, so resource pressure there affects
  everything. In production this would be a dedicated, tainted infra node
  pool, not the control plane.
- A failure of the control-plane node is not one of the incident scenarios.
