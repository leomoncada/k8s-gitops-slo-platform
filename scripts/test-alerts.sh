#!/usr/bin/env bash
# Unit-tests alert logic with promtool and synthetic series, no cluster needed:
# own rules (CI durations) and both generated SLO rule sets.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

PROMTOOL_IMAGE="quay.io/prometheus/prometheus:v3.15.0" # matches kube-prometheus-stack
OUT="build/rules"
mkdir -p "$OUT"

# PrometheusRule CR (stdin) -> plain Prometheus rules file (spec only)
spec_only() {
  "$PYTHON" -c '
import sys, yaml
docs = [d for d in yaml.safe_load_all(sys.stdin) if d]
groups = [g for d in docs for g in d["spec"]["groups"]]
yaml.safe_dump({"groups": groups}, sys.stdout, sort_keys=False)
'
}

helm template alerts alerts -f alerts/values-ci.yaml | spec_only >"$OUT/platform-alerts.yaml"
spec_only <slos/generated/ci/orders-rules.yaml >"$OUT/slo-ci.yaml"
spec_only <slos/generated/kind/orders-rules.yaml >"$OUT/slo-kind.yaml"

promtool() {
  docker run --rm --user "$(id -u):$(id -g)" -v "$ROOT:/work" -w /work \
    --entrypoint promtool "$PROMTOOL_IMAGE" "$@"
}

promtool check rules "$OUT"/*.yaml
promtool test rules alerts/tests/*.test.yaml
