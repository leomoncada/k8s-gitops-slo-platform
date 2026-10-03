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
    kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded >&2 || true
    exit 1
  fi
  sleep 10
done
