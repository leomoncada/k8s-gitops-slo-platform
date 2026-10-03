# OrdersMetricsAbsent

| | |
|---|---|
| Severity | `page` |
| Source | Our own rule, `alerts/templates/rules.yaml` (group `orders`) |
| Fires after | 2m without a healthy target locally, 1m in CI (`metricsAbsentFor` in `alerts/values*.yaml`) |
| Dashboard | `orders: service` at http://localhost:30300/d/orders-service (it goes empty, which is the symptom) |

## Meaning

Prometheus has no orders target that is up:

```promql
absent(up{job="orders"} == 1)
```

Every SLO alert is computed from `http_requests_total` and
`http_request_duration_seconds` scraped from that job. Without them, the
burn-rate expressions return no data, and no data never fires. So this alert
pages for "blind", which would otherwise look like "healthy". A single healthy
target is enough to keep it quiet. A promtool test proves both cases
(`alerts/tests/platform-alerts.test.yaml`).

## Impact

At best, you are blind: the service may be fine, but no SLO alert can fire.
At worst, the service is completely down. Find out which one first.

## Diagnosis

1. Is orders actually serving? Ask the service, and ask the clients.

   ```sh
   curl -s -o /dev/null -w '%{http_code}\n' 'http://localhost:30800/orders?limit=1'
   curl -s http://localhost:30800/metrics | head -5
   ```

   ```promql
   # k6 baseline traffic, as clients see it
   sum by (expected_response) (rate(k6_http_reqs_total{scenario="baseline"}[1m]))
   ```

   If both curl calls work and k6 sees successful requests, the service is up
   and the problem is in scraping (step 3).

2. Are there pods at all?

   ```sh
   kubectl -n orders get deploy,rs,pods -l app=orders -o wide
   kubectl -n orders get hpa orders
   kubectl -n orders get events --sort-by=.lastTimestamp | tail -20
   ```

   ```promql
   kube_deployment_spec_replicas{namespace="orders", deployment="orders"}
   kube_deployment_status_replicas_available{namespace="orders", deployment="orders"}
   ```

   Common causes:

   - **The Deployment was scaled to 0.** The HPA does nothing when a Deployment
     has 0 replicas, and Argo CD ignores replicas (ADR 11), so nothing brings
     the pods back.
   - **Every pod is crash-looping.** See
     [OrdersContainerOOMKilled](OrdersContainerOOMKilled.md) if the reason is
     OOM.
   - **Pods are stuck in `Init`.** The schema init container cannot reach
     Postgres (ADR 8). Check
     `kubectl -n orders logs <pod> -c schema` and
     `kubectl -n orders get pod postgres-0`.
   - **`ImagePullBackOff`.** The image tag in Git was never loaded into kind;
     there is no registry.

3. Is Prometheus finding the target? Open
   http://localhost:30090/targets?search=orders and check that the endpoint is
   discovered and its last scrape error.

   ```sh
   kubectl -n orders get servicemonitor orders -o yaml
   kubectl -n orders get svc orders --show-labels
   kubectl -n orders get endpointslices -l kubernetes.io/service-name=orders
   ```

   The ServiceMonitor selects `app: orders` and scrapes the port named `http`
   at `/metrics`. A change to the Service labels or port name breaks the
   scrape silently. The `job` label comes from the Service name, so renaming
   the Service also breaks this alert's selector.

4. Did Git change it? In Argo CD (http://localhost:30080), open `workloads`:
   check its sync and health status, **History and rollback** for the latest
   revision, and the diff for the ServiceMonitor, Service or Deployment.

5. Check the logs of the last process starts:

   ```logql
   {k8s_namespace_name="orders"} | json | event="startup"
   ```

   If nothing at all arrives from Prometheus, check whether Watchdog
   notifications have stopped. If Prometheus itself is down, this alert cannot
   fire either; see [KubeNodeDown](KubeNodeDown.md) for the infra node.

Traces do not help here. If no pod runs, there are no spans.

## Mitigation

- **Scaled to 0:** restore the starting replica count.

  ```sh
  kubectl -n orders scale deployment/orders --replicas=3
  ```

  This is the one imperative change this repository accepts. Replicas are not
  under Git's control (ADR 11), so it is not drift, and the HPA takes over
  again once replicas are above 0. Find out who scaled it to 0.
- **A bad release, or a broken Service or ServiceMonitor in Git:** revert the
  commit in the repository Argo CD reads from (locally
  `http://localhost:30232/platform.git`) with
  `git revert --no-edit <sha> && git push origin HEAD:main`. Never use
  `kubectl edit`.
- **Image missing in kind:** run `scripts/build-images.sh <version>`, then
  `kind load docker-image orders:<version> --name slo-platform`.
- **Init container waiting for Postgres:** fix Postgres first. The pods start
  as soon as it answers.

## Escalation

This is a page. If the service is down and the cause is not one of the above
within a few minutes, escalate to the orders service owner. If Postgres is
down, escalate to the database owner. If Prometheus or service discovery is
broken while orders is serving, escalate to the platform team: until it is
fixed, no SLO alert can fire.

## Related incident

There is no dedicated incident. Both the firing case and the quiet case are
proven by promtool tests in `alerts/tests/platform-alerts.test.yaml`. The
closest scenario is [incident #3: memory leak](../../incidents/03-memory-leak/README.md)
if every replica ends up in an OOM loop.
