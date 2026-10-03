# 6. Compressed SLO windows in CI

Date: 2026-10-03

Status: Accepted

## Context

With real 30-day windows, a severe incident pages within minutes, but the
alerts keep firing long after recovery: the slow page's short window is 30m,
and the tickets' short windows are 2h and 6h. A test that waits for its alerts
to clear would take an hour or more. CI runs six incidents on every push to
`main` and every night, with a target of under 25 minutes.

## Decision

The `ci` overlay (`OVERLAYS="kind ci" make up`) changes the time scale but not
the math. `slos/windows/ci/ci-1h.yaml` uses Sloth custom period windows to
shrink the SLO period from 30 days to 1 hour while keeping every burn-rate
threshold (burn rate = errorBudgetPercent / 100 × period / long window):

| Tier | Burn rate | Local, short / long (30-day SLO) | CI, short / long (1-hour SLO) |
|---|---|---|---|
| Page, fast | 14.4 | 5m / 1h | 30s / 2m |
| Page, slow | 6 | 30m / 6h | 1m / 5m |
| Ticket, fast | 3 | 2h / 1d | 2m / 10m |
| Ticket, slow | 1 | 6h / 3d | 5m / 30m |

- The `slo-rules` Application deploys `slos/generated/ci` when `ci` is one of
  the overlays.
- Prometheus scrapes and evaluates every 5 s and keeps 2 h of data
  (`deploy/overlays/ci/kube-prometheus-stack.yaml`).
- Our own alerts get shorter `for` durations (`alerts/values-ci.yaml`), and the
  HPA scales down after 30 s instead of 300 s (`deploy/workloads/values-ci.yaml`).
- The incident runner detects which rule set is loaded. With real windows it
  allows three times the detection timeout and four times the recovery timeout
  (`Timeouts` in `tests/incidents/platform_lib.py`).

## Consequences

- Incident tests detect and recover in minutes, and promtool verifies both
  rule sets.
- Time to detect in CI is not a production figure, and the README says so.
- A CI tier fires after 48–50% of a one-hour budget is spent; with real
  windows the figure is 2–10% of a 30-day budget. The thresholds match, but
  "error budget remaining" in CI cannot be compared with the real one.
- 30 s windows are noisy: a short burst can page in CI when real windows would
  absorb it.
- Locally, tickets keep firing for hours after a burst. So the baseline check
  before each incident (`tests/incidents/conftest.py`) requires `Watchdog`
  firing, no page and none of the incident's expected alerts, and tolerates
  leftover tickets. The CI smoke job, on a fresh cluster, allows only
  `Watchdog`.
- A real-window page can keep firing for about 30 minutes after recovery. The
  runner records this instead of failing.
