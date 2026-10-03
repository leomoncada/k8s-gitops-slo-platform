#!/usr/bin/env bash
# Checks the tools `make up` and the tests need.
set -uo pipefail
missing=0
check() {
  if command -v "$1" >/dev/null 2>&1; then
    printf '  ok       %-8s %s\n' "$1" "$($2 2>/dev/null | head -1)"
  else
    printf '  MISSING  %-8s install: %s\n' "$1" "$3"
    missing=1
  fi
}
check docker "docker version --format {{.Server.Version}}" "https://docs.docker.com/get-docker/"
check "${KIND:-kind}" "${KIND:-kind} version" "brew install kind  (or https://kind.sigs.k8s.io)"
check kubectl "kubectl version --client" "brew install kubectl"
check helm "helm version --short" "brew install helm"
check python3 "python3 --version" "https://www.python.org/downloads/"
check git "git --version" "brew install git"
if ! docker info >/dev/null 2>&1; then
  echo "  Docker is installed but not running"
  missing=1
fi
exit "$missing"
