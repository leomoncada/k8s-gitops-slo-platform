# OrdersContainerOOMKilled

| | |
|---|---|
| Severity | `ticket` |
| Source | Our own rule, `alerts/templates/rules.yaml` (group `orders`) |
| Fires | As soon as a restart is seen; it stays firing for the restart window after the last OOM kill (10m locally, 3m in CI, `oomWindow` in `alerts/values*.yaml`) |
| Dashboard | `orders: service` at http://localhost:30300/d/orders-service (panels "Memory by pod (limit 256 MiB)" and "Container restarts (5m)") |

## Meaning

An `orders` container restarted within the window, and the reason for its last
termination is `OOMKilled`. The kernel killed the process because it reached
the container's memory limit (256 Mi, `orders.resources.limits.memory` in
`deploy/workloads/values.yaml`).

```promql
increase(kube_pod_container_status_restarts_total{namespace="orders", container="orders"}[10m]) > 0
and on (namespace, pod, container)
kube_pod_container_status_last_terminated_reason{namespace="orders", container="orders", reason="OOMKilled"} == 1
```

kube-prometheus-stack has no fast OOM alert; its `KubePodCrashLooping` waits
15 minutes. That is why this rule exists.

## Impact

- In-flight requests on the killed pod fail at the client with a reset
  connection. The dying process cannot record them, so the server-side
  availability SLI undercounts them. Compare with the client-side k6 metric.
- The pod is not Ready while it restarts. Repeated kills go into
  `CrashLoopBackOff` with growing back-off, which reduces capacity.
- The PodDisruptionBudget does not help: it limits voluntary disruptions, not
  OOM kills.
- If every replica is in an OOM loop, expect `OrdersAvailabilityBurnRate`, and
  eventually `OrdersMetricsAbsent`, to page as well.

## Diagnosis

1. Which pods, how often, and which version?

   ```sh
   kubectl -n orders get pods -l app=orders \
     -o custom-columns=NAME:.metadata.name,IMAGE:.spec.containers[0].image,RESTARTS:.status.containerStatuses[0].restartCount,LAST:.status.containerStatuses[0].lastState.terminated.reason,NODE:.spec.nodeName
   kubectl -n orders describe pod <pod>      # Last State: Terminated, Reason: OOMKilled
   kubectl -n orders top pods -l app=orders  # metrics-server
   kubectl -n orders get events --sort-by=.lastTimestamp | tail -20
   ```

2. Is it a leak or a limit that is too low? Use Prometheus
   (http://localhost:30090) or Grafana Explore (login admin/admin).

   ```promql
   # Working set per pod against the limit
   container_memory_working_set_bytes{namespace="orders", container="orders"}
   max(kube_pod_container_resource_limits{namespace="orders", container="orders", resource="memory"})

   # Growth rate (bytes per second) and requests served per pod
   deriv(container_memory_working_set_bytes{namespace="orders", container="orders"}[5m])
   sum by (pod) (rate(http_requests_total{job="orders"}[5m]))

   # Which version each pod runs
   sum by (version) (orders_build_info{job="orders"})
   ```

   - If memory climbs steadily from each restart until the limit, and faster on
     pods that serve more requests, it is a leak in the code, usually a new
     release.
   - If memory is flat but close to the limit, the limit is too small for the
     real working set.

3. Did it start with a release? In Argo CD (http://localhost:30080), open
   `workloads` and check **History and rollback** for the latest revision and
   its sync time. Or look at the Git history:

   ```sh
   git clone http://localhost:30232/platform.git /tmp/platform && cd /tmp/platform
   git log --oneline -5 -- deploy/workloads/values.yaml
   ```

4. Check the logs. A SIGKILL leaves no last words, so look at the lines before
   the gap, and count the restarts.

   ```sh
   kubectl -n orders logs <pod> -c orders --previous | tail -20
   ```

   ```logql
   {k8s_namespace_name="orders"} | json | event="startup"
   ```

   Each `startup` line is one process start and carries its `version`.

5. Traces help little here. Spans waiting in the exporter's batch are lost
   when the process is killed, so gaps in Tempo around the kill times are
   expected. To see what a new version does differently, compare traffic per
   version:
   `{ resource.service.name = "orders" && resource.service.version = "<new version>" }`.

## Mitigation

- **A release introduced it:** revert the release commit in the repository
  Argo CD reads from (locally `http://localhost:30232/platform.git`).

  ```sh
  git revert --no-edit <sha> && git push origin HEAD:main
  kubectl -n argocd annotate application workloads argocd.argoproj.io/refresh=hard --overwrite
  kubectl -n orders rollout status deployment/orders
  ```

  The revert can sync while the Deployment is Degraded. The schema is applied
  by an init container, not by a sync hook that would wait for health
  (ADR 8).
- **The limit is too low for a legitimate working set:** raise
  `orders.resources.limits.memory` in `deploy/workloads/values.yaml` with a
  commit. Do not raise it with `kubectl edit`: self-heal reverts it within
  seconds. And raising the limit only delays a leak; it does not fix one.

The alert clears once no OOM restart has happened for a full window (10m
locally, 3m in CI).

## Escalation

- If kills continue on the reverted version, the leak was there before.
  Escalate to the orders service owner with the memory graph and the version
  history.
- If every replica is in `CrashLoopBackOff`, treat it as a page, even though
  this alert is a ticket.

## Related incident

[Incident #3: memory leak](../../incidents/03-memory-leak/README.md)
