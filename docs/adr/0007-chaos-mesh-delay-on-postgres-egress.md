# 7. Chaos Mesh delay on all egress of the Postgres pod

Date: 2026-10-03

Status: Accepted

## Context

Incident #2 needs a slow Postgres without changing its code or configuration.
Chaos Mesh `NetworkChaos` with `action: delay` applies `tc netem` inside the
target pod's network namespace. The obvious setup is a targeted delay on the
orders pods: `direction: to`, with a `target` that selects Postgres.

Before the design was approved, this was measured on 2026-10-03 with Chaos
Mesh 2.8.4 and kind v0.33.0 (Kubernetes v1.37.0), timing 20 requests from a
client pod to an nginx pod:

| Environment | Delay on all egress of the target pod | Targeted delay, via Service IP | Targeted delay, via pod IP |
|---|---|---|---|
| macOS, Docker Desktop (kernel 6.12 linuxkit) | +0.80 s | no effect | +0.80 s |
| GitHub `ubuntu-24.04` (kernel 6.17 azure) | +0.80 s | no effect | not run |
| GitHub `ubuntu-26.04` (kernel 7.0 azure) | +0.80 s | no effect | not run |

A 400 ms delay adding 0.80 s is expected: each new connection sends two
packets out of the delayed pod, the SYN-ACK and the response.

Targeted delays do not apply to traffic addressed to a Service ClusterIP. The
packet leaves the source pod addressed to the Service IP. kube-proxy rewrites
it to a pod IP only on the node, so the ipset filter that matches target pod
IPs never sees it. The `sch_netem`, `ip_set` and `xt_set` modules were loaded
on the GitHub runners, which rules out missing kernel support.

## Decision

Delay everything the Postgres pod sends. The experiment is
`incidents/02-slow-dependency/network-delay.yaml`: `slow-postgres`, 400 ms,
`mode: all`, selecting `app: postgres`, with a 30m `duration` as a safety net.
The test applies it and always deletes it in a `finally` block.

- chaos-daemon runs on every node, including the infra node where Postgres
  lives (`deploy/overlays/common/chaos-mesh.yaml`).
- The Postgres probes run `pg_isready` via exec, which never crosses the
  delayed interface, so the experiment never restarts Postgres.

## Consequences

- The delay works whether orders connects through a ClusterIP or a pod IP, on
  every kernel tested.
- Every Postgres client is delayed. That is fine while orders is the only
  client; on a shared database the blast radius would be larger.
- The `postgres` Service is headless, so a targeted delay would probably work
  today. The design does not rely on that, because switching the Service to a
  ClusterIP would silently turn incident #2 into a no-op.
- Every reply is delayed, so every request breaks 300 ms; this is not a subtle
  tail-latency shift.
- The ClusterIP limitation goes into the README's known limits.
