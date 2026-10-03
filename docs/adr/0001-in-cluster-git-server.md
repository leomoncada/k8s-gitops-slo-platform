# 1. In-cluster Git server as the Argo CD source

Date: 2026-10-03

Status: Accepted

## Context

Argo CD needs a Git repository to read. If it read from GitHub, every local
change would have to be pushed before it could be tested. Incidents #1 and #3
would need a token to push release commits and reverts, and those commits
would end up in the public history. CI runs six incidents in parallel on six
clusters, so they cannot share one branch.

## Decision

Run Soft Serve (`charmcli/soft-serve:v0.12.2`) inside the cluster, defined in
`deploy/bootstrap/git-server/git-server.yaml`. It runs in the `git-server`
namespace on the infra node (ADR 9), with a 1 Gi PersistentVolumeClaim so a
pod restart does not wipe the repository, and anonymous read-write access.

- Argo CD reads `http://soft-serve.git-server.svc:23232/platform.git`. This is
  `repoURL` in `deploy/platform/values.yaml`, and it is also set on the root
  Application in `scripts/up.sh`. Argo CD polls every 20 s
  (`timeout.reconciliation` in `deploy/bootstrap/argocd-values.yaml`).
- Humans and tests use `http://localhost:30232/platform.git` (NodePort 30232,
  bound to 127.0.0.1 by `cluster/kind.yaml`).
- `make sync` (`scripts/sync.sh`) takes the working tree, committed or not and
  respecting `.gitignore`, and publishes it as a new commit on top of the
  in-cluster `main`. Your local branches and index are not touched.
- The incident tests (`GitOps` in `tests/incidents/platform_lib.py`) clone the
  repository, commit an image tag change to `deploy/workloads/values.yaml`,
  push it and force an Argo CD refresh. The fix is `git revert`.

In phase 2, `repoURL` points at GitHub and nothing else changes.

## Consequences

- Local changes can be tested without pushing. Incidents commit and revert
  without credentials or junk commits on GitHub.
- Recovery is a real Git operation. That only works if nothing in Argo CD
  blocks a sync while the workload is unhealthy, which is why the schema is
  applied by an init container, not a sync hook (ADR 8).
- Anonymous read-write Git is acceptable only because the server is reachable
  only inside the cluster and on 127.0.0.1.
- The in-cluster history diverges from GitHub and is deleted by `make down`.
- Running `make sync` during an incident publishes the working tree's image
  tag on top of the incident commit, which ends the incident without a revert.
- There is no webhook. A change applies at the next 20 s poll unless a refresh
  is forced.
- The repository URL is set in two places.
