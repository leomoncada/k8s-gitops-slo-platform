#!/usr/bin/env bash
# Publishes the working tree to the in-cluster Git server as a new commit on
# main, committed or not (honouring .gitignore). Argo CD reads from there, so
# local changes apply without pushing anywhere. Your index and branches are
# not touched.
set -euo pipefail
# shellcheck source=scripts/lib.sh
source "$(dirname "$0")/lib.sh"
cd "$ROOT"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Snapshot the working tree into a throwaway index
GIT_INDEX_FILE="$tmp/index" git add -A .
tree="$(GIT_INDEX_FILE="$tmp/index" git write-tree)"

parent="$(git ls-remote "$GIT_REMOTE" refs/heads/main | cut -f1)"
parent_args=()
if [ -n "$parent" ]; then
  git fetch -q "$GIT_REMOTE" main
  if [ "$(git rev-parse "$parent^{tree}")" = "$tree" ]; then
    echo "in-cluster repo already matches the working tree"
    exit 0
  fi
  parent_args=(-p "$parent")
fi

base="$(git rev-parse --short HEAD 2>/dev/null || echo "no commits")"
# CI runners have no git identity; the snapshot commit only lives in the
# in-cluster repo, so a fixed fallback identity is fine.
export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-$(git config user.name || echo "make sync")}"
export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-$(git config user.email || echo "sync@slo-platform.local")}"
export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$GIT_AUTHOR_NAME}"
export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-$GIT_AUTHOR_EMAIL}"
commit="$(git commit-tree "$tree" ${parent_args[@]+"${parent_args[@]}"} -m "sync: working tree on top of $base")"
git push -q "$GIT_REMOTE" "+$commit:refs/heads/main"
echo "published $(git rev-parse --short "$commit") to $GIT_REMOTE"
