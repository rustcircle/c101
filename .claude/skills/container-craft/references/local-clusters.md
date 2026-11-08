# Local clusters for verification and reproduction

Reference for the container-craft verification ladder (rungs L2-L3) and `kubernetes-troubleshooting`
section 5. Every cluster here is disposable: create it with a unique name (`ce-<stamp>`), delete it
when done, and never point these commands at a context that is not local.

Run-owned kubeconfig: kind, k3d and minikube otherwise write into `~/.kube/config` and switch the
user's current context. Before creating a cluster:

```bash
STAMP=$(date +%Y%m%d-%H%M); RUN=.stack/out/container-expert/$STAMP; mkdir -p "$RUN"
export KUBECONFIG="$PWD/$RUN/kubeconfig"       # kind and minikube write here instead of ~/.kube/config
```

## Which one

| Tool | Runs on | Strengths | Context name |
|---|---|---|---|
| kind | Docker or Podman (nodes are containers) | exact upstream Kubernetes, pick the version by node image, multi-node, CI-friendly | `kind-<name>` |
| k3d | Docker | k3s (light, fast start), built-in local registry and load balancer | `k3d-<name>` |
| minikube | Docker, Podman, VMs | addons (ingress, metrics-server, registry), closest to a single VM node | `minikube` or `<profile>` |
| Docker Desktop / Rancher Desktop / OrbStack | their VM | already running on the laptop | `docker-desktop`, `rancher-desktop`, `orbstack` |

Default to kind; use the node image whose minor version matches the target cluster.

## kind

```bash
cat > /tmp/kind.yaml <<'YAML'
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings: [{containerPort: 30080, hostPort: 30080}]   # NodePort reachable on localhost
  - role: worker
  - role: worker
# networking: {disableDefaultCNI: true}    # then install Calico or Cilium for CNI-specific policy tests
YAML
kind create cluster --name t1 --config /tmp/kind.yaml --image kindest/node:v1.31.<patch> --wait 120s
kubectl config current-context                          # kind-t1
kind load docker-image app:dev --name t1                # local image into every node
kind load image-archive app.tar --name t1               # e.g. from podman save / buildah push oci-archive
kubectl --context kind-t1 get nodes
kind delete cluster --name t1
```

- Use the node image tags listed in the release notes of the installed kind version
  (`kind version`); other combinations may not boot.
- With Podman: `KIND_EXPERIMENTAL_PROVIDER=podman kind create cluster ...` (rootless needs cgroup v2
  delegation; see `podman-rootless`).
- metrics-server for HPA/top tests: apply the upstream manifest and add `--kubelet-insecure-tls` to
  its args (kind kubelets use self-signed certificates).
- Ingress: install ingress-nginx's kind provider manifest, map ports 80/443 in the config.
- NetworkPolicy: kindnetd enforces it (kind v0.24+); check with a probe pod before trusting it.

## k3d

```bash
k3d cluster create t1 --kubeconfig-update-default=false --kubeconfig-switch-context=false --agents 2 --image rancher/k3s:v1.31.<patch>-k3s1 \
  --registry-create t1-registry:0.0.0.0:5001 -p "8080:80@loadbalancer" --wait
docker tag app:dev localhost:5001/app:dev && docker push localhost:5001/app:dev   # the throwaway local registry only
k3d kubeconfig get t1 > "$KUBECONFIG"                # run-owned kubeconfig
# in manifests: image: t1-registry:5001/app:dev
k3d image import app:dev -c t1                           # alternative without a registry
k3d cluster delete t1
```

k3s ships Traefik and a local-path StorageClass; disable Traefik with `--k3s-arg "--disable=traefik@server:0"`
when testing another ingress. Pushing to `localhost:5001` is a push to the local throwaway registry,
not to a shared registry; any other registry host needs user confirmation.

## minikube

```bash
minikube start -p t1 --kubernetes-version=v1.31.<patch> --driver=docker --cpus=4 --memory=6g
minikube -p t1 addons enable metrics-server
minikube -p t1 image load app:dev
minikube -p t1 service api --url                         # reachable URL for a NodePort/LB service
minikube delete -p t1
```

## Standard verification run (rung L3)

```bash
set -euo pipefail
CTX=kind-t1
case "$CTX" in kind-*|k3d-*|minikube|docker-desktop|rancher-desktop|orbstack) ;; *) echo "refusing: $CTX is not local" >&2; exit 2;; esac
kubectl --context $CTX create namespace verify --dry-run=client -o yaml | kubectl --context $CTX apply -f -
kubectl --context $CTX -n verify apply --dry-run=server -f rendered.yaml
kubectl --context $CTX -n verify apply -f rendered.yaml
kubectl --context $CTX -n verify rollout status deploy/app --timeout=180s
kubectl --context $CTX -n verify get pods -o wide
kubectl --context $CTX -n verify run smoke --rm -i --restart=Never --image=curlimages/curl:8.10.1 -- \
  curl -fsS -m 5 http://app:8080/readyz
kubectl --context $CTX -n verify get events --sort-by=.lastTimestamp | tail -20 > .stack/out/container-expert/events.txt
```

Record: cluster tool and version, node image, Kubernetes server version, every command with exit
code, and the teardown. A local cluster proves scheduling, admission, probes, policies and wiring;
it does not prove cloud load balancers, storage classes, IAM bindings or production quotas: list
those as unverified.

## When no local cluster is possible

No Docker/Podman daemon, or not allowed to create one: stop at rungs L0-L1, which need no
cluster (render, kubeconform -strict, kube-linter, trivy config), say "not run on a cluster" in
Evidence and cap confidence at 0.6 for runtime behaviour claims.
