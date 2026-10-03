# KubeNodeDown

| | |
|---|---|
| Severity | `ticket` |
| Source | Our own rule, `alerts/templates/rules.yaml` (group `cluster`) |
| Fires after | 1m not Ready locally, 30s in CI (`nodeDownFor` in `alerts/values*.yaml`) |
| Dashboard | `orders: service` at http://localhost:30300/d/orders-service (panels "Replicas" and "5xx share: server-side vs client-side (k6)") |

## Meaning

A node's `Ready` condition is not `True`. It is either `False`, or `Unknown`
because the kubelet stopped reporting.

```promql
kube_node_status_condition{condition="Ready", status="true"} == 0
```

kube-prometheus-stack's `KubeNodeNotReady` covers the same condition after 15
minutes; this rule warns sooner.

In this cluster, the workers (`slo-platform-worker`, `slo-platform-worker2`)
run only orders replicas and DaemonSets. Everything else runs on the infra
node, `slo-platform-control-plane` (ADR 9).

## Impact

- **Before eviction.** The node controller first has to notice the node is
  gone. Until then, requests routed to orders pods on that node time out at the
  client and never reach a server. The server-side availability SLI barely
  moves. Only the k6 client-side metric shows these failures.
- **After eviction.** orders pods tolerate the `not-ready` and `unreachable`
  taints for only 30 s (ADR 10). After that, they are evicted and recreated on
  the surviving worker. The PodDisruptionBudget does not slow this down.
- **When the node returns.** The pods stay on the surviving worker. Kubernetes
  does not rebalance running pods.
- **If the infra node is the one down.** Prometheus, Alertmanager, Argo CD,
  Postgres and the load generator are all gone, so this alert cannot even be
  delivered. The sign is that Watchdog notifications stop.

## Diagnosis

1. Which node, and since when?

   ```sh
   kubectl get nodes -o wide
   kubectl describe node <node>      # Conditions, and Taints: node.kubernetes.io/unreachable
   docker ps -a --filter name=slo-platform   # kind nodes are containers (local only)
   ```

   ```promql
   kube_node_status_condition{condition="Ready"}
   kube_node_spec_taint{key=~"node.kubernetes.io/(unreachable|not-ready)"}
   up{job="node-exporter"}
   ```

2. Where are the orders replicas, and are they back to three?

   ```sh
   kubectl -n orders get pods -l app=orders -o wide
   kubectl -n orders get events --sort-by=.lastTimestamp | tail -20
   ```

   ```promql
   count by (node) (kube_pod_info{namespace="orders", pod=~"orders-.*"})
   kube_deployment_status_replicas_available{namespace="orders", deployment="orders"}
   ```

   If replacements are `Pending`, `kubectl -n orders describe pod <pod>` shows
   why (capacity, topology spread). If they are stuck in `Init`, the schema
   init container cannot reach Postgres.

3. What do users see? Compare client-side failures with server-side 5xx.

   ```promql
   sum(rate(k6_http_reqs_total{scenario="baseline", expected_response="false"}[1m]))
     / sum(rate(k6_http_reqs_total{scenario="baseline"}[1m]))

   sum(rate(http_requests_total{job="orders", status=~"5.."}[1m]))
     / sum(rate(http_requests_total{job="orders"}[1m]))
   ```

   A high client-side ratio next to a near-zero server-side ratio is the
   expected signature of a dead node.

4. Logs and traces add little. The OpenTelemetry Collector on the dead node is
   down too, so its pods' logs stop arriving:
   `{k8s_namespace_name="orders"} | json | event="request"`. Traces show only
   requests that reached a server, so the failures to the dead node are not in
   Tempo. Use the k6 metric instead. On kind, the node's kubelet logs are at
   `docker exec <node> journalctl -u kubelet --since "15 min ago"`, if the
   container is running.

## Mitigation

1. Make sure orders has three Ready replicas on the surviving worker. If it
   has, users are served again, even while the node is still down.
2. Bring the node back. On kind, run `docker start <node>`. On a real cluster,
   repair or replace the machine. If it flaps, cordon it with
   `kubectl cordon <node>` so nothing new lands there.
3. Optionally, rebalance once the node is Ready again. Delete one orders pod at
   a time on the crowded worker with `kubectl -n orders delete pod <pod>`. The
   scheduler puts the replacement on the emptier node, and the
   PodDisruptionBudget keeps two replicas available. Otherwise the pods spread
   out again at the next rollout.

Do not delete the node object of a kind node. Do not edit orders' tolerations
by hand; they come from Git (`orders.tolerationSeconds`).

## Escalation

- The node does not come back, or a second node fails: escalate to the
  platform team. With one worker left, orders has no spare failure domain.
- The infra node is down: escalate immediately. It means a total outage, with
  no alerting, no GitOps and no database (ADR 9).

## Related incident

[Incident #5: node failure](../../incidents/05-node-failure/README.md)
