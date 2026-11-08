# Verification toolchain and fallbacks

Commands behind the container-craft ladder (section 3), with exit-code semantics and how to run each
tool from its upstream image when the binary is missing. Fallback images: use a pinned version tag,
record the resolved digest (`docker image inspect --format '{{index .RepoDigests 0}}' <img>`) in
Evidence, mount only the repo and read-only (`-v "$PWD:/w:ro" -w /w`), and add `--network none`
where the tool needs no downloads.

## L0 static

| Tool | Command | Pass | Fallback image |
|---|---|---|---|
| hadolint | `hadolint --failure-threshold warning Dockerfile` | exit 0 | `docker run --rm -i hadolint/hadolint:<ver> < Dockerfile` |
| BuildKit checks | `docker build --check .` | exit 0, no warnings | needs Docker with BuildKit |
| compose | `docker compose -f compose.yaml config -q` (or `podman compose config`) | exit 0 | - |
| yamllint | `yamllint -s k8s/` | exit 0 | `docker run --rm -v "$PWD:/w:ro" -w /w cytopia/yamllint:<ver> -s k8s/` |
| helm | `helm lint charts/x --strict -f <values>`; `helm template ... > rendered.yaml` | exit 0 | `docker run --rm -v "$PWD:/w:ro" -w /w alpine/helm:<ver> lint charts/x --strict` |
| kustomize | `kustomize build overlays/x > rendered.yaml` (or `kubectl kustomize`) | exit 0 | `registry.k8s.io/kustomize/kustomize:<ver>` |
| kubeconform | `kubeconform -strict -summary -kubernetes-version 1.31.0 -schema-location default -schema-location '<CRD catalog template>' rendered.yaml` | `Invalid: 0, Errors: 0` | `ghcr.io/yannh/kubeconform:<ver>` (needs network for schemas, or `-schema-location` to a local mirror) |
| kube-linter | `kube-linter lint rendered.yaml` | `No lint errors found!` | `stackrox/kube-linter:<ver> lint /w/rendered.yaml` |
| kube-score | `kube-score score --output-format ci rendered.yaml` | no `[CRITICAL]` | `zegl/kube-score:<ver> score /w/rendered.yaml` |
| trivy config | `trivy config --severity HIGH,CRITICAL --exit-code 1 .` | exit 0 | `aquasec/trivy:<ver> config /w` |
| Quadlet | `/usr/lib/systemd/system-generators/podman-system-generator --user --dryrun` | units printed, no errors | Linux host only |

CRD catalog template for kubeconform:
`https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json`.
CRDs not in the catalog: convert the CRD's OpenAPI schema with `openapi2jsonschema.py` from the
kubeconform repo into a local directory and add it as another `-schema-location`. Use
`-ignore-missing-schemas` only with the skipped kinds listed in Evidence.

## L1 build and image checks

```bash
docker build --load -t app:dev --label stack.run=$STAMP .                 # or: podman build -t localhost/app:dev .
docker run --rm --read-only --tmpfs /tmp --user 10001 app:dev --version   # starts as non-root on a read-only root
docker image inspect app:dev --format '{{.Config.User}} {{.Architecture}} {{.Size}}'
trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed app:dev
grype app:dev --fail-on high                                               # second opinion, different DB
docker buildx build --platform linux/amd64,linux/arm64 \
  --output type=oci,dest=.stack/out/container-expert/$STAMP/app-oci.tar .   # multi-arch without pushing
```

Scanner findings: record counts per severity and the fixed-version column; a base image bump is the
usual fix. Accepted risks go in `.trivyignore` with an expiry comment, never silently.
Scanners without a daemon: `podman save -o app.tar localhost/app:dev` then `trivy image --input app.tar`.

## L2 admission

```bash
kubectl --context <local> apply --dry-run=server -f rendered.yaml   # exit 0; read PSA "Warning:" lines too
kubectl --context <local> diff -f rendered.yaml                      # exit 1 means differences, >1 error
```

CRD-backed resources need the CRDs installed on the local cluster first (operator chart or
`kubectl apply -f crds/`), otherwise `no matches for kind`.

## L3 live

See [local clusters](local-clusters.md): run-owned kubeconfig, create, load, apply, rollout status,
in-cluster smoke request, policy probes, events captured to a file, teardown.

## Exit codes worth knowing

| Tool | Code | Meaning |
|---|---|---|
| kubeconform | 1 | invalid resources or errors |
| helm lint | 1 | chart errors (with `--strict`, warnings too) |
| trivy | value of `--exit-code` | findings at or above `--severity` |
| grype | 1 | `--fail-on` threshold reached |
| kubectl diff | 1 | differences found (not an error) |
| kubectl rollout status | 1 | timeout or failed progress deadline |

## Versions to record

`docker version --format '{{.Server.Version}}'`, `podman version --format '{{.Version}}'`,
`helm version --short`, `kubeconform -v`, `kube-linter version`, `trivy --version | head -1`,
`kind version`, `kubectl version --context <local>` (server line).
