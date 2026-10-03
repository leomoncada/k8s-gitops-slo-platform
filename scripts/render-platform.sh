#!/usr/bin/env bash
# Renders every upstream platform chart with the same value files Argo CD uses
# (deploy/overlays/common + each overlay), so value mistakes fail here, not in
# the cluster. Output goes to $OUT_DIR (default: build/rendered).
#
# Usage: scripts/render-platform.sh [overlay ...]   (default: kind)
set -euo pipefail

# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
OUT_DIR="${OUT_DIR:-$ROOT/build/rendered}"
OVERLAYS="${*:-kind}"
VALUES="$ROOT/deploy/platform/values.yaml"

mkdir -p "$OUT_DIR"

# Reads charts.<key>.<field> from the platform chart values
chart_field() {
  "$PYTHON" - "$VALUES" "$1" "$2" <<'PY'
import sys, yaml
values = yaml.safe_load(open(sys.argv[1]))
print(values["charts"][sys.argv[2]][sys.argv[3]])
PY
}

# key | release | namespace | values file
while read -r key release namespace file; do
  [ -z "$key" ] && continue
  repo="$(chart_field "$key" repo)"
  name="$(chart_field "$key" name)"
  version="$(chart_field "$key" version)"
  args=(--values "$ROOT/deploy/overlays/common/$file")
  for overlay in $OVERLAYS; do
    if [ -f "$ROOT/deploy/overlays/$overlay/$file" ]; then
      args+=(--values "$ROOT/deploy/overlays/$overlay/$file")
    fi
  done
  echo "render $name $version (${OVERLAYS})"
  helm template "$release" "$name" --repo "$repo" --version "$version" \
    --namespace "$namespace" --include-crds "${args[@]}" >"$OUT_DIR/$release.yaml"
done <<'EOF'
metricsServer metrics-server kube-system metrics-server.yaml
kubePrometheusStack kps monitoring kube-prometheus-stack.yaml
loki loki monitoring loki.yaml
tempo tempo monitoring tempo.yaml
otelCollector otel-collector monitoring otel-collector.yaml
chaosMesh chaos-mesh chaos-mesh chaos-mesh.yaml
EOF

echo "rendered to $OUT_DIR"
