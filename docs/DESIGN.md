# Design: `k8s-gitops-slo-platform`

**Status:** designed, ready for an implementation plan.
**Date:** 2026-10-03
**Owner:** Leomar Moncada
**Companion repos:** `leomoncada/aws-ecs-fargate-platform`, `leomoncada/localstack-ephemeral-infra`, `leomoncada/aws-serverless-golden-path`

> This file is the working spec. When the repository exists, it becomes
> `docs/DESIGN.md` in the first commit, and the decisions marked "ADR" below
> are split into `docs/adr/`.

---

## 1. Purpose

Put public, running code behind the claims that lead the CV for SRE and DevOps
roles: Kubernetes, GitOps with Argo CD, observability, and alerts worth acting
on. Of 37 tailored CVs sent so far (15 SRE, 13 DevOps, 4 Platform, 3 Cloud,
1 DevSecOps, 1 other), all 37 mention Kubernetes. None of the three existing public repos
contains Kubernetes, GitOps or SLO code.

The thesis:

> Installing Prometheus is not SRE. Proving that a specific failure produces a
> specific alert, within a measured time, and that the runbook recovers it, is.

Three things make this repo different from the usual "kube-prometheus-stack on
kind" repo:

1. **Incidents are tests.** Six reproducible incidents, each with an injection,
   an expected alert, a recovery check and a runbook. CI runs all six on a fresh
   cluster and publishes time to detect and time to recover.
2. **GitOps is exercised, not just installed.** A bad release and a memory leak
   arrive as real commits, and recovery is a real `git revert`, all inside the
   cluster.
3. **It runs on a laptop at zero cost.** `make up` builds the whole platform in
   kind; `make demo` walks a full incident with narration.

### Audience

- Recruiters, who read the README and the incident table.
- Technical reviewers, who read the code, the CI runs, the ADRs and the
  runbooks. Neither needs cloud credentials to see it work.

---

## 2. Constraints

- **Money.** Zero recurring cost. No managed Kubernetes in v1 (the EKS control
  plane alone is $73/month).
- **No credentials anywhere in v1.** Local and CI runs need only Docker.
- **Consistency with the companion repos:** `Makefile` with `## help` targets,
  `docs/DESIGN.md`, ADRs, runbooks, honest limits in the README.
- **Job search is live.** Prefer a finished v1 over a bigger unfinished one;
  EKS and canary releases are explicitly phase 2 and future work.

---

## 3. Architecture

```
                ┌──────────────── kind cluster (local or CI) ─────────────────┐
  make up ──►   │  git-server ◄── Argo CD (app-of-apps) ──► installs all:    │
  (seeds the    │   (working-tree     │                                      │
   local repo)  │    repo)            ├─► platform: Prometheus, Alertmanager,│
                │                     │   Grafana, Loki, Tempo, OTel         │
                │                     │   Collector, Chaos Mesh, SLO rules   │
                │                     └─► workloads: orders (3 replicas)     │
                │                         + Postgres + baseline traffic (k6) │
                │  incident test: inject ─► alert in Alertmanager ─► verify  │
                │  (fault or commit)        detection and recovery           │
                └────────────────────────────────────────────────────────────┘
```

- **Cluster:** kind with one control-plane node and two workers. Two workers
  are needed for the node-failure incident and for topology spread.
- **Git source for Argo CD: a lightweight Git server inside the cluster**
  (Soft Serve), seeded from the working tree by `make up` and updated by
  `make sync`. Local changes are testable without pushing, and incidents can
  commit and revert without tokens or junk commits on GitHub. In phase 2 Argo
  CD points to GitHub instead and nothing else changes. **ADR.**
- **Images** are built locally and loaded with `kind load`. No registry in v1.
- **Access:** kind `extraPortMappings` expose fixed localhost ports, so tests
  and humans never depend on `kubectl port-forward`:

| Service | URL |
|---|---|
| Grafana | `http://localhost:3000` (anonymous viewer) |
| Prometheus | `http://localhost:9090` |
| Alertmanager | `http://localhost:9093` |
| Argo CD | `http://localhost:8080` |
| orders API | `http://localhost:8000` |

---

## 4. The service: `orders`

A small Python service built with FastAPI, purpose-built to fail in realistic
ways. Python matches the CV; Go would show a skill the CV does not claim.

### API

| Endpoint | Purpose |
|---|---|
| `POST /orders`, `GET /orders/{id}`, `GET /orders` | Real reads and writes against Postgres |
| `GET /healthz` | Liveness: the process answers |
| `GET /readyz` | Readiness: the process can serve. **Does not check Postgres.** |
| `GET /metrics` | Prometheus metrics |

**Readiness does not depend on the database.** If it did, a slow Postgres
(incident #2) would mark every pod unready at once and turn a degradation into
a full outage. Same reasoning as `/api/health/ready` in
`aws-ecs-fargate-platform`. **ADR.**

### Data

- Postgres as a StatefulSet built in this repo, with the official image and a
  local-path volume. No Bitnami chart (image terms changed in 2025) and no
  operator (out of proportion for one instance).
- Schema created by an init Job.
- Postgres probes use `pg_isready` via exec, so network chaos on the Postgres
  pod never restarts it.
- **Postgres is pinned to the control-plane node.** With a node-local volume it
  cannot move; if it lived on a worker, the node-failure incident would become a
  total outage. A single instance is a known single point of failure, stated in
  the README. HA Postgres is out of scope. **ADR.**

### Instrumentation

- **Metrics** (`prometheus_client`): request counter by route and status code,
  and a latency histogram with a bucket exactly at the 300 ms SLO threshold.
- **Traces** (OpenTelemetry SDK): FastAPI and psycopg instrumentation, OTLP to
  the Collector, stored in Tempo.
- **Logs:** JSON to stdout via structlog, including `trace_id` and `span_id`.

### Releases

| Version | Behaviour |
|---|---|
| `v1.0.0` | Correct |
| `v1.1.0` | A serializer "refactor" that raises on orders whose optional field is null. About 30% of requests fail. Health checks still pass, so the rollout completes and **only the SLO catches it.** |
| `v1.2.0` | Adds a response cache with no eviction. Memory grows with traffic until the container is OOM-killed. Growth is sized against the memory limit so OOM happens within minutes at baseline traffic. |

### Runtime shape

- 3 replicas, topology spread across the two workers, PodDisruptionBudget
  `minAvailable: 2`.
- Requests and limits set; the memory limit makes `v1.2.0` a real OOM.
- HPA on CPU, 3 to 6 replicas. Argo CD ignores `/spec/replicas` so it does not
  fight the HPA. **ADR.**
- `tolerationSeconds` for `not-ready` and `unreachable` lowered from the default
  300 to about 30, so pods leave a dead node in seconds rather than five
  minutes. **ADR.**

### Traffic

SLOs measure nothing without traffic. A k6 Deployment generates a constant
baseline of about 10 requests per second, mixing reads and writes, with about
30% of created orders leaving the optional field null (so `v1.1.0` fails on a
realistic share of traffic). Incident #6 adds a second k6 run.

### Tests

pytest against a real Postgres (service container in CI). No database mocks.

---

## 5. Observability, SLOs and alerting

### Components

All installed by Argo CD as separate Applications:

- **kube-prometheus-stack:** Prometheus, Alertmanager, Grafana,
  kube-state-metrics, node-exporter. Components that kind does not expose
  (etcd, scheduler, controller-manager) are disabled, otherwise their alerts
  fire forever.
- **metrics-server**, required by the HPA and missing from kind.
- **Loki** and **Tempo**, single-binary mode.
- **OpenTelemetry Collector** as a DaemonSet: container logs to Loki, OTLP
  traces to Tempo. One agent; no Promtail or Alloy.

Tempo rather than Jaeger: one UI for metrics, logs and traces, TraceQL, span
metrics, and object storage that is cheap in phase 2. Instrumentation is
OpenTelemetry, so the backend is a Collector exporter change. **ADR.**

No service mesh: one service and one database do not justify Istio's
operational cost. When a mesh becomes worth it is written down. **ADR.**

### SLOs (Sloth specs in `slos/`)

| SLO | Objective (30 days) | Bad events |
|---|---|---|
| Availability | 99.9% | 5xx responses (4xx are the client's fault) |
| Latency | 99% of requests under 300 ms | Requests above the threshold |

Sloth generates multiwindow, multi-burn-rate alerts with a page tier and a
ticket tier. Generated rules are committed; CI regenerates them and fails on any
difference, so nobody hand-edits them. **ADR.**

### Compressed windows in CI

Real windows (5 minutes and 1 hour for the fast page alert) make an incident
test take an hour. The `ci` overlay redefines the SLO period and alert windows
through Sloth's custom period windows and lowers the scrape interval to 5
seconds, so detection takes 2 to 3 minutes. The burn-rate math is unchanged;
only the time scale differs, and the README says so. **ADR.**

### Alerts per incident

| # | Alert | Source |
|---|---|---|
| 1 | `OrdersAvailabilityBurnRate` (page) | Sloth |
| 2 | `OrdersLatencyBurnRate` (page) | Sloth |
| 3 | `OrdersContainerOOMKilled` | Own rule |
| 4 | `GitOpsDriftNotHealed` (fires only if self-heal does not fix drift) | Own rule, proven by a `promtool` unit test |
| 5 | `KubeNodeDown` | Own rule |
| 6 | `OrdersHPAMaxedOut` | Own rule |

Own rules exist because the kube-prometheus-stack defaults wait up to 15
minutes; their `for` durations are set per overlay. Every rule carries a
`runbook_url` annotation pointing to `docs/runbooks/<alert>.md`.

### Clean baseline

Before every incident, the test requires that nothing fires except `Watchdog`.
After recovery, it requires the same again.

### Routing

Alertmanager routes `severity=page` and `severity=ticket` to separate receivers.
Both point to a minimal webhook sink that logs each alert (visible in Loki). No
Slack, PagerDuty or secrets; the README shows how to add Slack.

### Grafana

Dashboards as code: a service dashboard (traffic, errors, latency, saturation)
and an SLO dashboard (error budget remaining, burn rates). Datasources are
linked: log to trace by `trace_id`, trace to logs.

---

## 6. Incident framework

### Runner

Incidents are pytest tests under `tests/incidents/`, sharing fixtures for
Alertmanager, Prometheus, Tempo, the in-cluster Git repo and the cluster. Every
test follows the same steps:

1. Require a clean baseline.
2. Inject.
3. Wait for the expected alert to fire (polling Alertmanager, with a timeout).
4. Run the incident's own checks.
5. Remediate.
6. Wait for alerts to resolve and the baseline to be clean again.
7. Record time to detect and time to recover in a JSON report.

`make incident-N` runs one with step-by-step narration and Grafana links;
`make incidents` runs all six. CI runs exactly the same code.

### Catalog

Each incident has `incidents/0N-<name>/` with a `README.md` (scenario, which
runbook to follow) and its injection assets.

| # | Incident | Injection | Remediation | Test also asserts |
|---|---|---|---|---|
| 1 | Bad release | Commit `v1.1.0` to the in-cluster repo | `git revert`; Argo CD rolls back to `v1.0.0` | The rollout completed with all pods Ready before the alert fired |
| 2 | Slow dependency | Chaos Mesh `NetworkChaos`: 400 ms delay on all egress of the Postgres pod | Delete the experiment | A Tempo trace shows a Postgres span above 350 ms |
| 3 | Memory leak | Commit `v1.2.0` | `git revert` | Container restart count increased with reason `OOMKilled` |
| 4 | Manual drift | `kubectl set env` on the Deployment and `kubectl delete pdb` | Automatic: Argo CD self-heal | Both restored in under 60 seconds, and no page fired |
| 5 | Node failure | `docker stop` a worker running at least one replica | `docker start` the node | 3 Ready replicas restored on the surviving worker; error budget spent stays under a measured threshold; the node rejoins |
| 6 | Traffic spike | k6 Job ramping to about 200 requests per second | The load ends | HPA scaled to its maximum; the alert resolves after scale-down |

Drift is an env var and a deleted PodDisruptionBudget rather than "scale to 0",
because the HPA owns replicas and an HPA does not scale a Deployment that is at
zero.

The memory incident uses a real leaking release, not Chaos Mesh `StressChaos`:
the stressor runs inside the container's cgroup and the kernel usually kills
the stressor, not the application, so there would be no application OOM.
**ADR.**

### Chaos Mesh, verified before design approval

Run on 2026-10-03 with Chaos Mesh 2.8.4 and kind v0.33.0 (Kubernetes v1.37.0),
measuring 20 requests from a client pod to an nginx pod:

| Environment | Delay on all egress of the target pod | Targeted delay, via Service IP | Targeted delay, via pod IP |
|---|---|---|---|
| macOS, Docker Desktop (kernel 6.12 linuxkit) | +0.80 s | no effect | +0.80 s |
| GitHub `ubuntu-24.04` (kernel 6.17 azure) | +0.80 s | no effect | not run |
| GitHub `ubuntu-26.04` (kernel 7.0 azure) | +0.80 s | no effect | not run |

The +0.80 s for a 400 ms delay is expected: each new connection has two packets
leaving the delayed pod (the SYN-ACK and the response).

Targeted delays (`direction: to` with a `target`) do not apply to traffic
addressed to a Service ClusterIP: the packet leaves the source pod addressed to
the Service IP, kube-proxy rewrites it to the pod IP only on the node, and the
ipset filter matching pod IPs never sees it. The kernel modules (`sch_netem`,
`ip_set`, `xt_set`) were loaded on the GitHub runners, which rules out missing
kernel support. Hence the design delays **all egress of the Postgres pod**,
which works regardless of how the client connects. This limitation goes into
the README's known limits. **ADR.**

### Runbooks and postmortems

- **Runbooks are per alert, not per incident**, as in real operations:
  `docs/runbooks/<alert>.md` with meaning, impact, diagnosis (PromQL, LogQL,
  TraceQL, `kubectl`), mitigation and escalation. Incidents point to the
  runbook to follow.
- **Postmortems** for incidents #1 and #2, written from a real local run using a
  blameless template: impact as error budget consumed, timeline with the
  measured times, root cause, what went well and badly, action items. The main
  action item of #1 points to the canary work in section 11.

---

## 7. Local experience

| Target | What it does |
|---|---|
| `make help` | Lists targets |
| `make doctor` | Checks Docker, kind, kubectl, helm and Python versions |
| `make up` | Creates the cluster, builds and loads images, seeds the in-cluster Git repo, installs Argo CD, waits until every Application is Synced and Healthy, prints the URLs |
| `make sync` | Pushes local changes to the in-cluster repo so Argo CD applies them |
| `make incident-N` | Runs one incident with narration |
| `make incidents` | Runs all six |
| `make test` | App tests and `promtool` rule tests |
| `make lint` | Same lint as CI |
| `make demo` | `up`, then incident #1 narrated |
| `make down` | Deletes the cluster |

Target: `make up` under 10 minutes on first run on the owner's Mac (48 GB RAM,
25 GB assigned to Docker). If it is slow, a local image cache is added then, not
up front.

---

## 8. CI

GitHub Actions on a public repo (free minutes; 4 vCPU, 16 GB runners). All
actions on the Node 24 runtime.

| Trigger | Jobs |
|---|---|
| Every pull request | **Lint:** ruff, `helm lint`, kubeconform against Kubernetes and CRD schemas, shellcheck. **SLOs:** regenerate Sloth rules and fail on diff. **Alert logic:** `promtool test rules` with synthetic series, no cluster. **App:** pytest against Postgres. **Smoke:** `make up` in kind, then require every Application Synced and Healthy and a clean baseline. |
| Push to `main`, nightly, manual | **The six incidents in parallel** (matrix), each on a fresh kind cluster with the `ci` overlay. A summary job writes time to detect and time to recover for each to the run summary. Manual dispatch can run a single incident. |

The nightly run catches upstream breakage and keeps the README evidence fresh.
Target wall clock for the full incident run: under 25 minutes.

Renovate keeps Helm chart, image and action versions current; everything is
pinned.

---

## 9. Repository layout

```
app/                    orders service, Dockerfile, tests
cluster/kind.yaml       1 control-plane + 2 workers, port mappings
deploy/
  bootstrap/            Argo CD install and root Application
  platform/             one Application per platform component
  workloads/            Helm chart for orders, Postgres, baseline traffic
  overlays/kind/        values for kind (small resources, local storage)
  overlays/ci/          compressed SLO windows, 5 s scrape, short retention
  overlays/eks/         phase 2: README only
slos/                   Sloth specs and generated rules
alerts/                 own rules and their promtool unit tests
incidents/0N-<name>/    scenario README and injection assets
tests/incidents/        pytest runner and shared fixtures
docs/
  DESIGN.md             this file
  adr/
  runbooks/
  postmortems/
scripts/                cluster, Git seeding and wait helpers
Makefile
renovate.json
LICENSE                 MIT
.github/workflows/      ci.yml, incidents.yml
```

---

## 10. ADRs to write

1. In-cluster Git server as the Argo CD source for local and CI; GitHub in phase 2.
2. Readiness does not depend on the database.
3. Tempo over Jaeger.
4. No service mesh in v1, and when one would be worth it.
5. Sloth for SLOs; generated rules committed and verified in CI.
6. Compressed SLO windows in CI.
7. Chaos Mesh delay on the Postgres pod's egress, with the spike evidence and the ClusterIP limitation.
8. Memory incident via a real leaking release, not `StressChaos`.
9. Single Postgres instance pinned to the control-plane node; accepted single point of failure.
10. Lowered `tolerationSeconds` for faster node-failure recovery.
11. The HPA owns replicas; Argo CD ignores `/spec/replicas`.

---

## 11. README structure

1. One-line thesis and the CI badge for the latest incident run.
2. What this proves, in five bullets.
3. Architecture diagram.
4. Quickstart: `make doctor`, `make up`, `make demo`.
5. Incident catalog with time to detect and time to recover from the latest nightly run.
6. What differs in CI (compressed windows) and why the math still holds.
7. Known limits: kind is not production, single Postgres, Chaos Mesh targeted delays and ClusterIP traffic.
8. Links to ADRs, runbooks and postmortems.
9. Phase 2 and future work.

---

## 12. Success criteria

v1 is done when:

1. `make up` works from scratch on the owner's Mac.
2. All six incident tests pass locally and in the CI matrix.
3. The README shows time to detect and time to recover from a real CI run.
4. Every alert has a runbook, and the two postmortems are written from real runs.
5. All eleven ADRs are written.
6. The project is listed in the `projects` command of the portfolio site.

---

## 13. Phase 2 and future work

### Phase 2: EKS target

The same manifests on EKS, following the "one codebase, two targets" pattern of
`localstack-ephemeral-infra`:

- Terraform for a minimal VPC (public subnets, no NAT Gateway), EKS and a small
  managed node group, applied and destroyed per demo session.
- Argo CD reads from GitHub; images published to GHCR.
- `overlays/eks/` changes storage class, exposure and resources.
- `PARITY-NOTES.md` records every kind versus EKS difference.

v1 prepares only what avoids a restructure later: the Argo CD repository URL and
storage values are overlay parameters.

### Future work

- **Incident #7, canary release with Argo Rollouts** (no mesh needed): the
  `v1.1.0` bug ships to 10% of traffic first, an analysis on the availability
  burn rate rolls it back automatically, and the README compares its blast
  radius against incident #1.
- HA Postgres (CloudNativePG).
- Alert routing to Slack.

---

## 14. Out of scope for v1

EKS or any cloud resource, canary releases, service mesh, HA Postgres, real
paging integrations, TLS and ingress controllers, authentication beyond an
anonymous Grafana viewer on localhost, multi-cluster.

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| Sloth custom period windows cannot express CI-short windows | Fallback: a script derives CI rules from the generated ones by scaling windows; still verified by `promtool` tests |
| Soft Serve does not fit Argo CD's HTTP access or the push flow | Fallback: a `git-http-backend` container, then Gitea |
| Full incident run exceeds 25 minutes because of image pulls | Pre-pull and `kind load` heavy images; trim the `ci` overlay |
| Alert timing makes CI flaky | Generous timeouts with polling, one fresh cluster per incident, times recorded so drift is visible |
| Memory pressure on 16 GB runners | Resource requests tuned in the `ci` overlay |
| Chaos Mesh behaviour changes with runner kernels | Verified on Ubuntu 24.04 and 26.04; the nightly run catches regressions |
| Leak sizing is not deterministic | Size growth relative to the memory limit; assert OOM within a timeout, not at an exact moment |
| Scope too large for the job-search window | Build in value order: platform and #1, then #2, #4, #3, #5, #6 |

---

## 16. Parameters to settle during implementation

Not open design questions; values to measure and fix in the plan:

- CI window lengths and alert `for` durations per overlay.
- The error budget threshold asserted in incident #5.
- `v1.2.0` growth rate against the memory limit.
- Exact versions: Python, Postgres image, chart versions, kind node image.
