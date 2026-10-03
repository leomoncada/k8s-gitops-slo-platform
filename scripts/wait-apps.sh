#!/usr/bin/env bash
# Waits until every Argo CD Application is Synced and Healthy.
# Usage: scripts/wait-apps.sh [timeout seconds, default 900]
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"

timeout="${1:-900}"
deadline=$(( $(date +%s) + timeout ))
last=""

while :; do
  status="$(kubectl -n argocd get applications.argoproj.io \
    -o custom-columns='NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status' \
    --no-headers 2>/dev/null || true)"
  if [ -n "$status" ] && ! echo "$status" | grep -vqE '\sSynced\s+Healthy$'; then
    echo "$status"
    echo "all Applications are Synced and Healthy"
    exit 0
  fi
  if [ "$status" != "$last" ]; then
    printf '%s\n---\n' "$status"
    last="$status"
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "timed out after ${timeout}s waiting for Applications" >&2
    kubectl -n argocd get applications.argoproj.io -o wide >&2 || true
    echo "--- resources not Synced or not Healthy:" >&2
    kubectl -n argocd get applications.argoproj.io -o json | "${PYTHON:-python3}" -c '
import json, sys
for app in json.load(sys.stdin)["items"]:
    status = app.get("status", {})
    for r in status.get("resources", []):
        health = r.get("health", {}).get("status")
        if r.get("status") != "Synced" or health not in (None, "Healthy"):
            print(" ", app["metadata"]["name"], r["kind"], r.get("namespace", ""), r["name"],
                  r.get("status"), health, r.get("health", {}).get("message", ""))
    op = status.get("operationState", {})
    if op.get("phase") not in (None, "Succeeded"):
        print(" ", app["metadata"]["name"], "operation", op.get("phase"), op.get("message", "")[:200])
' >&2 || true
    kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded >&2 || true
    exit 1
  fi
  sleep 10
done
