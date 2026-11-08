# Helm and Kustomize authoring

Reference for `kubernetes-workloads` section 8. Render everything to plain YAML and validate the
rendered output; templates are never proof on their own.

## Helm chart layout

```
charts/app/
  Chart.yaml              apiVersion: v2, name, version (chart SemVer), appVersion, kubeVersion: ">=1.29.0-0"
  values.yaml             documented defaults, safe for a dev cluster
  values.schema.json      JSON Schema; helm lint/install/template fail on violations
  templates/_helpers.tpl  app.name, app.fullname, app.labels, app.selectorLabels
  templates/deployment.yaml service.yaml serviceaccount.yaml pdb.yaml hpa.yaml networkpolicy.yaml
  templates/NOTES.txt
  templates/tests/test-connection.yaml   helm test hook pod
  tests/*_test.yaml       helm-unittest suites (plugin)
```

### Template idioms

```yaml
metadata:
  name: {{ include "app.fullname" . }}
  labels: {{- include "app.labels" . | nindent 4 }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  selector:
    matchLabels: {{- include "app.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      annotations:
        checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
    spec:
      {{- with .Values.imagePullSecrets }}
      imagePullSecrets: {{- toYaml . | nindent 8 }}
      {{- end }}
      containers:
        - name: app
          image: "{{ .Values.image.repository }}{{ if .Values.image.digest }}@{{ .Values.image.digest }}{{ else }}:{{ .Values.image.tag | default .Chart.AppVersion }}{{ end }}"
          resources: {{- toYaml (required "resources are required" .Values.resources) | nindent 12 }}
```

Rules:
- `nindent` after `{{-` keeps indentation right; `indent` without a newline breaks block scalars.
- `required "msg" .Values.x` for mandatory values; `values.schema.json` for types and enums.
- `quote` string values that YAML might coerce (`"on"`, `"0755"`, version strings like `1.10`).
- `lookup` returns empty under `helm template` and `--dry-run` (no cluster): never make correctness depend on it.
- Hooks (`helm.sh/hook: pre-upgrade`) for migrations, with `helm.sh/hook-delete-policy:
  before-hook-creation,hook-succeeded`; hook Jobs are not managed by later upgrades.
- CRDs in `crds/` are installed once and never upgraded or deleted by Helm; ship CRD upgrades separately.
- Library charts (`type: library`) for shared helpers across many charts.

### Helm test commands

```bash
helm dependency build charts/app                       # vendored deps in charts/, Chart.lock pinned
helm lint charts/app --strict                          # with every values file you ship:
for f in charts/app/values*.yaml; do helm lint charts/app --strict -f "$f" || exit 1; done
helm template app charts/app -f values-prod.yaml --kube-version 1.31 --api-versions monitoring.coreos.com/v1 > out.yaml
helm unittest charts/app                               # plugin: helm plugin install https://github.com/helm-unittest/helm-unittest
ct lint --charts charts/app                            # chart-testing: version bump, maintainers, yamllint
helm diff upgrade app charts/app -f values-prod.yaml   # plugin; read-only diff against a release (needs cluster access: local only unless the brief names the context)
# live, local cluster only:
helm --kube-context kind-dev upgrade --install app charts/app -f values-dev.yaml --wait --timeout 3m --atomic
helm --kube-context kind-dev test app
```

`--api-versions` lets `.Capabilities.APIVersions.Has` branches render as they would on a cluster
that has those CRDs. `--atomic` rolls back a failed upgrade on the local test cluster.

### helm-unittest example

```yaml
suite: deployment
templates: [templates/deployment.yaml]
tests:
  - it: omits replicas when autoscaling is on
    set: {autoscaling.enabled: true}
    asserts:
      - notExists: {path: spec.replicas}
  - it: fails without resources
    set: {resources: null}
    asserts:
      - failedTemplate: {errorMessage: resources are required}
```

## Kustomize layout

```
k8s/
  base/            kustomization.yaml, deployment.yaml, service.yaml (no namespace, no env specifics)
  components/      opt-in features (e.g. debug sidecar, monitoring) as kind: Component
  overlays/
    dev/           kustomization.yaml: resources [../../base], namespace, images, patches, replicas
    prod/
```

```yaml
# overlays/prod/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: shop
resources: [../../base]
components: [../../components/monitoring]
labels:
  - pairs: {app.kubernetes.io/part-of: shop}
    includeSelectors: false          # never add labels to immutable selectors after first deploy
images:
  - name: api
    newName: registry.example.com/shop/api
    digest: sha256:0123...
replicas:
  - {name: api, count: 4}
configMapGenerator:
  - name: api-config
    envs: [api.env]                  # hash suffix rolls pods when content changes
patches:
  - path: resources-patch.yaml       # strategic merge
  - target: {kind: Deployment, name: api}
    patch: |-
      - op: add
        path: /spec/template/spec/topologySpreadConstraints
        value: [{maxSkew: 1, topologyKey: topology.kubernetes.io/zone, whenUnsatisfiable: ScheduleAnyway, labelSelector: {matchLabels: {app.kubernetes.io/name: api}}}]
```

Rules:
- `commonLabels` is deprecated and rewrites selectors; use `labels` with `includeSelectors: false`.
- Remote bases only with a pinned `?ref=<tag or sha>`.
- `kubectl kustomize` bundles an older kustomize than the standalone binary; render in CI with the
  same binary the GitOps controller uses.
- Helm inside Kustomize: `helmCharts:` entries need `kustomize build --enable-helm`.

### Kustomize test commands

```bash
for o in k8s/overlays/*/; do kustomize build "$o" > "/tmp/$(basename "$o").yaml" || exit 1; done
kubeconform -strict -summary -kubernetes-version 1.31.0 /tmp/*.yaml
diff <(kustomize build k8s/overlays/dev) <(kustomize build k8s/overlays/prod)   # review env drift
```

## Choosing by failure mode

| Pain | Fix |
|---|---|
| values.yaml has 300 keys and nobody knows which matter | schema + defaults that work, document the 10 that matter in README |
| copy-pasted YAML per environment drifts | Kustomize base/overlays, or one chart with per-env values files |
| chart renders differently in CI and in Argo | same Helm version and `--kube-version`/`--api-versions` in both |
| secret values in values-prod.yaml | External Secrets / SOPS (`helm secrets` plugin) / sealed secrets; never plaintext in git |
