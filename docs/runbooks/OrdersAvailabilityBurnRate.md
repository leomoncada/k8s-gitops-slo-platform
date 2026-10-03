# OrdersAvailabilityBurnRate

| | |
|---|---|
| Severity | `page` (fast burn) or `ticket` (slow burn). Same alert name; the `severity` label tells them apart |
| SLO | 99.9% of orders API requests do not return a 5xx, over 30 days (error budget: 0.1% of requests) |
| Source | Sloth: `slos/orders.yaml` generates `slos/generated/{kind,ci}/orders-rules.yaml` |
| Routing | Alertmanager receiver `page` or `ticket`, both pointing to the alert sink |
| Dashboards | `orders: SLOs` at http://localhost:30300/d/orders-slo and `orders: service` at http://localhost:30300/d/orders-service |

## Meaning

orders is answering enough requests with a 5xx that, if this continues, the
30-day error budget will run out early. 4xx responses do not count, because
they are the client's fault.

The alert is multiwindow and multi-burn-rate. A burn rate of 1 spends the
budget in exactly 30 days. A burn rate of 14.4 spends 2% of the budget in one
hour. Each tier fires only when both of its windows are above the threshold:
the long window shows the burn is significant, and the short window shows it
is still happening. The short window also lets the alert reset soon after a
fix.

| Tier | Burn rate | 5xx ratio that triggers it | Windows locally, short / long | Windows in CI, short / long |
|---|---|---|---|---|
| page, fast | 14.4 | 1.44% | 5m / 1h | 30s / 2m |
| page, slow | 6 | 0.6% | 30m / 6h | 1m / 5m |
| ticket, fast | 3 | 0.3% | 2h / 1d | 2m / 10m |
| ticket, slow | 1 | 0.1% | 6h / 3d | 5m / 30m |

- `severity=page`: the budget is going fast and someone must act now.
- `severity=ticket`: the budget is leaking slowly. Fix it during working
  hours.
- A severe incident fires both tiers at once.

In CI the SLO period is one hour and every window shrinks with it, but the
thresholds are the same (`slos/windows/ci/ci-1h.yaml`, ADR 6). Locally,
Prometheus keeps 12 h of data, so the 1d and 3d windows cover at most the last
12 h.

## Impact

Users are getting errors. At the fast-page threshold, at least 1.44% of
requests fail. A bad release can fail far more: every request that serializes
a record the new code cannot handle, including list pages that contain such a
record.

This SLI is measured on the server. Requests that never reach a server do not
appear in it, such as requests to pods on a dead node or to a pod that was just
OOM-killed. The k6 client-side metric below covers that gap.

## Diagnosis

1. Size the problem in Prometheus (http://localhost:30090) or Grafana Explore.
   Explore requires logging in (admin/admin locally); the anonymous viewer can
   only see dashboards.

   ```promql
   # 5xx ratio over the last 5 minutes (exists in both rule sets)
   slo:sli_error:ratio_rate5m{sloth_slo="requests-availability"}

   # Budget left in the SLO period (1 = untouched, below 0 = exhausted)
   slo:period_error_budget_remaining:ratio{sloth_slo="requests-availability"}

   # Which routes and status codes
   sum by (route, status) (rate(http_requests_total{job="orders", status=~"5.."}[5m]))

   # One pod or all of them?
   sum by (pod) (rate(http_requests_total{job="orders", status=~"5.."}[5m]))
     / sum by (pod) (rate(http_requests_total{job="orders"}[5m]))
   ```

2. Check what changed. Most availability burns start with a release.

   ```promql
   # Running version, counted per pod
   sum by (version) (orders_build_info{job="orders"})
   ```

   ```sh
   kubectl -n orders rollout history deployment/orders
   kubectl -n orders get pods -l app=orders \
     -o custom-columns=NAME:.metadata.name,IMAGE:.spec.containers[0].image,READY:.status.containerStatuses[0].ready,NODE:.spec.nodeName
   git clone http://localhost:30232/platform.git /tmp/platform && cd /tmp/platform
   git log --oneline -5 -- deploy/workloads/values.yaml
   ```

   In Argo CD (http://localhost:30080, read-only without logging in), open the
   `workloads` application and go to **History and rollback** to see which Git
   revision is deployed and when it synced. The CLI equivalent, after
   `argocd login localhost:30080 --plaintext`, is `argocd app history workloads`.

   A completed rollout with every pod Ready does not clear a release.
   Readiness does not exercise business paths (ADR 2).

3. Read the errors in Loki (Grafana Explore, Loki datasource).

   ```logql
   {k8s_namespace_name="orders"} | json | event="request" | status >= 500
   sum by (route) (count_over_time({k8s_namespace_name="orders"} | json | event="request" | status >= 500 [5m]))
   {k8s_namespace_name="orders"} |= "Traceback"
   {k8s_namespace_name="orders"} | json | event=~"database_unavailable|database_error"
   ```

   - A traceback points at code, usually a release.
   - `database_unavailable` (a 503) points at Postgres: a pool wait over 2 s, a
     connection failure, or a statement over the 3 s `statement_timeout`. In
     that case, also follow the Postgres checks in
     [OrdersLatencyBurnRate](OrdersLatencyBurnRate.md).
   - Every access log line carries a `trace_id`. Its link opens the trace in
     Tempo.

4. Find example traces in Tempo (Grafana Explore, Tempo datasource, TraceQL).

   ```traceql
   { resource.service.name = "orders" && kind = server && status = error }
   { resource.service.name = "orders" && resource.service.version = "<new version>" && status = error }
   ```

5. Compare with what clients see. The k6 baseline traffic pushes client-side
   metrics, which also count requests that never reached a server.

   ```promql
   sum(rate(k6_http_reqs_total{scenario="baseline", expected_response="false"}[5m]))
     / sum(rate(k6_http_reqs_total{scenario="baseline"}[5m]))
   ```

6. Check what else is firing at http://localhost:30093. `KubeNodeDown` or
   `OrdersContainerOOMKilled` point to a different cause; follow those
   runbooks.

## Mitigation

**Bad release** (the errors started with a rollout, tracebacks appear, a new
version is running). Revert the release commit in the repository Argo CD
reads from. Locally, that is the in-cluster Git server; in phase 2 it is
GitHub, through a pull request.

```sh
git clone http://localhost:30232/platform.git /tmp/platform && cd /tmp/platform
git log --oneline -- deploy/workloads/values.yaml   # find the release commit
git revert --no-edit <sha>
git push origin HEAD:main
# Optional: skip the 20 s poll
kubectl -n argocd annotate application workloads argocd.argoproj.io/refresh=hard --overwrite
kubectl -n orders rollout status deployment/orders
```

- Do not use `kubectl edit` or `kubectl set image` on the Deployment. Argo CD
  self-heal restores Git's version within seconds.
- Do not use `argocd app rollback`. Argo CD refuses it while automated sync is
  on, and Git would still name the bad version.

**Database errors** (503s, `database_unavailable`): check for a leftover chaos
experiment with `kubectl get networkchaos -A`, check that
`kubectl -n orders get pod postgres-0` is Running, and see
[OrdersLatencyBurnRate](OrdersLatencyBurnRate.md).

**A single pod returns the errors**: delete it with
`kubectl -n orders delete pod <pod>`. The ReplicaSet replaces it, and the
PodDisruptionBudget keeps two replicas available.

**Confirm recovery** with the 5m ratio back under 0.1%:
`slo:sli_error:ratio_rate5m{sloth_slo="requests-availability"}`. Do not use
the alert to judge whether the fix worked.

- Locally, the fast page clears within about 5 minutes.
- The slow page can keep firing for up to about 30 minutes after a severe
  burn, because its short window is 30m.
- Tickets can last hours.
- In CI, everything clears within minutes.

## Escalation

- If the page is not acknowledged, or the cause is not a release: escalate to
  the orders service owner (`owner: platform` on the alert).
- If the 5xx ratio does not drop once the reverted version has fully rolled
  out, the release was not the cause. Escalate with the evidence: routes,
  status codes and a few trace IDs.
- For Postgres-related 503s, escalate to whoever owns the database. It is a
  single instance with no HA and no backups (ADR 9).
- For the postmortem, record the budget consumed from
  `slo:period_error_budget_remaining:ratio`.

## Related incident

[Incident #1: bad release](../../incidents/01-bad-release/README.md). For the
gap between server-side and client-side failures, see
[incident #5: node failure](../../incidents/05-node-failure/README.md).
