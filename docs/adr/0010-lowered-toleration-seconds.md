# 10. Lowered tolerationSeconds for faster node-failure recovery

Date: 2026-10-03

Status: Accepted

## Context

When a node stops responding, the node controller waits for a grace period,
then marks the node NotReady or Unknown, marks its pods not ready, and adds
the `node.kubernetes.io/not-ready` or `node.kubernetes.io/unreachable`
NoExecute taint. Pods that have no explicit toleration get one with
`tolerationSeconds: 300` from the DefaultTolerationSeconds admission plugin,
so they are evicted and replaced only five minutes later. In incident #5 that
would mean five extra minutes of reduced capacity on a single worker.

## Decision

orders tolerates both taints for 30 s. The value is `orders.tolerationSeconds`
in `deploy/workloads/values.yaml`, rendered in
`deploy/workloads/templates/orders.yaml`. Postgres and the platform components
keep the default, since they run on the infra node (ADR 9).

## Consequences

- When a worker dies, its orders replicas are evicted 30 s after the taint
  appears, and their replacements start on the surviving worker. Incident #5
  asserts that three Ready replicas run off the dead node within its timeout.
- The node controller's grace period still comes first. kind leaves the
  kube-controller-manager defaults untouched, and this setting does not
  shorten detection.
- A network blip longer than the grace period plus 30 s evicts healthy pods
  and churns the Deployment. For a stateless service with spare capacity, that
  is the cheaper failure; for stateful or slow-starting workloads it would not
  be.
- Taint-based eviction does not go through the Eviction API, so the
  PodDisruptionBudget (`minAvailable: 2`) does not slow it down. The PDB
  protects against drains, not against losing a node.
- Until the node controller marks the pods not ready, requests to pods on the
  dead node time out at the client and never reach the server. The server-side
  availability SLI barely notices. Incident #5 measures the gap with k6's
  client-side `k6_http_reqs_total{expected_response="false"}`, and requires
  client failures to stay at or below 10%.
- Replacement pods must reach Postgres from the schema init container before
  they start (ADR 8).
- `nodeTaintsPolicy: Honor` (ADR 9) also leaves the dead node, which is tainted
  `unreachable:NoSchedule`, out of the spread calculation, so all three
  replicas can land on the surviving worker. When the node comes back, the
  scheduler does not rebalance running pods; they spread out again at the next
  rollout.
