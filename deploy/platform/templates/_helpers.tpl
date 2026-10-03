{{/*
An Application for an upstream Helm chart, with values from
deploy/overlays/common/<file> plus each active overlay.
Args: dict "root" $ "name" <app name> "chart" <charts entry> "namespace" <ns>
      "release" <release name> "file" <values file> "wave" <sync wave>
      and optional "extra" (YAML string appended to spec)
*/}}
{{- define "platform.chartApp" -}}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {{ .name }}
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: {{ .wave | quote }}
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  destination:
    server: https://kubernetes.default.svc
    namespace: {{ .namespace }}
  sources:
    - repoURL: {{ .chart.repo }}
      chart: {{ .chart.name }}
      targetRevision: {{ .chart.version }}
      helm:
        releaseName: {{ .release }}
        ignoreMissingValueFiles: true
        valueFiles:
          - $values/deploy/overlays/common/{{ .file }}
          {{- range .root.Values.overlays }}
          - $values/deploy/overlays/{{ . }}/{{ $.file }}
          {{- end }}
    - repoURL: {{ .root.Values.repoURL }}
      targetRevision: {{ .root.Values.targetRevision }}
      ref: values
  syncPolicy:
    automated: { prune: true, selfHeal: true }
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - RespectIgnoreDifferences=true
    retry:
      limit: 10
      backoff: { duration: 10s, factor: 2, maxDuration: 3m }
  {{- with .extra }}
  {{- . | nindent 2 }}
  {{- end }}
{{- end -}}

{{/*
An Application for a Helm chart that lives in this repository.
Args: dict "root" $ "name" "path" "namespace" "wave" and optional "extra" (YAML string appended to spec)
*/}}
{{- define "platform.localApp" -}}
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {{ .name }}
  namespace: argocd
  annotations:
    argocd.argoproj.io/sync-wave: {{ .wave | quote }}
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  destination:
    server: https://kubernetes.default.svc
    namespace: {{ .namespace }}
  source:
    repoURL: {{ .root.Values.repoURL }}
    targetRevision: {{ .root.Values.targetRevision }}
    path: {{ .path }}
    helm:
      ignoreMissingValueFiles: true
      valueFiles:
        {{- range .root.Values.overlays }}
        - values-{{ . }}.yaml
        {{- end }}
  syncPolicy:
    automated: { prune: true, selfHeal: true }
    syncOptions:
      - CreateNamespace=true
      - ServerSideApply=true
      - RespectIgnoreDifferences=true
    retry:
      limit: 10
      backoff: { duration: 10s, factor: 2, maxDuration: 3m }
  {{- with .extra }}
  {{- . | nindent 2 }}
  {{- end }}
{{- end -}}
