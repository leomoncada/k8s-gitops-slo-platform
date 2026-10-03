#!/usr/bin/env bash
# Build the orders images.
#
#   orders:1.0.0  from app/ as it is
#   orders:1.1.0  app/ + incidents/01-bad-release/v1.1.0.patch
#   orders:1.2.0  app/ + incidents/03-memory-leak/v1.2.0.patch
#
# Usage: scripts/build-images.sh [VERSION...]   (default: all three)
# Env:   ORDERS_IMAGE  image name (default: orders)
#
# Works with bash 3.2 (macOS) and Linux. Fails if a patch does not apply.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${ORDERS_IMAGE:-orders}"

TMP_DIR=""
cleanup() {
  # Remove only the directory this script created.
  if [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ]; then
    rm -rf -- "$TMP_DIR"
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

patch_for() {
  case "$1" in
    1.0.0) echo "" ;;
    1.1.0) echo "incidents/01-bad-release/v1.1.0.patch" ;;
    1.2.0) echo "incidents/03-memory-leak/v1.2.0.patch" ;;
    *) echo "error: unknown version '$1' (expected 1.0.0, 1.1.0 or 1.2.0)" >&2; return 1 ;;
  esac
}

build() {
  local version="$1" context="$2"
  printf '\n==> building %s:%s\n' "$IMAGE" "$version"
  docker build --build-arg "APP_VERSION=${version}" --tag "${IMAGE}:${version}" "$context"
}

build_patched() {
  local version="$1" patch="$ROOT/$2" src
  if [ ! -f "$patch" ]; then
    echo "error: patch not found: $patch" >&2
    exit 1
  fi
  if [ -z "$TMP_DIR" ]; then
    local base="${TMPDIR:-/tmp}"
    TMP_DIR="$(mktemp -d "${base%/}/orders-images.XXXXXX")"
  fi
  src="$TMP_DIR/$version"
  mkdir -p "$src"
  # Copy app/ without local caches or virtualenvs (BSD and GNU tar alike).
  (cd "$ROOT" && tar -cf - --exclude='__pycache__' --exclude='.venv' \
    --exclude='.pytest_cache' --exclude='.ruff_cache' app) | (cd "$src" && tar -xf -)
  # A throwaway repo makes git apply resolve the a/app/... paths against $src,
  # whatever repository the temp dir happens to live in.
  git -C "$src" init --quiet
  if ! git -C "$src" apply --verbose "$patch"; then
    echo "error: $2 does not apply to app/; regenerate it against the current code" >&2
    exit 1
  fi
  build "$version" "$src/app"
}

if [ "$#" -eq 0 ]; then
  set -- 1.0.0 1.1.0 1.2.0
fi

for version in "$@"; do
  patch="$(patch_for "$version")"
  if [ -z "$patch" ]; then
    build "$version" "$ROOT/app"
  else
    build_patched "$version" "$patch"
  fi
done

printf '\n==> built:\n'
for version in "$@"; do
  docker image ls --format '  {{.Repository}}:{{.Tag}}  {{.Size}}' "${IMAGE}:${version}"
done
