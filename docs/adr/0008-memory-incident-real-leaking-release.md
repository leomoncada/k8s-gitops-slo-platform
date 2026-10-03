# 8. Memory incident via a real leaking release, not StressChaos

Date: 2026-10-03

Status: Accepted

## Context

Incident #3 needs the orders container to be OOM-killed, so that
`OrdersContainerOOMKilled` fires and its runbook is exercised. Chaos Mesh
`StressChaos` with a memory stressor is the obvious tool, but the stressor is
a separate process inside the container's cgroup. When the cgroup reaches its
limit, the kernel OOM killer usually picks the stressor, not the application.
The application keeps running, the container does not restart with reason
`OOMKilled`, and the alert has nothing to see. It would also leave the GitOps
path untested.

## Decision

Ship a real release that leaks. `incidents/03-memory-leak/v1.2.0.patch` adds a
plausible debugging feature, "replay snapshots": a fixed 256 KiB record kept
for every request, keyed by trace ID, and never evicted.

- `scripts/build-images.sh` builds `orders:1.2.0` from the patch, and
  `make up` loads it into kind. `app/tests/test_patches.py` checks that the
  patch still applies and still leaks.
- With a 256 Mi memory limit (`deploy/workloads/values.yaml`), a replica holds
  at most about a thousand snapshots before the kernel kills it, and fewer in
  practice.
- The incident is a commit that sets `image: orders:1.2.0`. The fix is
  `git revert`.

The database schema is applied by an idempotent init container in the orders
Deployment (`deploy/workloads/templates/orders.yaml`), not by an Argo CD sync
hook. A sync hook waits for every resource in earlier waves to be healthy.
With the Deployment stuck in an OOM loop, that wait would block the sync of the
very `git revert` that fixes it.

## Consequences

- The OOM belongs to the application: the container's last state is
  `terminated` with reason `OOMKilled`, as in production.
- The incident exercises the same release-and-revert path as incident #1.
- A third image must be built and loaded, and the patch must keep applying as
  `app/` changes (guarded by `test_patches.py`).
- Time to OOM depends on traffic per replica, so the test waits up to a
  timeout of at least 10 minutes.
- The init container runs `psql` every time a pod starts. That is safe
  because `app/schema.sql` uses `CREATE TABLE IF NOT EXISTS`, but it makes
  Postgres a start-up dependency: no new orders pod starts while Postgres is
  unreachable (ADR 2). Non-idempotent schema changes would need a versioned
  migration tool.
