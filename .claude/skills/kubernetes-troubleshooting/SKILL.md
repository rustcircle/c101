---
name: kubernetes-troubleshooting
description: "Diagnosing failing Kubernetes workloads from evidence: a read-only triage order (get, describe, events, logs --previous, exit codes), playbooks for CrashLoopBackOff, OOMKilled, ImagePullBackOff, Pending/unschedulable, CreateContainerConfigError, failing probes, stuck rollouts, Service with no endpoints and DNS, kubectl debug with ephemeral containers, pod copies and node shells, and reproducing the failure on a local kind, k3d or minikube cluster. Load when a pod, rollout, Job or Service misbehaves."
when_to_use: "A pod shows CrashLoopBackOff, OOMKilled, Error, ImagePullBackOff, ErrImagePull, Pending, CreateContainerConfigError, Init:CrashLoopBackOff or Terminating forever; kubectl rollout status hangs; a Service returns connection refused or has no endpoints; exit code 137, 139 or 143; needing a shell in a distroless container; setting up kind, k3d or minikube to reproduce a cluster problem."
---

# Kubernetes troubleshooting

Evidence first, one hypothesis at a time (method: `debugging-method`). Every command below is
read-only unless marked LOCAL ONLY; run mutating or debug-container commands only against a local
cluster context (kind-*, k3d-*, minikube, docker-desktop) unless the brief explicitly names the
context and the action. Always pass `--context` explicitly.

Local clusters (kind, k3d, minikube, run-owned kubeconfig): `container-craft` reference
`references/local-clusters.md` (the hub is preloaded by container-expert; Read that file by path).

## 1. Triage order (read-only)

```bash
K="kubectl --context $CTX -n $NS"
$K get pods -o wide                                   # STATUS, RESTARTS, NODE, AGE
$K describe pod <pod>                                 # Events at the bottom, Last State, Exit Code, Reason
$K get events --sort-by=.lastTimestamp | tail -30     # or: kubectl events --for pod/<pod>
$K logs <pod> -c <container> --previous --tail=200    # the crashed instance, not the restarted one
$K get pod <pod> -o jsonpath='{range .status.containerStatuses[*]}{.name}{" "}{.lastState.terminated.reason}{" "}{.lastState.terminated.exitCode}{"\n"}{end}'
$K get deploy,rs,svc,endpointslices,pdb,hpa
kubectl --context $CTX top pod -n $NS --containers    # needs metrics-server
```

Write down the exact status, reason, exit code and the first error line before forming a hypothesis.

## 2. Exit codes

| Code | Meaning | Usual cause |
|---|---|---|
| 0 | exited cleanly | a server process that is not long-running (wrong CMD, script backgrounds the server), or a Job done |
| 1, 2 | application error | config, missing env, failed migration: read `--previous` logs |
| 126 | not executable | wrong permissions, exec bit lost, noexec mount |
| 127 | command not found | wrong entrypoint, shell form in distroless (no `/bin/sh`) |
| 128+n | killed by signal n | 137 = SIGKILL (OOM kill or grace period expired), 143 = SIGTERM, 139 = SIGSEGV, 134 = SIGABRT |
| `exec format error` in logs | architecture mismatch | arm64 image on amd64 node or vice versa: build multi-arch (`container-images`) |

## 3. Playbooks

### CrashLoopBackOff
1. `--previous` logs and exit code (table above). No logs at all: the process dies before logging
   (entrypoint, missing binary, permission on a read-only filesystem).
2. Liveness kill vs crash: `describe` shows `Liveness probe failed ... will be restarted` when the
   probe killed it; then fix the probe (startupProbe for slow boots) not the app.
3. Config: `$K get pod <pod> -o yaml | yq '.spec.containers[].env'` (never print Secret values);
   compare with what the app expects.
4. Reproduce the container locally with the same image, command, env and user:
   `docker run --rm --read-only --user 10001 -e ... <image@digest>`.

### OOMKilled (reason OOMKilled, exit 137)
1. Confirm: `lastState.terminated.reason == OOMKilled`. Exit 137 without OOMKilled is usually the grace
   period expiring after SIGTERM (app ignores SIGTERM, see PID 1 in `container-images`).
2. Compare limit with real usage: `top pod --containers`, `container_memory_working_set_bytes`.
3. Runtime not limit-aware (JVM heap, Go without `GOMEMLIMIT`, Node old-space) vs a real leak (usage
   grows with time or requests): leaks go to the language expert with a heap profile.
4. Node-level OOM or eviction instead: `describe node` shows `MemoryPressure`, pod reason `Evicted`.

### ImagePullBackOff / ErrImagePull
Read the event message; it says which of these it is:

| Message fragment | Cause | Fix |
|---|---|---|
| `not found`, `manifest unknown` | wrong repo, tag or digest | check the reference; `docker manifest inspect <ref>` / `crane digest <ref>` |
| `unauthorized`, `denied` | missing or wrong `imagePullSecrets`, wrong SA | secret in the same namespace, referenced by pod or ServiceAccount |
| `no matching manifest for linux/arm64` | single-arch image | multi-arch build |
| `toomanyrequests` | registry rate limit (Docker Hub) | mirror, authenticated pulls |
| `dial tcp ... i/o timeout`, `x509` | node cannot reach registry, private CA | network egress, containerd registry config |
| kind/k3d with a local tag | image never reached the cluster nodes | `kind load docker-image <img> --name <cluster>` or a local registry; `imagePullPolicy: IfNotPresent` |

### Pending
`describe pod` Events show the scheduler's reason: `Insufficient cpu/memory` (requests too big or
quota), `didn't match Pod's node affinity/selector`, `had untolerated taint`, `pod has unbound
immediate PersistentVolumeClaims` (`$K get pvc`, StorageClass, `WaitForFirstConsumer`),
`didn't match pod topology spread constraints`. Fix the spec, not the node, unless the brief is
about capacity.

### CreateContainerConfigError / RunContainerError
Missing ConfigMap or Secret key referenced by `valueFrom`/`envFrom`/volume, or `runAsNonRoot` with an
image whose user is root or non-numeric (`container has runAsNonRoot and image has non-numeric user`).

### Rollout stuck
`kubectl rollout status` hangs: new ReplicaSet pods never become Ready (see readiness), a PDB plus
`maxUnavailable: 0` with no capacity for surge (Pending), or `progressDeadlineSeconds` exceeded
(`$K get deploy -o yaml | yq .status.conditions`). Roll back on a local cluster with
`kubectl rollout undo`; on any other context return it as an Open doubt.

### Service unreachable
1. Endpoints: `$K get endpointslices -l kubernetes.io/service-name=<svc>`. Empty: selector does not
   match pod labels, or pods not Ready.
2. Ports: Service `targetPort` must equal the container port (name or number).
3. From inside the cluster: an ephemeral or throwaway pod (LOCAL ONLY unless authorised):
   `kubectl run -it --rm net --image=nicolaka/netshoot --restart=Never -- curl -sv http://<svc>.<ns>:<port>`.
4. DNS: `nslookup <svc>.<ns>.svc.cluster.local` from that pod; CoreDNS logs in kube-system.
5. NetworkPolicy denying it: `$K get networkpolicy`; see `kubernetes-security-policy`.

### Terminating forever
Finalizers (`$K get <obj> -o jsonpath='{.metadata.finalizers}'`) waiting on a controller, or a node
that is gone. Removing finalizers by patch skips cleanup: never do it outside a local cluster, and say
what cleanup is skipped.

## 4. kubectl debug (LOCAL ONLY unless the brief authorises it on a named context)

| Situation | Command |
|---|---|
| Shell beside a running distroless container, sharing its process namespace | `kubectl debug -it <pod> --image=busybox:1.36 --target=<container> --profile=general` |
| Crashing pod: a copy with a different command, so it stays up | `kubectl debug <pod> -it --copy-to=<pod>-dbg --container=<container> -- sh` |
| Copy with a different image (e.g. the debug variant) | `kubectl debug <pod> --copy-to=<pod>-dbg --set-image=<container>=<image>:debug` |
| Node-level inspection (host filesystem at /host) | `kubectl debug node/<node> -it --image=busybox:1.36 --profile=sysadmin` |

Ephemeral containers cannot be removed from a pod after creation (the pod must be deleted); copies
and node debug pods must be deleted when done. `--profile` values: legacy, general, baseline,
netadmin, restricted, sysadmin; under restricted PSS use `--profile=restricted`. Tools inside:
`/proc/1/root` of the target for its filesystem, `ss -ltnp` for listening ports. The default profile
is `legacy` up to kubectl 1.35 and `general` from 1.36: always pass `--profile` explicitly.

## 5. Reproduce locally

A cluster-side bug is fixed when it is reproduced and then gone on a local cluster with the same
manifests (rendered), same image digest and same Kubernetes minor version. Quick start:

```bash
export KUBECONFIG=.stack/out/container-expert/<stamp>/kubeconfig     # run-owned; ~/.kube/config untouched
kind create cluster --name repro --image kindest/node:v1.31.<patch> --wait 60s   # match the target minor
kind load docker-image app:dev --name repro
kubectl --context kind-repro apply -f rendered.yaml
kubectl --context kind-repro rollout status deploy/app --timeout=120s
kind delete cluster --name repro                                                  # always clean up
```

k3d, minikube, local registries, ingress, metrics-server and CNI swaps: `container-craft/references/local-clusters.md`.

## 6. Reporting a diagnosis

| Field | Example |
|---|---|
| Symptom | `api-7d9f` CrashLoopBackOff, 14 restarts in 20 min |
| Evidence | `lastState.terminated.reason=OOMKilled exitCode=137`; limit 256Mi; working set 250Mi at crash |
| Root cause | `-Xmx512m` in `JAVA_OPTS` exceeds the 256Mi limit (JDK 21 is container aware; the explicit flag overrides it) |
| Fix | remove `-Xmx`, `-XX:MaxRAMPercentage=75`, limit 512Mi |
| Proof | kind repro: OOMKilled within 3 min before; 30 min soak after, 0 restarts, working set 380Mi |

Never state a root cause that the evidence column does not support; list competing hypotheses with
the next discriminating check instead.

## 7. Pitfalls

- Reading logs of the restarted container instead of `--previous`.
- Treating exit 137 as OOM without checking the reason.
- Fixing a probe-induced restart by raising memory.
- `kubectl delete pod` as a fix: the controller recreates it with the same spec.
- Debugging on production with mutating commands "just to look": port-forward, exec, debug and
  run are not read-only; they need explicit authorisation outside a local cluster.
