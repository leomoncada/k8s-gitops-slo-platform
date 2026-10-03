#!/usr/bin/env python3
"""Prints a Markdown table of incident reports (reports/incidents/*.json):
result, time to detect and time to recover. Used by `make incidents` and CI."""

import json
import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1] / "reports" / "incidents"


def fmt(seconds):
    return "-" if seconds is None else f"{seconds:.0f} s"


def main() -> int:
    rows = [json.loads(p.read_text()) for p in sorted(FOLDER.glob("*.json"))]
    if not rows:
        print("No incident reports found.")
        return 0
    print("| Incident | Result | Time to detect | Time to recover | Windows |")
    print("|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['incident']}: {r['title']} | {'pass' if r['passed'] else '**FAIL**'} "
            f"| {fmt(r['time_to_detect_s'])} | {fmt(r['time_to_recover_s'])} | {r['windows']} |"
        )
    facts = [(r["incident"], r["facts"]) for r in rows if r["facts"]]
    if facts:
        print("\nMeasured facts:\n")
        for incident, f in facts:
            print(f"- **{incident}**: " + ", ".join(f"{k} = {v}" for k, v in f.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
