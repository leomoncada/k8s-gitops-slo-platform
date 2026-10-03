# 11. The HPA owns replicas; Argo CD ignores /spec/replicas

Date: 2026-10-03

Status: Accepted

## Context

orders has an HPA that keeps it between 3 and 6 replicas at 60% CPU, and Argo
CD runs with automated sync and self-heal. The Deployment manifest says
`replicas: 3`. When the HPA scales to 5, the live object no longer matches
Git. Self-heal sets it back to 3, the HPA scales it up again, and the two fight
forever.

## Decision

- The HPA owns `/spec/replicas`. The `workloads` Application ignores that
  field on the `orders` Deployment (`ignoreDifferences` in
  `deploy/platform/templates/applications.yaml`). The `RespectIgnoreDifferences=true`
  sync option makes sure a sync does not reset it either.
- `replicas: 3` stays in `deploy/workloads/templates/orders.yaml`, but only as
  the starting value for the first sync. The settings that matter are
  `orders.hpa.minReplicas`, `maxReplicas`, `cpuUtilization` and
  `scaleDownStabilizationSeconds` in `deploy/workloads/values.yaml`. The
  stabilization window is 300 s there and 30 s in
  `deploy/workloads/values-ci.yaml`.
- Running at the ceiling raises an alert instead of staying silent:
  `OrdersHPAMaxedOut` in `alerts/templates/rules.yaml`.

## Consequences

- Autoscaling and GitOps coexist. Incident #6 scales orders to six replicas
  without Argo CD reporting drift.
- Changing `orders.replicas` in Git has no effect after the first sync, which
  can surprise someone reading the chart.
- Argo CD no longer detects replica drift. `kubectl scale --replicas=0` would
  cause a full outage that neither Argo CD nor the HPA repairs, because an HPA
  does not act on a Deployment that has been scaled to zero.
  `OrdersMetricsAbsent` pages in that case, and its runbook restores the
  replicas with `kubectl scale`. That is the one imperative change this
  repository accepts.
- This is also why incident #4 changes an env var and deletes the
  PodDisruptionBudget instead of scaling to zero: scaling to zero would test
  neither self-heal nor the HPA.
