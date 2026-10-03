#!/usr/bin/env bash
# Everything CI lints, runnable locally: Python, shell, Helm charts, rendered
# manifests against Kubernetes and CRD schemas, and generated SLO rules.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

VENV_BIN="${VENV_BIN:-$ROOT/.venv/bin}"
KUBECONFORM_IMAGE="ghcr.io/yannh/kubeconform:v0.8.0"
SHELLCHECK_IMAGE="koalaman/shellcheck:v0.11.0"
OUT="build/lint"
mkdir -p "$OUT"

log "ruff"
"$VENV_BIN/ruff" check app tests
"$VENV_BIN/ruff" format --check app tests

log "shellcheck"
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck -x scripts/*.sh
else
  docker run --rm -v "$ROOT:/mnt" -w /mnt "$SHELLCHECK_IMAGE" -x scripts/*.sh
fi

log "helm lint (charts in this repo)"
for chart in deploy/platform deploy/platform-config deploy/workloads alerts; do
  helm lint --quiet "$chart" -f "$chart/values.yaml" >/dev/null
  echo "  ok $chart"
done

log "render everything Argo CD would apply (kind + ci overlays)"
OUT_DIR="$OUT/upstream" scripts/render-platform.sh kind ci >/dev/null
helm template platform deploy/platform --set 'overlays={kind,ci}' >"$OUT/platform.yaml"
helm template platform-config deploy/platform-config >"$OUT/platform-config.yaml"
helm template workloads deploy/workloads -f deploy/workloads/values-ci.yaml >"$OUT/workloads.yaml"
helm template alerts alerts -f alerts/values-ci.yaml >"$OUT/alerts.yaml"
cp deploy/bootstrap/git-server/git-server.yaml slos/generated/*/orders-rules.yaml incidents/0*/*.yaml "$OUT/" 2>/dev/null || true
# Rename copies that would collide (two orders-rules.yaml)
cp slos/generated/kind/orders-rules.yaml "$OUT/slo-kind.yaml"
cp slos/generated/ci/orders-rules.yaml "$OUT/slo-ci.yaml"
rm -f "$OUT/orders-rules.yaml"

log "kubeconform (Kubernetes + CRD schemas)"
docker run --rm -v "$ROOT/$OUT:/work" -w /work "$KUBECONFORM_IMAGE" \
  -summary -strict -ignore-missing-schemas \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  -skip CustomResourceDefinition \
  /work

log "generated SLO rules match slos/orders.yaml"
scripts/generate-slos.sh >/dev/null
if ! git diff --quiet -- slos/generated 2>/dev/null || [ -n "$(git status --porcelain -- slos/generated)" ]; then
  if git rev-parse --verify -q HEAD >/dev/null; then
    git --no-pager diff --stat -- slos/generated
    echo "slos/generated is out of date or hand-edited: run 'make slos' and commit" >&2
    exit 1
  fi
fi
echo "  ok"
