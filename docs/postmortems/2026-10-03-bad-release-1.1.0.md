# Postmortem: orders 1.1.0 fails on orders without a note

Blameless: this describes what the system and the process allowed. Numbers come
from `reports/incidents/01-bad-release.json` and Prometheus, from a local run
with the CI overlay (compressed SLO windows, [ADR 6](../adr/0006-compressed-slo-windows-in-ci.md)).

| | |
|---|---|
| Date | 2026-10-03 |
| Incident | [`incidents/01-bad-release/`](../../incidents/01-bad-release/README.md) |
| Severity | page (`OrdersAvailabilityBurnRate`) |
| Status | resolved |
| Time to detect | 20 s from the release commit to the page |
| Time to recover | 61 s from the page to the SLI back within objective |
| Error budget consumed | 0.15% of the 30-day availability budget |

## Summary

Release 1.1.0 changed how orders are serialized and raised on every order whose
optional `note` is null. The release passed its health checks and rolled out to
all three replicas in 10 seconds. The availability burn-rate alert paged 10
seconds later. A `git revert` of the release commit rolled the service back to
1.0.0, and the error ratio returned to zero within a minute.

## Impact

- 38 of 908 requests in the incident window failed with a 500 (4.2%). While
  1.1.0 was serving, the failure rate was much higher: list requests fail
  whenever any of the 20 most recent orders has a null note, and about 30% of
  orders do.
- 0.15% of the 30-day error budget (at the 10 req/s baseline, the budget is
  about 25,900 failed requests per 30 days).

## Timeline (UTC)

| Time | Event |
|---|---|
| 15:48:06 | Release commit `release: orders 1.1.0` pushed to the repository Argo CD reads |
| 15:48:16 | Rollout complete: every pod on 1.1.0 and Ready |
| 15:48:26 | `OrdersAvailabilityBurnRate` page fires |
| 15:48:27 | `git revert` of the release commit pushed |
| 15:49:27 | 5xx ratio over the last minute back under 0.1% |
| 15:49:32 | Page clears |

## Root cause

`serialize_order` was "refactored" to normalise whitespace with
`row["note"].strip()`, which raises `AttributeError` when `note` is null
(`incidents/01-bad-release/v1.1.0.patch`). The existing unit tests in
`app/tests` cover a null note and fail against the patched code: the release
reached production without running them.

## Detection

Liveness and readiness check the process, not the business logic, so both kept
passing and nothing stopped the rollout. That is by design: readiness must not
depend on downstream behaviour ([ADR 2](../adr/0002-readiness-does-not-depend-on-database.md)).
The only signal that could catch a partial failure was the SLO. A sudden,
large burn like this one is exactly what the page tier of a multiwindow,
multi-burn-rate alert exists for.

## What went well

- The SLO caught a failure every health check missed, within seconds.
- Rollback was a `git revert`: no `kubectl edit`, no guessing which image was
  previously deployed, and Git history shows exactly what happened.
- Recovery did not depend on anyone remembering the previous state.

## What went badly

- The release reached the cluster without the unit tests that would have
  caught it.
- All three replicas switched at once. Every user got the broken version
  before any signal could react.

## Action items

| Action | Type | Status |
|---|---|---|
| Release images only from CI after `pytest app/tests` passes | prevent | done for this repo (`ci.yml`) |
| Canary releases with Argo Rollouts: ship to 10% of traffic and roll back automatically on the availability burn rate (incident #7, DESIGN.md section 13) | mitigate | future work |
| Keep the null-note test in the suite; it is the regression test for this incident | prevent | done |
