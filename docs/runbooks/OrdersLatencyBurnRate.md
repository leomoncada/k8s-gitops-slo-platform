# OrdersLatencyBurnRate

| | |
|---|---|
| Severity | `page` (fast burn) or `ticket` (slow burn). Same alert name; the `severity` label tells them apart |
| SLO | 99% of orders API requests complete in under 300 ms, over 30 days (error budget: 1% of requests) |
| Source | Sloth: `slos/orders.yaml` generates `slos/generated/{kind,ci}/orders-rules.yaml` |
| Routing | Alertmanager receiver `page` or `ticket`, both pointing to the alert sink |
| Dashboards | `orders: SLOs` at http://localhost:30300/d/orders-slo and `orders: service` at http://localhost:30300/d/orders-service |

## Meaning

Too many requests are taking longer than 300 ms. A request is "slow" when it
falls outside the `le="0.3"` bucket of `http_request_duration_seconds`. The
bucket boundary is exactly the SLO threshold.

The alert is multiwindow and multi-burn-rate. A burn rate of 1 spends the
budget in exactly 30 days. A burn rate of 14.4 spends 2% of the budget in one
hour. Each tier fires only when both of its windows are above the threshold:
the long window shows the burn is significant, and the short window shows it
is still happening and lets the alert reset soon after a fix.

| Tier | Burn rate | Share of slow requests that triggers it | Windows locally, short / long | Windows in CI, short / long |
|---|---|---|---|---|
| page, fast | 14.4 | 14.4% | 5m / 1h | 30s / 2m |
| page, slow | 6 | 6% | 30m / 6h | 1m / 5m |
| ticket, fast | 3 | 3% | 2h / 1d | 2m / 10m |
| ticket, slow | 1 | 1% | 6h / 3d | 5m / 30m |

- `severity=page`: act now.
- `severity=ticket`: a slow leak to fix during working hours.

In CI the SLO period is one hour, with the same thresholds
(`slos/windows/ci/ci-1h.yaml`, ADR 6). Locally, Prometheus keeps 12 h of data,
so the 1d and 3d windows cover at most the last 12 h.

## Impact

Users wait. Requests still succeed, unless they cross a timeout: the pool wait
(2 s), the statement timeout (3 s) and the k6 client timeout (2 s). At that
point latency turns into errors and `OrdersAvailabilityBurnRate` follows.

All pods stay Ready during a slow database. That is deliberate (ADR 2): a
readiness check against Postgres would turn this degradation into an outage.

## Diagnosis

1. Size the problem and find where it is, in Prometheus
   (http://localhost:30090) or Grafana Explore. Explore requires logging in
   (admin/admin locally).

   ```promql
   # Share of slow requests over the last 5 minutes
   slo:sli_error:ratio_rate5m{sloth_slo="requests-latency"}

   # p99 by route
   histogram_quantile(0.99, sum by (le, route) (rate(http_request_duration_seconds_bucket{job="orders"}[5m])))

   # Share slower than 300 ms, by route
   1 - sum by (route) (rate(http_request_duration_seconds_bucket{job="orders", le="0.3"}[5m]))
       / sum by (route) (rate(http_request_duration_seconds_count{job="orders"}[5m]))
   ```

   If every route is slow, suspect a shared dependency (Postgres) or
   saturation. If only one route is slow, suspect that route's query or code.

2. Rule out saturation. orders has a CPU request but no CPU limit, so there is
   no throttling. A CPU-bound process still queues requests, though.

   ```promql
   sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="orders", container="orders"}[5m]))
   kube_horizontalpodautoscaler_status_current_replicas{namespace="orders", horizontalpodautoscaler="orders"}
   sum by (scenario) (rate(k6_http_reqs_total[1m]))   # baseline vs extra load
   ```

   If the HPA is at its maximum, see [OrdersHPAMaxedOut](OrdersHPAMaxedOut.md).

3. Use traces to see where the time goes. In Grafana Explore, choose the Tempo
   datasource and run TraceQL:

   ```traceql
   { resource.service.name = "orders" && kind = server && duration > 300ms }
   { resource.service.name = "orders" && kind = client && duration > 350ms }
   ```

   - `kind = client` spans are the psycopg database calls. If slow server spans
     are mostly made of slow client spans, the time is spent in Postgres or on
     the network to it.
   - A gap at the start of a server span, before the first database span, is
     time spent waiting for a pooled connection.
   - If server spans are slow but their client spans are fast, the time is
     spent inside the process.

   The same search without Grafana:

   ```sh
   curl -sG http://localhost:30320/api/search \
     --data-urlencode 'q={ resource.service.name = "orders" && kind = client && duration > 350ms }' \
     --data-urlencode limit=5
   ```

4. Read slow requests in Loki and jump to their traces through the `trace_id`
   link.

   ```logql
   {k8s_namespace_name="orders"} | json | event="request" | duration_ms > 300
   sum by (route) (count_over_time({k8s_namespace_name="orders"} | json | event="request" | duration_ms > 300 [5m]))
   {k8s_namespace_name="orders"} | json | event="database_unavailable"
   ```

5. Find out whether the database itself or the network to it is slow.

   ```sh
   # Leftover chaos experiments
   kubectl get networkchaos -A
   kubectl -n orders describe networkchaos slow-postgres

   # Inside Postgres: are queries slow or waiting?
   kubectl -n orders exec postgres-0 -- psql -U orders -d orders -c \
     "select state, wait_event_type, wait_event, now() - query_start as age, left(query, 60) as query
        from pg_stat_activity where datname = 'orders' order by age desc nulls last limit 10"

   # From an orders pod: TCP connect time to Postgres
   kubectl -n orders exec deploy/orders -c orders -- python -c \
     "import socket,time; t=time.perf_counter(); socket.create_connection(('postgres', 5432), 5).close(); print(f'{(time.perf_counter()-t)*1000:.0f} ms')"
   ```

   If queries are short inside Postgres but connecting takes hundreds of
   milliseconds from orders, the delay is on the network, not in the database.
   `kubectl exec` does not cross the pod network, so it keeps working during
   network chaos.

6. Check whether a release is involved: `sum by (version) (orders_build_info{job="orders"})`,
   and the `workloads` History in Argo CD (http://localhost:30080).

## Mitigation

- **Leftover network chaos:**
  `kubectl -n orders delete networkchaos slow-postgres`, or
  `kubectl delete -f incidents/02-slow-dependency/network-delay.yaml`. The
  experiment also expires on its own after its 30m `duration`.
- **A release made it slow:** revert the release commit in the repository Argo
  CD reads from (locally `http://localhost:30232/platform.git`):

  ```sh
  git clone http://localhost:30232/platform.git /tmp/platform && cd /tmp/platform
  git log --oneline -- deploy/workloads/values.yaml
  git revert --no-edit <sha> && git push origin HEAD:main
  ```

  Never use `kubectl edit` on the Deployment; self-heal undoes it.
- **CPU saturation at the HPA ceiling:** follow
  [OrdersHPAMaxedOut](OrdersHPAMaxedOut.md). The fix is a commit that raises
  `orders.hpa.maxReplicas`.
- **A runaway query in Postgres:** cancel it with
  `select pg_cancel_backend(<pid>)`, using the pid from `pg_stat_activity`.
  Then find out where it came from.
- Do not restart orders pods to fix a slow database. They are not the cause,
  and new pods must reach Postgres from their schema init container before
  they can start (ADR 8).

Confirm recovery with the 5m slow ratio back under 1%. As with availability,
the slow page can keep firing for up to about 30 minutes locally after a
severe burn, and tickets for hours.

## Escalation

- Postgres itself is slow (long `pg_stat_activity` ages, locks): escalate to
  whoever owns the database.
- The network is slow and there is no chaos experiment: escalate to the
  platform team (node, CNI).
- The time is spent inside the process, with no load increase and no release:
  escalate to the orders service owner, with trace IDs.

## Related incident

[Incident #2: slow dependency](../../incidents/02-slow-dependency/README.md).
Load beyond the HPA ceiling can also cause this alert; see
[incident #6: traffic spike](../../incidents/06-traffic-spike/README.md).
