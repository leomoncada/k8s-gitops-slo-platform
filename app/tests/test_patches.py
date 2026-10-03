"""The incident releases, checked against the code they patch.

Each patch is applied to a fresh copy of app/ and exercised in a subprocess,
so the patched package never mixes with the one under test here. If app/
changes in a way that breaks a patch, these tests fail before any image build.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = APP_DIR.parent
PROBE = Path(__file__).with_name("_patch_probe.py")
PATCHES = {
    "1.1.0": REPO_DIR / "incidents" / "01-bad-release" / "v1.1.0.patch",
    "1.2.0": REPO_DIR / "incidents" / "03-memory-leak" / "v1.2.0.patch",
}
COPY_IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache", ".venv")


def patched_app(version: str, tmp_path: Path) -> Path:
    """Copy app/ into a scratch repo root and apply the release patch there."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = tmp_path / f"v{version}"
    shutil.copytree(APP_DIR, root / "app", ignore=COPY_IGNORE)
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    applied = subprocess.run(
        ["git", "apply", "--verbose", str(PATCHES[version])],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stderr
    return root / "app"


def run_probe(app_dir: Path, scenario: str, database_url: str, tmp_path: Path) -> dict:
    output = tmp_path / f"{scenario}.json"
    env = {**os.environ, "PYTHONPATH": str(app_dir), "PROBE_DATABASE_URL": database_url}
    result = subprocess.run(
        [sys.executable, str(PROBE), scenario, str(output)],
        cwd=app_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    data = json.loads(output.read_text())
    module = Path(data["module"]).resolve()
    assert module.is_relative_to(app_dir.resolve()), "probe imported the unpatched code"
    return data


@pytest.mark.parametrize("version", sorted(PATCHES))
def test_patch_applies_with_patch_p1(version: str, tmp_path: Path) -> None:
    if shutil.which("patch") is None:
        pytest.skip("patch(1) is not installed")
    shutil.copytree(APP_DIR, tmp_path / "app", ignore=COPY_IGNORE)
    with PATCHES[version].open("rb") as diff:
        result = subprocess.run(
            ["patch", "-p1", "--dry-run"],
            stdin=diff,
            cwd=tmp_path,
            capture_output=True,
            check=False,
        )
    assert result.returncode == 0, result.stdout + result.stderr


def test_v1_1_0_fails_on_null_notes_while_probes_pass(clean_db: str, tmp_path: Path) -> None:
    result = run_probe(patched_app("1.1.0", tmp_path), "bad-release", clean_db, tmp_path)

    assert result["version"] == "1.1.0"
    assert result["null_note_error"] == "AttributeError"
    assert result["normalised_note"] == "ring twice"
    assert result["post_with_note"] == 201
    assert result["post_null_note"] == 500
    assert (result["healthz"], result["readyz"]) == (200, 200)


def test_v1_2_0_keeps_a_resident_buffer_per_request(clean_db: str, tmp_path: Path) -> None:
    result = run_probe(patched_app("1.2.0", tmp_path), "memory-leak", clean_db, tmp_path)

    assert result["version"] == "1.2.0"
    assert result["default_buffer_bytes"] == 256 * 1024
    assert result["snapshot_growth"] == result["requests"]
    assert result["probe_growth"] == 0
    # The buffers must be resident, not lazily mapped zero pages.
    expected_kib = result["requests"] * result["record_bytes"] // 1024
    assert result["rss_growth_kib"] >= 0.75 * expected_kib, result
