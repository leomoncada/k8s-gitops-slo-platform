#!/usr/bin/env bash
# Generates Prometheus rules from slos/orders.yaml with Sloth:
#   slos/generated/kind/  real 30-day windows (local)
#   slos/generated/ci/    1-hour period with compressed windows (CI, ADR 6)
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

SLOTH_IMAGE="ghcr.io/slok/sloth:v0.16.0"

sloth() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:/work" -w /work "$SLOTH_IMAGE" "$@"
}

sloth generate --no-log -i slos/orders.yaml -o slos/generated/kind/orders-rules.yaml
sloth generate --no-log -i slos/orders.yaml -o slos/generated/ci/orders-rules.yaml \
  --slo-period-windows-path slos/windows/ci --default-slo-period 1h
echo "generated slos/generated/{kind,ci}/orders-rules.yaml"
