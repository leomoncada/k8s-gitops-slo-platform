# 4. No service mesh in v1, and when one would be worth it

Date: 2026-10-03

Status: Accepted

## Context

A service mesh such as Istio or Linkerd adds mTLS, L7 metrics, retries,
timeouts and traffic splitting through sidecars or node proxies. Here, orders
is one service talking to one database. Istio would add a control plane, a
proxy per pod, CRDs to upgrade and memory use on 16 GB CI runners. It would
also be one more component that every incident has to reason about.

## Decision

No service mesh in v1. What a mesh would provide is covered elsewhere:

- RED metrics come from the app itself (`prometheus_client` in
  `app/orders/observability.py`). Client-side metrics come from k6 through
  remote write (`k6_http_reqs_total`).
- Traces come from the OpenTelemetry SDK (ADR 3).
- Timeouts live in client code: the pool wait is capped at 2 s, statements at
  3 s and k6 requests at 2 s.
- Faults are injected by Chaos Mesh at the network layer (ADR 7). This works
  for Postgres's TCP protocol, where HTTP-level mesh fault injection would not.
- Canary releases, when they arrive (future incident #7), will use Argo
  Rollouts with replica-weighted traffic. No mesh is needed for that.

## Consequences

- There are fewer moving parts. The incidents test orders and the GitOps loop,
  not proxy behaviour.
- There is no mTLS. Traffic inside the cluster, including the Postgres
  connection, is plain text. That is acceptable for a local, single-tenant lab,
  not for production with sensitive data.
- There are no per-route retries, no circuit breaking and no header-based
  routing. A canary in incident #7 can split traffic only by replica count,
  not by share of requests or by header.
- Golden signals exist only for code we instrumented. A new service without
  instrumentation would be invisible.

A mesh becomes worth its cost when:

- Many services owned by many teams need the same telemetry, retries and
  timeouts without each team building them.
- mTLS between workloads is mandatory (compliance, zero-trust), with
  identity-based authorization.
- Fine-grained traffic management is needed: weighted or header-based routing,
  mirroring, per-route retries and L7 fault injection.

Istio fits when all three apply. Lighter options cover parts of the list:
Linkerd gives mTLS and golden metrics with less to operate. Cilium gives
eBPF-based networking, network policy and transparent encryption without
sidecars. Argo Rollouts on its own is enough for canaries.
