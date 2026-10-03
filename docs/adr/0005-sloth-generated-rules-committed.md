# 5. Sloth for SLOs; generated rules committed and verified in CI

Date: 2026-10-03

Status: Accepted

## Context

Multiwindow, multi-burn-rate alerts (from the Google SRE workbook) need a
recording rule for each SLI over several windows, plus alert expressions that
pair those windows with thresholds. For our two SLOs that comes to 446 lines
of PromQL (`slos/generated/kind/orders-rules.yaml`). Written by hand, rules
like these are easy to get subtly wrong and tedious to review.

## Decision

- Both SLOs are declared once, in `slos/orders.yaml` (Sloth
  `PrometheusServiceLevel`), over 30 days:
  - availability: 99.9%. 5xx responses are bad; 4xx are not. The error query
    ends in `or vector(0)`, so the ratio is 0 rather than "no data" when there
    are no 5xx at all.
  - latency: 99% of requests under 300 ms, read from the 0.3 s histogram
    bucket.
- The alerts are named `OrdersAvailabilityBurnRate` and
  `OrdersLatencyBurnRate`, each with a `severity=page` tier and a
  `severity=ticket` tier.
- `make slos` (`scripts/generate-slos.sh`) runs Sloth v0.16.0 in Docker and
  writes `slos/generated/kind/` (real windows) and `slos/generated/ci/`
  (compressed windows, ADR 6). The `slo-rules` Argo CD Application deploys one
  set or the other.
- The generated PrometheusRule files are committed. `scripts/lint.sh` (CI
  `lint` job) regenerates them and fails on any difference, so a hand edit or a
  forgotten regeneration fails the pull request.
- `scripts/test-alerts.sh` (CI `alert-tests` job) runs `promtool test rules`
  on both sets with synthetic series (`alerts/tests/slo.test.yaml`,
  `alerts/tests/slo-kind.test.yaml`). The tests check that 30% errors page,
  zero errors stay quiet, slow requests page on latency, and 0.5% slow
  requests stay within the 1% budget.

## Consequences

- Reviewers read a short spec instead of generated PromQL, and the diff of the
  generated files shows exactly what changes in Prometheus.
- What runs in the cluster is what is in Git and what promtool tested. Nothing
  is generated at deploy time.
- Generated files make diffs noisy, and regenerating them needs Docker.
- The generated rule names (`slo:sli_error:ratio_rate5m`,
  `slo:period_error_budget_remaining:ratio`) tie the dashboards and runbooks to
  Sloth.
- Locally, the 30-day windows exist only on paper. Prometheus keeps 12 h of
  data (`deploy/overlays/common/kube-prometheus-stack.yaml`), so the 1d and 3d
  ticket windows and the 30-day budget see at most the last 12 h.
- The diff check needs at least one commit; before that, `scripts/lint.sh`
  skips it.
