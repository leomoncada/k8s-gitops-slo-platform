import os
import subprocess
import sys

import pytest

from platform_lib import (
    ROOT,
    GitOps,
    Report,
    alert_firing,
    compressed_windows,
    describe,
    firing_alerts,
    narrate,
    wait_until,
)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if call.when == "call":
        item.rep_call = outcome.get_result()


@pytest.fixture(scope="session")
def compressed() -> bool:
    value = compressed_windows()
    narrate(f"SLO windows: {'compressed (CI, ADR 6)' if value else 'real 30-day windows'}")
    return value


@pytest.fixture
def gitops():
    repo = GitOps()
    yield repo
    repo.close()


@pytest.fixture
def report(request):
    reports = []

    def start(incident: str, title: str) -> Report:
        narrate(f"=== {incident}: {title}")
        narrate(
            "watch: http://localhost:30300/d/orders-slo and http://localhost:30300/d/orders-service"
        )
        r = Report(incident, title)
        reports.append(r)
        return r

    yield start
    passed = getattr(request.node, "rep_call", None) is not None and request.node.rep_call.passed
    for r in reports:
        r.save(passed)


@pytest.fixture
def baseline():
    """Every incident starts from a clean baseline: the alerting pipeline is
    alive (Watchdog fires) and no page, nor the alert this incident expects
    (name and severity), is firing. Tickets left by an earlier incident are
    reported, not blocking: with real windows a slow-burn ticket legitimately
    lasts hours.

    `expected` holds (alertname, severity) pairs; severity None matches any."""

    def require(expected: list[tuple[str, str | None]], timeout: float) -> None:
        wait_until(
            "Watchdog fires (alerting pipeline alive)",
            lambda: alert_firing("Watchdog"),
            180,
        )

        def is_expected(alert: dict) -> bool:
            labels = alert["labels"]
            return any(
                labels.get("alertname") == name and severity in (None, labels.get("severity"))
                for name, severity in expected
            )

        def clean() -> bool:
            blocking = [
                a
                for a in firing_alerts()
                if a["labels"].get("severity") == "page" or is_expected(a)
            ]
            if blocking:
                narrate(f"  still firing: {describe(blocking)}")
            return not blocking

        wait_until(f"clean baseline (no page, none of {expected})", clean, timeout, interval=10)
        tolerated = [a for a in firing_alerts() if a["labels"].get("alertname") != "Watchdog"]
        if tolerated:
            narrate(f"tolerated, left by earlier incidents: {describe(tolerated)}")

    return require


def pytest_sessionfinish(session):
    """Writes reports/summary.md (and the GitHub step summary) from every report."""
    script = ROOT / "scripts" / "summarize-incidents.py"
    text = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, check=False
    ).stdout
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports" / "summary.md").write_text(text)
    print("\n" + text)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as fh:
            fh.write("## Incidents\n\n" + text)
