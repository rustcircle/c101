---
name: container-craft
description: "Container and orchestration expertise hub: orienting in Docker, Podman, Compose, Helm, Kustomize and raw Kubernetes repos, the safety model (local vs production kube contexts and container engines, no registry or signing writes, no secret output), the verification ladder from hadolint, kubeconform, helm lint and kube-linter through image builds and trivy/grype scans to server dry runs and live checks on a disposable kind cluster, OCI image and registry facts, runtime choice tables and a routing table to the granular container and Kubernetes playbooks. Load when building, running, deploying, reviewing or debugging containers or Kubernetes workloads."
when_to_use: "Any task touching Dockerfile/Containerfile, compose.yaml, Quadlet files, Kubernetes manifests, Helm charts, kustomizations, image tags and digests, registries or kubeconfig contexts; CrashLoopBackOff, OOMKilled or ImagePullBackOff; choosing Docker vs Podman or Compose vs Kubernetes; proving a manifest or image works."
---

# Container craft

Hub for container and Kubernetes work. It holds the rules every task needs (orientation, safety,
verification); task detail lives in the granular skills (section 9). Image build craft is in
`container-images`, which this hub reuses rather than repeats.

Deep material:
[verification toolchain and fallbacks](references/verification-toolchain.md) |
[local clusters: kind, k3d, minikube](references/local-clusters.md)

## 1. Orient

```bash
git ls-files | grep -iE '(^|/)(Dockerfile|Containerfile)[^/]*$|compose[^/]*\.ya?ml$|\.dockerignore$|docker-bake\.hcl$'
git ls-files | grep -iE '\.(container|pod|kube|network|volume|build|image)$'            # Quadlet
git ls-files | grep -iE '(^|/)(Chart\.yaml|values[^/]*\.yaml|kustomization\.ya?ml)$'
git ls-files '*.yaml' '*.yml' | xargs grep -lE '^kind: (Deployment|StatefulSet|DaemonSet|Job|CronJob|Pod)$' 2>/dev/null | head
for t in docker podman buildah kubectl helm kustomize kind k3d minikube hadolint trivy grype kubeconform kube-linter kube-score crane skopeo; do printf '%-12s %s\n' "$t" "$(command -v $t || echo -)"; done
kubectl config get-contexts -o name 2>/dev/null; echo "DOCKER_HOST=${DOCKER_HOST:-unset}"
docker context ls 2>/dev/null; podman system connection list 2>/dev/null
```

Record: which engine builds images (Docker/BuildKit, Podman/Buildah), how the app is deployed
(compose, Quadlet, Helm, Kustomize, raw YAML, GitOps controller), the target Kubernetes minor version
(chart `kubeVersion`, CI kind image, cluster docs), the CI commands that build, lint and scan
(`.github/workflows/*.yml`), and which verification tools exist. The CI commands are the contract.

## 2. Safety model (hard rules)

### 2.1 Kubernetes targets
A context is **local** only when its name is `kind-*`, `k3d-*`, `minikube` (or a minikube profile),
`docker-desktop`, `rancher-desktop` or `orbstack` AND its server is on the loopback or local VM
network (`kubectl config view --minify --context <c> -o jsonpath='{.clusters[0].cluster.server}'`).
Every other context is **production**, whatever its name says.

- Prefer a run-owned cluster with its own kubeconfig (`export KUBECONFIG=.stack/out/container-expert/<stamp>/kubeconfig`
  before `kind create cluster`), so the user's `~/.kube/config` and current context stay untouched.
- On an existing local context, work in a namespace you create (`verify-<stamp>`) and delete only that.
- Always pass the context explicitly: `kubectl --context`, `helm --kube-context`. Never run
  `kubectl config use-context`.
- On a **production** context, and only when the brief names that context, the allowed commands are:
  `kubectl get, describe, logs, events, top, explain, api-resources, api-versions, version, auth can-i, diff`
  and `helm list, status, history, template`. Everything else is mutating, including `apply`
  (also `--dry-run=server`, which runs admission webhooks), `exec`, `cp`, `edit`, `patch`, `label`,
  `annotate`, `set`, `scale`, `rollout restart|undo|pause`, `cordon`, `drain`, `taint`, `run`, `debug`,
  `port-forward`, `delete`, any kubectl plugin, `helm install|upgrade|rollback|uninstall|test`, and
  `argocd`/`flux` commands. Return those as a `needs-user` Open doubt with the exact command.
- No context named in the brief: touch no production context at all.

### 2.2 Container engines
- Engine is local when `docker context inspect` shows a `unix://` socket (Docker Desktop, OrbStack,
  Colima) and `DOCKER_HOST` is unset or a local socket; for Podman, the default connection is the
  local socket or a `podman machine` VM. A `tcp://` or `ssh://` engine is production: read-only
  (`ps`, `images`, `inspect` without printing env) only.
- Label what you create (`--label stack.run=<stamp>`, compose project `-p ce-<stamp>`) and clean up
  by that label or project only. Never `system prune`, `volume prune`, `compose down -v` on a project
  you did not create, or `rm` containers/volumes you did not create.

### 2.3 Registries and signing (never without explicit user confirmation)
Never run anything that writes to a remote registry or transparency log: `docker|podman|buildah|helm|oras|crane push`,
any `--push`, `--output type=registry` or `push=true`, `buildx imagetools create`, `podman manifest push`,
`skopeo copy|sync` to a remote destination, `crane copy|mutate|append|tag`, `ko build` to a remote repo,
`docker compose push`, `cosign sign|attest|upload` (keyless signing writes a permanent public log
entry), `docker login`/`helm registry login`. Local equivalents: `--load` (single platform) or
`--output type=oci,dest=.stack/out/container-expert/<stamp>/img.tar` (multi-platform), `kind load`,
`k3d image import`, a throwaway registry on `localhost` that you started. The push and signing
recipes in `container-images` sections 7-8 belong in CI (`ci-pipelines`); hand them back as
`needs-user` with the exact command.

The `pre-tool` hook backs these rules up (`config/policy.json` `outward_actions`): registry writes and
changes on a context outside `kind-*`, `k3d-*`, `minikube`, `docker-desktop`, `rancher-desktop`, `orbstack`
(or with a kubeconfig outside `.stack/`) return `ask`. Treat that prompt as a mistake on your side, not a gate to pass.

### 2.4 Secrets
Never print: Secret data (`kubectl get secret -o yaml|json`, `-o jsonpath` on `.data`), `helm get
values|manifest|all` (rendered secrets), `kubectl get pod|cm -o yaml` without filtering env,
`kubectl config view --raw`, `docker inspect`/`podman inspect` env sections, `~/.docker/config.json`,
`podman secret inspect --showsecret`, registry tokens. List key names only (`jq 'keys'`) and redact.

## 3. Verification ladder (no claim without a rung)

| Rung | Proves | Commands (details: [toolchain](references/verification-toolchain.md)) |
|---|---|---|
| L0 static | syntax, schema, best practice | `hadolint Dockerfile`, `docker build --check .`, `docker compose config -q`, `helm lint --strict`, `helm template` / `kustomize build`, `kubeconform -strict -kubernetes-version <v>`, `kube-linter lint`, `kube-score score`, `trivy config`, Quadlet generator `--dryrun` |
| L1 build | the image builds and starts | `docker build` / `podman build` (`--load`), `docker run --rm --read-only --user <uid> <img> --version`, size and user via `image inspect`, `trivy image --severity HIGH,CRITICAL` or `grype`, multi-arch via `--platform` to an OCI tar |
| L2 admission | the API server accepts it (defaults, PSA, webhooks) | `kubectl --context <local> apply --dry-run=server -f rendered.yaml` |
| L3 live | it schedules, becomes Ready, serves and obeys policy | kind/k3d cluster: load image, apply, `rollout status --timeout`, in-cluster curl, probe-pod policy checks, `auth can-i` tables, teardown |

Rules:
- Pick the highest rung the change needs: a Dockerfile change needs L0+L1; a manifest or chart
  change needs L0+L2 and L3 when probes, policies, rollout or wiring changed.
- A missing binary runs from its upstream image with the repo mounted read-only (toolchain
  reference). If neither works, report the rung as UNVERIFIED and cap confidence at 0.6.
- `kubectl apply --dry-run=client` and "looks right" are not rungs.
- Record tool versions (`kubeconform -v`, `helm version --short`, `kind version`) with results.

## 4. Choosing runtimes and packaging

| Situation | Choose |
|---|---|
| Developer laptop, multi-service app | Compose (`container-images` section 9), or `podman kube play` when the target is Kubernetes |
| Single host, long-running services, no cluster | Podman + Quadlet (`podman-rootless`) |
| Several hosts, rolling updates, autoscaling, self-healing | Kubernetes (`kubernetes-workloads`) |
| CI runners without a Docker daemon or privileged mode | Buildah / `podman build`, or BuildKit rootless |
| Reusable package for other teams | Helm chart |
| Own app across environments | Kustomize base + overlays |

Docker vs Podman: same OCI images and mostly the same CLI. Podman is daemonless and rootless by
default and integrates with systemd; Docker has BuildKit/buildx and Compose as first-class tools.
Follow what the repo and CI already use; do not migrate engines as a side effect.

## 5. OCI images and registries (read-only facts)

- A reference is `registry/repo:tag@sha256:digest`; the digest pins content, the tag is mutable.
  Multi-arch images are an index (manifest list) of per-platform manifests.
- Inspect without pulling: `crane manifest <ref>`, `crane digest <ref>`, `skopeo inspect docker://<ref>`,
  `docker buildx imagetools inspect <ref>`, `regctl manifest get`. All are read-only.
- Short names (`nginx`) resolve differently in Docker (docker.io) and Podman
  (`unqualified-search-registries`): write fully qualified names in files.
- Media types: Docker v2 schema 2 and OCI; attestations (SBOM, provenance) are attached manifests
  that some older registries or tools reject.
- Rate limits and pull secrets: see `kubernetes-troubleshooting` (ImagePullBackOff).

## 6. Pitfalls (symptom -> cause -> where)

| Symptom | Cause | Playbook |
|---|---|---|
| exit 137 / OOMKilled | memory limit vs runtime heap | `kubernetes-troubleshooting` |
| SIGTERM ignored, slow stops | shell-form ENTRYPOINT, no init | `container-images` section 5 |
| `exec format error` | wrong architecture | `container-images` section 7 |
| image works in Docker, not rootless Podman | UID mapping, SELinux labels | `podman-rootless` section 2 |
| `violates PodSecurity "restricted"` | missing securityContext | `kubernetes-security-policy` section 1 |
| requests dropped on rollout | probes, preStop, PDB | `kubernetes-workloads` section 4 |
| works on kind, fails in prod | storage class, LB, IAM, quotas, admission webhooks not on kind | say so: list as unverified |

## 7. Review checklist

- [ ] Images: multi-stage, pinned base by digest, non-root numeric USER, exec-form ENTRYPOINT, no
      secrets in layers, scan clean at the agreed severity (`container-images`).
- [ ] Manifests: probes, requests/limits, restricted securityContext, PDB/spread, digest-pinned image.
- [ ] Policies: RBAC least privilege, default-deny NetworkPolicy with DNS.
- [ ] Every claim backed by a ladder rung with command and exit code; unverified rungs named.
- [ ] No production context touched beyond the allowlist; no registry or signing write; no secret printed.

## 8. Worked example

Brief: "our Helm chart's api pods crash after the base image bump". Orient: chart `charts/api`,
CI uses kind `v1.31` and kubeconform. L0: `helm lint --strict` clean, kubeconform `Valid: 8`.
L1: `docker build --load -t api:dev .` then `docker run --rm --read-only --user 10001 api:dev`
fails `open /tmp/x: read-only file system`: the new base dropped its `/tmp` volume. Fix: `emptyDir`
for `/tmp` in the chart (the image stays read-only). L3: `KUBECONFIG=.stack/out/container-expert/<stamp>/kubeconfig
kind create cluster --name ce-<stamp> --image kindest/node:v1.31.<patch>`, `kind load docker-image
api:dev`, `helm --kube-context kind-ce-<stamp> upgrade --install api charts/api --set image.tag=dev
--wait`, `rollout status` exit 0, in-cluster curl `/readyz` 200, then `kind delete cluster`.
Pushing the fixed image is returned as `needs-user`.

## 9. Granular skills

Load one with the Skill tool by name when the task matches; they are listed by name only, so this
table is their description. A skill whose pack is not enabled is off: work from this hub and say so.

| skill | load when |
|---|---|
| `kubernetes-workloads` | writing or reviewing Deployments, StatefulSets, Jobs, probes, resources/QoS, PDB, HPA, Helm charts or Kustomize overlays |
| `kubernetes-security-policy` | RBAC, ServiceAccounts, NetworkPolicy, Pod Security Standards, securityContext hardening, admission policy |
| `kubernetes-troubleshooting` | CrashLoopBackOff, OOMKilled, ImagePullBackOff, Pending, stuck rollouts, unreachable Services, `kubectl debug` |
| `podman-rootless` | rootless Podman, pods, `podman kube play`, Quadlet units, Buildah, podman machine, Docker compatibility |

From the `devops` pack (hub `coding-general`):

| skill | load when |
|---|---|
| `container-images` | Dockerfile/Containerfile craft, BuildKit mounts, base images, multi-arch, SBOM, scanning, compose for local dev |
| `ci-pipelines` | image build, scan, sign and push jobs in CI; kind-based integration jobs |
| `observability-instrumentation` | logs, metrics and traces for services in containers |
| `shell-scripting` | entrypoint scripts and run steps |

From core: `security-review` (security checklist for audits), `debugging-method` (hypothesis log).
