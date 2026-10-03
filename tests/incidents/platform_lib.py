"""Helpers the incident tests share: the cluster, Prometheus, Alertmanager,
Tempo and the in-cluster Git repository Argo CD reads from.

Everything is reached through the fixed localhost ports that cluster/kind.yaml
maps, so nothing here depends on `kubectl port-forward`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
PROM = os.environ.get("PROM_URL", "http://localhost:30090")
ALERTMANAGER = os.environ.get("ALERTMANAGER_URL", "http://localhost:30093")
TEMPO = os.environ.get("TEMPO_URL", "http://localhost:30320")
GIT_REMOTE = os.environ.get("GIT_REMOTE", "http://localhost:30232/platform.git")
CLUSTER = "slo-platform"

_t0 = time.monotonic()


def narrate(message: str) -> None:
    """One timestamped line per step; `make incident-N` runs pytest with -s."""
    print(f"  [{time.monotonic() - _t0:7.1f}s] {message}", flush=True)


def run(*args: str, check: bool = True) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def kubectl(*args: str, check: bool = True) -> str:
    return run("kubectl", "--context", f"kind-{CLUSTER}", *args, check=check)


def wait_until(description: str, predicate, timeout: float, interval: float = 5) -> float:
    """Polls `predicate` until it is truthy; returns the seconds it took."""
    narrate(f"waiting: {description} (timeout {timeout:.0f}s)")
    start = time.monotonic()
    while True:
        try:
            if predicate():
                took = time.monotonic() - start
                narrate(f"done: {description} after {took:.0f}s")
                return took
        except (requests.RequestException, RuntimeError, KeyError, ValueError) as exc:
            narrate(f"  (retrying: {exc})")
        if time.monotonic() - start > timeout:
            raise AssertionError(f"timed out after {timeout:.0f}s waiting for: {description}")
        time.sleep(interval)


# --- Prometheus and Alertmanager ---------------------------------------------


def prom_query(query: str) -> list[dict]:
    response = requests.get(f"{PROM}/api/v1/query", params={"query": query}, timeout=10)
    response.raise_for_status()
    return response.json()["data"]["result"]


def prom_value(query: str, default: float = 0.0) -> float:
    result = prom_query(query)
    return float(result[0]["value"][1]) if result else default


def compressed_windows() -> bool:
    """True when the CI rules (ADR 6) are loaded: their 30 s window only exists
    there. Checked through the rules API, not data, so it holds while healthy."""
    response = requests.get(f"{PROM}/api/v1/rules", params={"type": "record"}, timeout=10)
    response.raise_for_status()
    return any(
        rule.get("name") == "slo:sli_error:ratio_rate30s"
        for group in response.json()["data"]["groups"]
        for rule in group["rules"]
    )


def firing_alerts() -> list[dict]:
    response = requests.get(
        f"{ALERTMANAGER}/api/v2/alerts",
        params={"active": "true", "silenced": "false", "inhibited": "false"},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def alert_firing(name: str, severity: str | None = None) -> bool:
    return any(
        a["labels"].get("alertname") == name
        and (severity is None or a["labels"].get("severity") == severity)
        for a in firing_alerts()
    )


def error_ratio(window: str = "1m") -> float:
    """Share of orders requests answered with a 5xx over `window` (1.0 without traffic)."""
    total = prom_value(f'sum(rate(http_requests_total{{job="orders"}}[{window}]))')
    bad = prom_value(f'sum(rate(http_requests_total{{job="orders", status=~"5.."}}[{window}]))')
    return 1.0 if total == 0 else bad / total


def slow_ratio(window: str = "1m") -> float:
    """Share of orders requests slower than the 300 ms SLO threshold over `window`."""
    count = 'http_request_duration_seconds_count{job="orders"}'
    fast = 'http_request_duration_seconds_bucket{job="orders", le="0.3"}'
    total = prom_value(f"sum(rate({count}[{window}]))")
    good = prom_value(f"sum(rate({fast}[{window}]))")
    return 1.0 if total == 0 else max(0.0, (total - good) / total)


def wait_for_recovery(report, alert, sli, *, budget, compressed, timeout) -> None:
    """Recovery is the service being healthy again: the SLI back within its
    objective over the last minute. The page clearing lags by design (its
    windows still remember the incident): with compressed CI windows it must
    clear within the timeout; with real 30-day windows on a young cluster the
    slow page can legitimately last ~30 minutes, so it is recorded, not required."""
    wait_until(
        f"SLI back within objective over 1m (bad ratio <= {budget})",
        lambda: sli() <= budget,
        timeout,
    )
    report.mark("resolved")
    if compressed:
        wait_until(f"{alert} page clears", lambda: not alert_firing(alert, "page"), timeout)
        report.mark("alert_cleared")
        return
    try:
        wait_until(
            f"{alert} page clears (real windows)",
            lambda: not alert_firing(alert, "page"),
            600,
        )
        report.mark("alert_cleared")
    except AssertionError:
        report.facts["page_still_firing_after_recovery_s"] = 600
        narrate(
            "page still firing 10 min after recovery: expected with real windows on a young cluster"
        )


def describe(alerts: list[dict]) -> str:
    return ", ".join(
        f"{a['labels'].get('alertname')}({a['labels'].get('severity', '-')})" for a in alerts
    )


# --- Workloads -----------------------------------------------------------------


def deployment(name: str = "orders") -> dict:
    return json.loads(kubectl("-n", "orders", "get", "deployment", name, "-o", "json"))


def rollout_complete(image: str, name: str = "orders") -> bool:
    """Every replica runs `image` and is Ready: the rollout passed its health checks."""
    d = deployment(name)
    spec, status = d["spec"], d.get("status", {})
    if spec["template"]["spec"]["containers"][0]["image"] != image:
        return False
    if status.get("observedGeneration", 0) < d["metadata"]["generation"]:
        return False
    replicas = spec.get("replicas", 0)
    return (
        status.get("updatedReplicas", 0) == replicas
        and status.get("readyReplicas", 0) == replicas
        and status.get("availableReplicas", 0) == replicas
        and status.get("replicas", 0) == replicas  # no old pods left
    )


def orders_pods() -> list[dict]:
    return json.loads(kubectl("-n", "orders", "get", "pods", "-l", "app=orders", "-o", "json"))[
        "items"
    ]


def refresh(app: str = "workloads") -> None:
    """Ask Argo CD to re-read Git now instead of at the next poll."""
    kubectl(
        "-n", "argocd", "annotate", "application", app,
        "argocd.argoproj.io/refresh=hard", "--overwrite",
    )  # fmt: skip


# --- GitOps --------------------------------------------------------------------


class GitOps:
    """A clone of the in-cluster repository. Incidents change the platform the
    way a team would: a commit, and a `git revert` to undo it."""

    VALUES = "deploy/workloads/values.yaml"

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="gitops-")
        self.path = Path(self._tmp.name)
        run("git", "clone", "--quiet", GIT_REMOTE, str(self.path))
        self._git("config", "user.name", "orders release bot")
        self._git("config", "user.email", "release-bot@orders.example")

    def close(self) -> None:
        self._tmp.cleanup()

    def _git(self, *args: str) -> str:
        return run("git", "-C", str(self.path), *args)

    def _push(self) -> str:
        self._git("pull", "--quiet", "--rebase", "origin", "main")
        self._git("push", "--quiet", "origin", "HEAD:main")
        refresh()
        return self._git("rev-parse", "HEAD")

    def set_orders_image(self, tag: str, message: str) -> str:
        values = self.path / self.VALUES
        text = values.read_text()
        new = re.sub(r"image: orders:\S+", f"image: orders:{tag}", text, count=1)
        assert new != text, f"orders image tag not found in {self.VALUES}"
        values.write_text(new)
        self._git("commit", "--quiet", "-am", message)
        sha = self._push()
        narrate(f"pushed {sha[:7]}: {message.splitlines()[0]}")
        return sha

    def revert(self, sha: str) -> str:
        self._git("revert", "--no-edit", sha)
        new = self._push()
        narrate(f"pushed {new[:7]}: revert of {sha[:7]}")
        return new


# --- Reporting -----------------------------------------------------------------


@dataclass
class Timeouts:
    """Real 30-day windows locally take minutes; compressed CI windows, seconds."""

    rollout: float
    detect: float
    recover: float

    @classmethod
    def for_profile(cls, compressed: bool, detect: float, recover: float) -> Timeouts:
        if compressed:
            return cls(rollout=240, detect=detect, recover=recover)
        return cls(rollout=300, detect=detect * 3, recover=recover * 4)


class Report:
    """Times one incident: injected -> detected -> mitigated -> resolved."""

    def __init__(self, incident: str, title: str) -> None:
        self.incident, self.title = incident, title
        self.marks: dict[str, float] = {}
        self.facts: dict[str, object] = {}

    def mark(self, name: str) -> None:
        self.marks[name] = time.time()

    def seconds(self, start: str, end: str) -> float | None:
        if start in self.marks and end in self.marks:
            return round(self.marks[end] - self.marks[start], 1)
        return None

    def save(self, passed: bool) -> None:
        out = ROOT / "reports" / "incidents"
        out.mkdir(parents=True, exist_ok=True)
        data = {
            "incident": self.incident,
            "title": self.title,
            "passed": passed,
            "windows": "compressed (CI)" if compressed_windows() else "real (30 days)",
            "time_to_detect_s": self.seconds("injected", "detected"),
            "time_to_recover_s": self.seconds("detected", "resolved"),
            "total_s": self.seconds("injected", "resolved"),
            "alert_cleared_after_recovery_s": self.seconds("resolved", "alert_cleared"),
            "marks": {k: round(v, 1) for k, v in self.marks.items()},
            "facts": self.facts,
        }
        (out / f"{self.incident}.json").write_text(json.dumps(data, indent=2) + "\n")
