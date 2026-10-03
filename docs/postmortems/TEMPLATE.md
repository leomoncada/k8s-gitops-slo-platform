# Postmortem: <title>

Blameless: this document describes what the system and the process allowed,
not who did what. Every number comes from the incident report
(`reports/incidents/<id>.json`), Prometheus or Alertmanager.

| | |
|---|---|
| Date | |
| Incident | `incidents/0N-<name>/` |
| Severity | page / ticket |
| Status | resolved |
| Time to detect | from the change to the alert firing |
| Time to recover | from the alert firing to the SLI back within objective |
| Error budget consumed | share of the period's budget |

## Summary

Two or three sentences: what broke, who noticed and how, how it was fixed.

## Impact

Who was affected, for how long, and how much of the error budget it cost.
Client-side numbers (k6) next to server-side numbers when they differ.

## Timeline (UTC)

| Time | Event |
|---|---|
| | Change pushed |
| | Alert fired |
| | Mitigation applied |
| | SLI back within objective |
| | Alert cleared |

## Root cause

The technical cause, and the condition that let it reach production.

## Detection

Which signal caught it, why that signal and not another, and whether a
health check or a test could have caught it earlier.

## What went well

## What went badly

## Action items

| Action | Type | Status |
|---|---|---|
| | prevent / detect / mitigate | |
