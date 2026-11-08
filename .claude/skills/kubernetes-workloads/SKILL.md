---
name: kubernetes-workloads
description: "Kubernetes workload manifests that survive production: Deployment, StatefulSet, Job/CronJob and DaemonSet choice, startup/readiness/liveness probes, requests and limits with QoS classes, graceful shutdown, PodDisruptionBudgets, topology spread, HPA, ConfigMaps and Secrets wiring, native sidecars, plus Helm chart and Kustomize overlay authoring, all proven with kubeconform, helm lint/template, kube-linter and a server-side dry run. Load when writing, reviewing or fixing Kubernetes YAML, a Helm chart or a kustomization."
when_to_use: "Editing *.yaml under k8s/, deploy/, manifests/, charts/ or kustomize/; Chart.yaml, values.yaml, templates/*.yaml, kustomization.yaml; adding probes, resources, PDB, HPA or anti-affinity; pods restart during deploys or drop requests on rollout; helm template renders wrong; choosing Helm vs Kustomize."
---

# Kubernetes workloads

Authoring manifests, charts and overlays. Security policy (RBAC, NetworkPolicy, Pod Security) lives in
`kubernetes-security-policy`; failure diagnosis in `kubernetes-troubleshooting`; the image itself in
`container-images`. Target the cluster's minor version: `kubectl version` (server line) or the
`kubeVersion` the chart declares. Never use an API field newer than that floor.

Deep material: [Helm and Kustomize authoring](references/helm-kustomize.md)

## 1. Pick the controller

| Workload | Controller | Key fields |
|---|---|---|
| Stateless service, any replica can serve | `Deployment` | `strategy.rollingUpdate` (maxSurge 25%, maxUnavailable 0 for zero-downtime), `revisionHistoryLimit` |
| Stable identity or per-replica storage (databases, brokers) | `StatefulSet` + headless `Service` | `serviceName`, `volumeClaimTemplates`, `podManagementPolicy: Parallel` when ordering is not needed, `persistentVolumeClaimRetentionPolicy` |
| One per node (log shipper, CNI, node agent) | `DaemonSet` | tolerations for control-plane taints, `updateStrategy.rollingUpdate.maxUnavailable` |
| Run to completion | `Job` | `backoffLimit`, `activeDeadlineSeconds`, `ttlSecondsAfterFinished`, `completionMode: Indexed` for sharded work, `podFailurePolicy` |
| Scheduled | `CronJob` | `concurrencyPolicy: Forbid`, `startingDeadlineSeconds`, `timeZone`, history limits |

Every workload carries the recommended labels (`app.kubernetes.io/name`, `instance`, `version`,
`component`, `part-of`, `managed-by`). The selector uses only stable ones (`name`, `instance`): a
Deployment selector is immutable, and putting `version` in it breaks the next upgrade.

## 2. Probes

| Probe | Question it answers | Failure effect | Rule |
|---|---|---|---|
| `startupProbe` | has the app finished booting? | restarts after `failureThreshold x periodSeconds` | use for slow starters instead of a large `initialDelaySeconds`; liveness waits for it |
| `readinessProbe` | may it receive traffic now? | removed from Service endpoints, no restart | checks the app's own ability to serve; may check hard dependencies it cannot serve without |
| `livenessProbe` | is it wedged beyond self-recovery? | container restart | cheap, local, never checks downstream dependencies (a DB outage would restart every pod) |

```yaml
startupProbe:   {httpGet: {path: /healthz, port: http}, periodSeconds: 5, failureThreshold: 36}   # 180 s budget
readinessProbe: {httpGet: {path: /readyz, port: http}, periodSeconds: 5, failureThreshold: 3}
livenessProbe:  {httpGet: {path: /healthz, port: http}, periodSeconds: 10, failureThreshold: 3, timeoutSeconds: 2}
```

Use named ports (`ports: [{name: http, containerPort: 8080}]`). `grpc:` probes exist for gRPC health.
`exec` probes fork a process each period: avoid them on busy nodes. A liveness probe identical to
readiness with the same thresholds turns overload into a restart storm: give liveness a longer window.

## 3. Resources and QoS

| QoS class | Condition | Eviction order under node pressure |
|---|---|---|
| Guaranteed | every container has requests == limits for CPU and memory | last |
| Burstable | at least one request or limit set, not Guaranteed | middle (by usage over request) |
| BestEffort | no requests or limits anywhere | first |

Rules:
- Always set memory request and memory limit; set them equal for anything stateful or latency
  critical. Exceeding the memory limit is an OOM kill (exit 137, `OOMKilled`), not throttling.
- Always set a CPU request (scheduling and fair share). A CPU limit causes CFS throttling even on an
  idle node; omit it for latency-sensitive services unless a namespace `LimitRange` or policy demands
  one, and then size it with headroom (throttling shows in `container_cpu_cfs_throttled_periods_total`).
- Size from measurement: `kubectl top pod --containers` under representative load, or VPA in
  recommendation mode (`updateMode: "Off"`). Request about p95 usage, memory limit about p99 + 20-30%.
- Runtimes must see the limit: JVM `-XX:MaxRAMPercentage=75`, Go `GOMEMLIMIT` at about 90% of the
  limit (via the downward API `resourceFieldRef: {resource: limits.memory}`), Node
  `--max-old-space-size` below the limit.
- Namespace guard rails: `ResourceQuota` and `LimitRange` defaults; check them before blaming the pod.

## 4. Rollouts without dropped requests

1. `maxUnavailable: 0`, `maxSurge: 1` (or 25%), readiness probe that fails until the app can serve.
2. Graceful shutdown: the app handles SIGTERM by failing readiness, draining in-flight requests and
   exiting before `terminationGracePeriodSeconds` (default 30). Endpoints removal races with SIGTERM,
   so add a short wait before the server stops accepting:
   `lifecycle: {preStop: {sleep: {seconds: 5}}}` (the `sleep` action needs v1.30+; older clusters:
   `exec: {command: ["sleep", "5"]}`, which needs a `sleep` binary, absent in distroless).
3. Grace period > preStop + longest request drain.
4. `PodDisruptionBudget` with `maxUnavailable: 1` (or `minAvailable` as a percentage) so node drains
   do not take every replica; never a PDB that allows zero disruptions on a single replica (drains hang).
5. Spread: `topologySpreadConstraints` over `topology.kubernetes.io/zone` and `kubernetes.io/hostname`
   with `whenUnsatisfiable: ScheduleAnyway` for soft spread, `DoNotSchedule` only when you have the capacity.
6. `minReadySeconds: 10` stops a crash-after-ready image from completing a rollout.
7. Verify: `kubectl rollout status deploy/<name> --timeout=120s` (exit 0) on a local cluster.

## 5. Configuration and secrets

| Need | Use | Note |
|---|---|---|
| Non-secret config | `ConfigMap` via `envFrom` or a mounted file | env vars do not update in running pods; mounted files do (not with `subPath`) |
| Roll pods on config change | checksum annotation in the pod template (Helm `sha256sum`) or Kustomize `configMapGenerator` hash suffix | otherwise pods keep stale config |
| Secret values | `Secret` mounted as files, created from an external manager (External Secrets, Sealed Secrets, SOPS, CSI driver) | never commit plaintext Secret YAML; base64 is encoding, not encryption |
| Pod identity | dedicated `ServiceAccount`, `automountServiceAccountToken: false` unless the app calls the API | see `kubernetes-security-policy` |
| Downward API | `fieldRef` for pod name/namespace, `resourceFieldRef` for limits | feed `GOMEMLIMIT`, log labels |

## 6. Sidecars and init containers

- Native sidecars: an init container with `restartPolicy: Always` starts before the main containers,
  keeps running, and is stopped after them; Jobs complete when the main containers finish. Use it for
  proxies and log shippers when the cluster supports it (on by default since v1.29, stable in v1.33);
  on older clusters a sidecar in `containers` blocks Job completion.
- In-place resize of CPU/memory (`kubectl patch --subresource resize`) is beta from v1.33 and stable
  in v1.35; on older clusters a resource change restarts pods through a rollout.
- Plain init containers run to completion in order: migrations, waiting for a dependency (with a
  timeout), fetching config.

## 7. Autoscaling

- HPA `autoscaling/v2` on CPU utilisation needs CPU requests; target 60-75%. Add
  `behavior.scaleDown.stabilizationWindowSeconds: 300` to stop flapping.
- `minReplicas >= 2` for anything behind a PDB. Omit `spec.replicas` from a Deployment the HPA owns:
  every `kubectl apply` or Helm upgrade would otherwise reset the replica count the HPA chose.
- Queue-driven work: KEDA `ScaledObject` rather than CPU.

## 8. Helm or Kustomize

| Situation | Choose |
|---|---|
| Distributing a reusable package with many knobs to other teams | Helm chart |
| Your own app, a few environments differing by image tag, replicas, resources | Kustomize base + overlays |
| Third-party chart with local tweaks | `helm template` output fed into Kustomize (`helmCharts:` with `--enable-helm`) or chart values only |
| GitOps (Argo CD, Flux) | either; render in CI exactly as the controller will |

Helm essentials: `Chart.yaml` `apiVersion: v2`, `kubeVersion` constraint, `values.schema.json` to
reject bad values, `_helpers.tpl` for names and labels, `required` for mandatory values,
`toYaml | nindent` for blocks, `{{- with }}` for optional sections, never template Secrets with real
values. Kustomize essentials: `resources`, `patches` (strategic merge or JSON6902 with `target`),
`images` for tags, `replicas`, `configMapGenerator`, `components` for opt-in features; no remote
bases without a pinned ref. Details and test commands: [helm-kustomize](references/helm-kustomize.md).

## 9. The gate (run in this order, stop at the first failure)

```bash
# 0. render to plain YAML (one of)
kustomize build overlays/dev > /tmp/rendered.yaml          # or: kubectl kustomize overlays/dev
helm lint charts/app --strict -f charts/app/values-dev.yaml
helm template app charts/app -f charts/app/values-dev.yaml --kube-version 1.31 > /tmp/rendered.yaml
# 1. schema validation against the target minor version (CRDs from the catalog)
kubeconform -strict -summary -kubernetes-version 1.31.0 \
  -schema-location default \
  -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' \
  /tmp/rendered.yaml
# 2. best-practice lint
kube-linter lint /tmp/rendered.yaml          # and/or: kube-score score /tmp/rendered.yaml
# 3. API server admission (defaults, webhooks, PSA) on a LOCAL cluster only
kubectl --context kind-dev apply --dry-run=server -f /tmp/rendered.yaml
# 4. live: apply, wait, probe (local cluster only)
kubectl --context kind-dev apply -f /tmp/rendered.yaml
kubectl --context kind-dev rollout status deploy/app --timeout=120s
```

Missing binaries run from images: `docker run --rm -v "$PWD:/w:ro" -w /w ghcr.io/yannh/kubeconform:latest ...`,
`docker run --rm -v "$PWD:/w:ro" -w /w stackrox/kube-linter:latest lint /w/rendered.yaml`,
`docker run --rm -v "$PWD:/w:ro" -w /w alpine/helm:latest lint charts/app`. Pin tags in anything
committed. `kubectl apply --dry-run=client` validates almost nothing; never report it as proof.

## 10. Pitfalls (symptom -> cause -> fix)

| Symptom | Cause | Fix |
|---|---|---|
| `field is immutable` on `spec.selector` | selector changed (often a label added via Helm) | keep selectors to stable labels; recreate the object deliberately |
| 502s during every deploy | no preStop delay, readiness passes before warm-up, `maxUnavailable` > 0 | section 4 |
| Restart storm when the database blips | liveness checks the database | liveness local only |
| Pods pending after adding limits | `LimitRange` max or `ResourceQuota` exhausted | `kubectl describe quota,limitrange -n <ns>` |
| Config change has no effect | env from ConfigMap without a rollout | checksum annotation or generator hash |
| HPA shows `<unknown>` | no CPU request or no metrics-server | set requests; install metrics-server in kind |
| StatefulSet stuck at pod 0 | `OrderedReady` waiting for readiness of pod 0 | fix pod 0, or `Parallel` when safe |
| `no matches for kind ... in version` | removed API (e.g. `policy/v1beta1` PDB) | `kubectl api-resources`; migrate with `kubectl convert` or by hand |
| Helm upgrade rejects: `cannot patch ... field is immutable` | a Job or selector templated with a changing value | `helm.sh/hook` with `hook-delete-policy`, or stable names |

## 11. Review checklist

- [ ] Controller fits the workload; selectors use stable labels only.
- [ ] startup/readiness/liveness present with distinct purposes; liveness local.
- [ ] CPU request, memory request and memory limit on every container (init and sidecar too).
- [ ] Graceful shutdown: preStop delay, grace period, SIGTERM handled (PID 1, see `container-images`).
- [ ] PDB + spread for replicated services; `minReplicas >= 2` under HPA.
- [ ] Image pinned by digest or immutable tag; `imagePullPolicy` not `Always` on a mutable tag in prod.
- [ ] securityContext set (restricted profile, see `kubernetes-security-policy`).
- [ ] Gate passed: rendered, kubeconform strict, linter, server dry-run on a local cluster.

## 12. Worked example: zero-downtime fix for a chart

Report: "every Helm upgrade of `api` drops about 2% of requests". Rendered the chart with
`helm template api charts/api -f values-prod.yaml`, found `maxUnavailable: 25%`, no preStop, readiness
equal to liveness on `/` with a 1 s period. Changes: `maxUnavailable: 0`, `maxSurge: 1`,
`minReadySeconds: 10`, `preStop.sleep.seconds: 5`, `terminationGracePeriodSeconds: 40`, a
`/readyz` readiness probe and a slower `/healthz` liveness probe, a PDB `maxUnavailable: 1`. Gate:
`helm lint --strict` 0 errors, kubeconform `Summary: 9 resources found ... Valid: 9, Invalid: 0`,
kube-linter `No lint errors found!`. Live check on `kind-dev`: a `hey -z 60s` load against a
port-forward while running `kubectl rollout restart deploy/api`: 0 non-2xx responses (before: 41).
