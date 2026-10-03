# Architecture decision records

Short records of the decisions that shape this repository, in the format
Michael Nygard proposed: context, decision, consequences. The working spec is
[`docs/DESIGN.md`](../DESIGN.md). Section 17 of the spec lists what changed
during implementation.

| # | Decision | Summary |
|---|---|---|
| 1 | [In-cluster Git server as the Argo CD source](0001-in-cluster-git-server.md) | Soft Serve inside the cluster, seeded by `make sync`. Incidents commit and revert there without tokens. GitHub in phase 2. |
| 2 | [Readiness does not depend on the database](0002-readiness-does-not-depend-on-database.md) | `/readyz` never checks Postgres, so a slow database cannot mark every replica unready at once. The SLOs catch it instead. |
| 3 | [Tempo over Jaeger](0003-tempo-over-jaeger.md) | One Grafana UI with linked logs and traces, plus TraceQL. Instrumentation is OTLP, so the backend is a Collector exporter change. |
| 4 | [No service mesh in v1](0004-no-service-mesh.md) | One service and one database do not justify Istio. Records when a mesh, or Linkerd, Cilium or Argo Rollouts, would be worth it. |
| 5 | [Sloth for SLOs; generated rules committed](0005-sloth-generated-rules-committed.md) | SLOs are declared in `slos/orders.yaml`. Generated rules are committed, regenerated in CI and fail on any diff, and are unit-tested with promtool. |
| 6 | [Compressed SLO windows in CI](0006-compressed-slo-windows-in-ci.md) | A 1-hour SLO period with the same burn-rate thresholds (14.4 / 6 / 3 / 1), so incidents detect and clear in minutes. |
| 7 | [Chaos Mesh delay on the Postgres pod's egress](0007-chaos-mesh-delay-on-postgres-egress.md) | A targeted delay misses traffic sent to a Service ClusterIP (spike evidence from 2026-10-03), so all egress of the Postgres pod is delayed instead. |
| 8 | [Memory incident via a real leaking release](0008-memory-incident-real-leaking-release.md) | StressChaos gets its own stressor killed, not the app. A leaking `v1.2.0` causes a real OOM. Also explains why the schema is applied by an init container, not a sync hook. |
| 9 | [Single Postgres and the platform on the infra node](0009-single-postgres-on-infra-node.md) | Postgres and every platform component are pinned to the control-plane node, so a worker failure only affects orders. Postgres is an accepted single point of failure. |
| 10 | [Lowered tolerationSeconds](0010-lowered-toleration-seconds.md) | orders pods leave a dead node 30 s after it is tainted, not after the default 300 s. |
| 11 | [The HPA owns replicas](0011-hpa-owns-replicas.md) | Argo CD ignores `/spec/replicas` on the orders Deployment, so self-heal and the HPA do not fight. |
