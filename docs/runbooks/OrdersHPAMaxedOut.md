# OrdersHPAMaxedOut

| | |
|---|---|
| Severity | `ticket` |
| Source | Our own rule, `alerts/templates/rules.yaml` (group `orders`) |
| Fires after | 2m at the maximum locally, 30s in CI (`hpaMaxedOutFor` in `alerts/values*.yaml`) |
| Dashboard | `orders: service` at http://localhost:30300/d/orders-service (panels "Replicas" and "CPU by pod") |

## Meaning

The orders HPA has run at its maximum replica count for the hold time:

```promql
kube_horizontalpodautoscaler_status_current_replicas{namespace="orders", horizontalpodautoscaler="orders"}
  >= kube_horizontalpodautoscaler_spec_max_replicas{namespace="orders", horizontalpodautoscaler="orders"}
```

The HPA keeps orders between 3 and 6 replicas, targeting 60% of the CPU
request (`orders.hpa` in `deploy/workloads/values.yaml`). At 6 there is no
headroom left. kube-prometheus-stack's `KubeHpaMaxedOut` covers the same
condition after 15 minutes; this rule warns sooner.

## Impact

None by itself. It is a capacity warning. If load keeps rising, CPU saturates,
requests queue, and `OrdersLatencyBurnRate` follows. Six replicas spread over
two workers (`maxSkew: 1`) means three per worker, so the workers' capacity is
the next limit.

## Diagnosis

1. Is the load real, and where does it come from? Use Prometheus
   (http://localhost:30090) or Grafana Explore (login admin/admin).

   ```promql
   # Server-side request rate by route
   sum by (route) (rate(http_requests_total{job="orders"}[1m]))

   # Client-side rate by k6 scenario: "baseline" is constant traffic,
   # anything else (for example "spike") is extra load
   sum by (scenario) (rate(k6_http_reqs_total[1m]))

   # CPU used against CPU requested (the HPA target is 60%)
   sum(rate(container_cpu_usage_seconds_total{namespace="orders", container="orders"}[2m]))
     / sum(kube_pod_container_resource_requests{namespace="orders", container="orders", resource="cpu"})

   # Is it hurting users yet?
   slo:sli_error:ratio_rate5m{sloth_slo="requests-latency"}

   # Replicas that could not be scheduled
   sum(kube_pod_status_phase{namespace="orders", phase="Pending"})
   ```

2. Ask the cluster directly.

   ```sh
   kubectl -n orders get hpa orders
   kubectl -n orders describe hpa orders     # conditions (ScalingLimited) and scaling events
   kubectl -n orders top pods
   kubectl top nodes
   kubectl -n orders get jobs                # load generators applied by hand, e.g. traffic-spike
   ```

3. Check the logs for request volume and slow requests.

   ```logql
   sum by (route) (count_over_time({k8s_namespace_name="orders"} | json | event="request" [1m]))
   {k8s_namespace_name="orders"} | json | event="request" | duration_ms > 300
   ```

4. Use traces to tell CPU-bound from database-bound. If server spans are slow
   while their database (client) spans stay fast, the process is saturated.

   ```traceql
   { resource.service.name = "orders" && kind = server && duration > 300ms }
   ```

## Mitigation

- **Legitimate, sustained load:** raise `orders.hpa.maxReplicas` in
  `deploy/workloads/values.yaml` with a commit to the repository Argo CD reads
  from (locally `http://localhost:30232/platform.git`). Check first that the
  workers have room, using `kubectl top nodes` and the Pending pods count.
- **Unwanted load:** stop the source. The incident #6 load generator is a Job
  applied outside Git, so remove it with
  `kubectl delete -f incidents/06-traffic-spike/spike.yaml`.
- Do not `kubectl scale` the Deployment: the HPA owns replicas (ADR 11) and
  overrides the change. Do not edit the HPA by hand either: self-heal restores
  it from Git.

The alert resolves only after the HPA scales below its maximum. That takes at
least the scale-down stabilization window after the load drops: 300 s locally,
30 s in CI (`scaleDownStabilizationSeconds`).

## Escalation

- If the latency SLO starts burning while the HPA is at its ceiling, act on
  `OrdersLatencyBurnRate` (page) first.
- If worker capacity is exhausted (Pending pods, nodes near full), escalate to
  the platform team for more nodes. A higher `maxReplicas` alone will not help.
- If the load is unexpected and not a known test, escalate to the orders
  service owner to identify the client.

## Related incident

[Incident #6: traffic spike](../../incidents/06-traffic-spike/README.md)
