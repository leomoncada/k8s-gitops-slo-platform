# GitOpsDriftNotHealed

| | |
|---|---|
| Severity | `ticket` |
| Source | Our own rule, `alerts/templates/rules.yaml` (group `gitops`) |
| Fires after | 5m OutOfSync locally, 2m in CI (`driftNotHealedFor` in `alerts/values*.yaml`) |
| Where to look | Argo CD at http://localhost:30080 (read-only without logging in) |

## Meaning

An Argo CD Application with automated sync has stayed `OutOfSync` for the hold
time:

```promql
argocd_app_info{sync_status="OutOfSync", autosync_enabled="true"} == 1
```

Every Application here syncs automatically with `selfHeal: true`
(`deploy/platform/templates/_helpers.tpl`). Self-heal normally reverts a manual
change in seconds; incident #4 asserts it does so within 60 s. So this alert
does not mean someone changed the cluster. It means Argo CD has tried to put
Git back and could not.

Typical causes:

- **The sync fails.** For example: an invalid manifest, an admission webhook
  rejecting it, a change to an immutable field (Deployment selector,
  StatefulSet `volumeClaimTemplates`), or a missing CRD.
- **A permanent diff.** The API server defaults or rewrites a field that the
  manifest states differently, so every sync "succeeds" and the diff stays.
  `deploy/workloads/templates/postgres.yaml` states the PVC template's
  `apiVersion`, `kind` and `volumeMode` for exactly this reason.
- **Another controller owns the field.** A controller or mutating webhook keeps
  changing a field that Argo CD keeps resetting. The HPA would do this with
  `/spec/replicas` if it were not ignored (ADR 11).
- **Retries exhausted.** The retry policy is 10 attempts with back-off up to
  3m. After that, the Application waits for a new commit or a refresh.

## Impact

The cluster no longer matches Git, and fixes sent through Git may not apply.
If this happens on `workloads`, the `git revert` that recovers a bad release
(incidents #1 and #3) will not reach the cluster. There is no direct user
impact by itself.

## Diagnosis

1. Which Application, and what is out of sync?

   ```sh
   kubectl -n argocd get applications \
     -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status,LAST-OP:.status.operationState.phase
   kubectl -n argocd get application <app> \
     -o jsonpath='{range .status.resources[?(@.status=="OutOfSync")]}{.kind}/{.namespace}/{.name}{"\n"}{end}'
   kubectl -n argocd get application <app> -o jsonpath='{.status.operationState.message}{"\n"}'
   kubectl -n argocd get application <app> -o jsonpath='{.status.conditions}{"\n"}'
   ```

   In the UI, open the Application. **App diff** shows the fields that differ,
   and **Sync status** and **Last sync** show the last operation and its error.
   With the CLI, log in first (anonymous access is read-only):

   ```sh
   argocd login localhost:30080 --plaintext --username admin \
     --password "$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
   argocd app get <app>
   argocd app diff <app>
   argocd app history <app>
   ```

2. Who changed the field? Field managers other than `argocd-controller` (for
   example `kubectl-edit`, `kubectl-set` or another controller) show who
   touched it.

   ```sh
   kubectl -n <ns> get <kind> <name> -o yaml --show-managed-fields
   ```

3. Is it failing repeatedly? Use Prometheus (http://localhost:30090):

   ```promql
   argocd_app_info{sync_status!="Synced"}
   sum by (name, phase) (increase(argocd_app_sync_total[15m]))
   ```

   A rising `phase="Failed"` or `phase="Error"` count means the sync keeps
   failing. Steady successful syncs with the app still OutOfSync means a
   permanent diff.

4. Read the controller logs in Loki (Grafana Explore, login admin/admin):

   ```logql
   {k8s_namespace_name="argocd"} |= "<app>" |~ "level=(error|warning)"
   ```

Traces do not apply; Argo CD is not instrumented here.

## Mitigation

The fix goes into Git. Do not make the cluster match by hand.

- **A manifest that cannot be applied:** revert the commit that introduced it
  in the repository Argo CD reads from (locally
  `http://localhost:30232/platform.git`):
  `git revert --no-edit <sha> && git push origin HEAD:main`.
- **A permanent diff from defaulting:** state the defaulted field in the
  manifest, as `postgres.yaml` does, and commit.
- **A field owned by another controller:** add an `ignoreDifferences` entry for
  it in `deploy/platform/templates/applications.yaml`, with
  `RespectIgnoreDifferences=true`, as is done for `/spec/replicas` (ADR 11).
- **A change to an immutable field:** the resource must be recreated. Either
  set the `argocd.argoproj.io/sync-options: Replace=true` annotation on that
  resource in Git, or delete the live object and let Argo CD recreate it. Be
  careful with the Postgres StatefulSet and its PVC: deleting a PVC deletes the
  data.
- After fixing, force a refresh with
  `kubectl -n argocd annotate application <app> argocd.argoproj.io/refresh=hard --overwrite`.

Do not disable automated sync to make the alert go away. The rule matches only
`autosync_enabled="true"`, so it goes quiet while the drift stays.

## Escalation

- If the drift is on `workloads` while a release needs reverting, escalate
  immediately: the recovery path is blocked.
- Otherwise, escalate to the author of the last commit to the Application's
  path, and to the platform team for Argo CD itself.

## Related incident

[Incident #4: manual drift](../../incidents/04-manual-drift/README.md). There,
self-heal fixes the drift and this alert must not fire. The firing case is
proven by the promtool test "drift that self-heal cannot fix fires" in
`alerts/tests/platform-alerts.test.yaml`.
