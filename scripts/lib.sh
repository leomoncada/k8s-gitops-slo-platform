# shellcheck shell=bash disable=SC2034  # variables are used by the scripts that source this
# Shared settings for the scripts. Source it, don't run it.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KIND="${KIND:-kind}"
CLUSTER="slo-platform"
OVERLAYS="${OVERLAYS:-kind}"
GIT_REMOTE="${GIT_REMOTE:-http://localhost:30232/platform.git}"
ARGOCD_CHART_VERSION="10.9.6" # renovate: datasource=helm depName=argo-cd registryUrl=https://argoproj.github.io/argo-helm
ORDERS_VERSIONS="1.0.0 1.1.0 1.2.0"

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
