# Incident 1: bad release

| | |
|---|---|
| Expected alert | `OrdersAvailabilityBurnRate`, `severity=page` |
| Runbook | [OrdersAvailabilityBurnRate](../../docs/runbooks/OrdersAvailabilityBurnRate.md) |
| Test | `tests/incidents/test_01_bad_release.py` |
| Run | `make incident-1` |

## What happens

orders `1.1.0` ships a serializer "refactor"
([`v1.1.0.patch`](v1.1.0.patch)) that collapses whitespace in the `note`
field. It calls `.split()` on a note that can be null, so every response that
contains a null-note order fails with a 500. That covers creating such an
order, reading one, and any list page that includes one. The baseline traffic
leaves about 30% of new orders without a note.

`/healthz` and `/readyz` keep passing, so the rollout completes normally. Only
the availability SLO notices.

## Injection

The test commits the release to the in-cluster repository, the way a release
pipeline would.

1. Clone `http://localhost:30232/platform.git`.
2. Change `image: orders:1.0.0` to `image: orders:1.1.0` in
   `deploy/workloads/values.yaml`.
3. Commit with the message "release: orders 1.1.0" and push to `main`.
4. Force an Argo CD refresh of `workloads`.

The `orders:1.1.0` image is built from the patch by `scripts/build-images.sh`
and loaded into kind by `make up`.

## What the test asserts

1. Clean baseline: `Watchdog` is firing, and no page is firing (which includes
   this incident's alert).
2. Every replica runs `orders:1.1.0`, is Ready, and no old pod is left: the
   rollout passed its health checks.
3. The page had not fired before the rollout completed.
4. `OrdersAvailabilityBurnRate` fires with `severity=page` within the
   detection timeout.
5. Remediation: `git revert` of the release commit, pushed to the same
   repository. `orders:1.0.0` rolls out again.
6. Recovery: the 5xx ratio over the last minute is back at or below 0.1%.
   - With CI windows, the page must also clear.
   - With real windows, the page clearing is recorded rather than required,
     because the slow page can last about 30 minutes ([ADR 6](../../docs/adr/0006-compressed-slo-windows-in-ci.md)).

Clean baseline means `Watchdog` firing, no page, and none of this incident's
expected alerts. Tickets left over from earlier incidents are tolerated,
because with real windows a slow-burn ticket lasts hours.

## Run it

```sh
make up            # once; OVERLAYS="kind ci" make up for compressed windows
make incident-1
```

With real windows, the runner allows three times the detection timeout and
four times the recovery timeout. The report is written to
`reports/incidents/01-bad-release.json` and summarized in
`reports/summary.md`. Time to detect runs from injection to the page; time to
recover runs from detection until the SLI is back within its objective. For
measured times, see the latest CI run of the `incidents` workflow.
