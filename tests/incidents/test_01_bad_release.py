"""Incident #1: a bad release that only the SLO catches.

orders 1.1.0 ships a serializer "refactor" (incidents/01-bad-release/v1.1.0.patch)
that fails on orders without a note. Health checks keep passing, so the rollout
completes; only the availability burn rate notices. The fix is `git revert`.
"""

from platform_lib import (
    Timeouts,
    alert_firing,
    error_ratio,
    rollout_complete,
    wait_for_recovery,
    wait_until,
)

ALERT = "OrdersAvailabilityBurnRate"


def test_bad_release(gitops, report, baseline, compressed):
    t = Timeouts.for_profile(compressed, detect=240, recover=300)
    baseline([(ALERT, "page")], timeout=t.recover)
    r = report("01-bad-release", "a bad release only the SLO catches")

    sha = gitops.set_orders_image(
        "1.1.0",
        "release: orders 1.1.0\n\nShips incidents/01-bad-release/v1.1.0.patch "
        "(serializer whitespace normalisation).",
    )
    r.mark("injected")
    reverted = False
    try:
        # The health checks keep passing, so nothing stops the rollout. With
        # compressed CI windows the page may even fire before it finishes.
        wait_until(
            "1.1.0 fully rolled out, every pod Ready",
            lambda: rollout_complete("orders:1.1.0"),
            t.rollout,
        )
        r.mark("rollout_completed")
        wait_until(
            "availability burn-rate page fires", lambda: alert_firing(ALERT, "page"), t.detect
        )
        r.mark("detected")
        r.facts["rollout_completed_despite_errors"] = True

        gitops.revert(sha)
        reverted = True
        r.mark("mitigated")
    finally:
        if not reverted:
            gitops.revert(sha)  # never leave the bad release behind
    wait_until("1.0.0 rolled back", lambda: rollout_complete("orders:1.0.0"), t.rollout)
    wait_for_recovery(r, ALERT, error_ratio, budget=0.001, compressed=compressed, timeout=t.recover)
