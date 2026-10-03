#!/usr/bin/env bash
# Builds the whole platform in kind: cluster, images, in-cluster Git, Argo CD,
# then lets Argo CD install everything else from this repository.
# OVERLAYS="kind" locally, OVERLAYS="kind ci" in CI.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

if ! "$KIND" get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  log "Creating kind cluster $CLUSTER"
  "$KIND" create cluster --config cluster/kind.yaml --wait 180s
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null

if [ "${SKIP_IMAGES:-0}" != "1" ] && [ -x scripts/build-images.sh ]; then
  log "Building and loading orders images"
  scripts/build-images.sh
  for v in $ORDERS_VERSIONS; do
    "$KIND" load docker-image "orders:$v" --name "$CLUSTER"
  done
fi

log "Starting the in-cluster Git server"
kubectl apply -f deploy/bootstrap/git-server/git-server.yaml
kubectl -n git-server rollout status deploy/soft-serve --timeout=180s
for _ in $(seq 1 60); do
  git ls-remote "$GIT_REMOTE" >/dev/null 2>&1 && break
  sleep 2
done

log "Publishing the working tree to it"
scripts/sync.sh

log "Installing Argo CD (chart $ARGOCD_CHART_VERSION)"
helm upgrade --install argocd argo-cd --repo https://argoproj.github.io/argo-helm \
  --version "$ARGOCD_CHART_VERSION" --namespace argocd --create-namespace \
  --values deploy/bootstrap/argocd-values.yaml --wait --timeout 10m

log "Applying the root Application (overlays: $OVERLAYS)"
# shellcheck disable=SC2086 # OVERLAYS is a space-separated list, split on purpose
overlays_json="$(printf '"%s",' $OVERLAYS)"
kubectl apply -f - <<APP
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: platform
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  source:
    repoURL: http://soft-serve.git-server.svc:23232/platform.git
    targetRevision: main
    path: deploy/platform
    helm:
      valuesObject:
        overlays: [${overlays_json%,}]
  syncPolicy:
    automated: { prune: true, selfHeal: true }
APP

log "Waiting for every Application to be Synced and Healthy"
scripts/wait-apps.sh "${WAIT_TIMEOUT:-1200}"

log "Ready"
cat <<URLS
  Grafana       http://localhost:30300   (anonymous viewer; admin/admin)
  Prometheus    http://localhost:30090
  Alertmanager  http://localhost:30093
  Argo CD       http://localhost:30080   (anonymous read-only)
  orders API    http://localhost:30800
  Tempo API     http://localhost:30320
  Git (Argo CD) http://localhost:30232/platform.git
URLS
