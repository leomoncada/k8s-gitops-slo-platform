# 3. Tempo over Jaeger

Date: 2026-10-03

Status: Accepted

## Context

Incident #2 needs traces: the runbook has to show that the time is spent
waiting on Postgres. The platform already runs Grafana, Prometheus and Loki.
The two common open-source trace backends are Jaeger and Grafana Tempo.

## Decision

Tempo in single-binary mode, using the chart `grafana-community/tempo` 3.1.0
(the `grafana/tempo` chart is deprecated and moved there). Values are in
`deploy/overlays/common/tempo.yaml`, and the Application is in
`deploy/platform/templates/applications.yaml`.

- orders exports OTLP/HTTP to the OpenTelemetry Collector DaemonSet, which
  forwards over OTLP gRPC to Tempo (`deploy/overlays/common/otel-collector.yaml`).
  The application knows only OTLP.
- The Grafana datasources link in both directions
  (`deploy/overlays/common/kube-prometheus-stack.yaml`). A Loki derived field
  turns the `trace_id` in a log line into a Tempo link, and Tempo's
  traces-to-logs query is `{k8s_namespace_name="orders"} |= "<trace id>"`.
- TraceQL is the language for diagnosis. The incident #2 test runs
  `{ resource.service.name = "orders" && kind = client && duration > 350ms }`
  against Tempo's API on `localhost:30320`. That NodePort Service is defined
  in `deploy/platform-config/templates/nodeports.yaml`, because the chart has
  no nodePort setting.

## Consequences

- Grafana is the single UI for metrics, logs and traces, and you can jump from
  a log line to its trace and back.
- In phase 2, Tempo can store traces cheaply in object storage. It indexes only
  trace IDs and block metadata.
- Changing the backend means changing a Collector exporter. Application code
  does not change.
- In v1 Tempo has no persistence and keeps traces for 12 h, so a Tempo restart
  loses them. The metrics generator (span metrics, service graphs) is off to
  save memory, so that advantage is not used yet.
- Tag searches scan stored blocks instead of an index. That is fine at this
  scale; at large volume, an indexed store answers tag lookups faster.
- There is no standalone trace UI. Traces are viewed in Grafana.

Jaeger would be the better choice for:

- Teams that do not run the Grafana stack and want traces without adopting it.
- Organisations that already run Elasticsearch or OpenSearch and want traces in
  the same store, with indexed tag search.
- Teams that want a standalone trace UI, with its own service dependency view
  and trace comparison, separate from their metrics and logs tools.
