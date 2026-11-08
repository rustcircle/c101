---
name: kubernetes-security-policy
description: "Kubernetes workload hardening and access policy: least-privilege RBAC (Roles, bindings, ServiceAccounts, token automount), NetworkPolicy default-deny with DNS and explicit flows, Pod Security Standards and admission labels, the restricted securityContext, image provenance admission, Secrets handling, and proving each policy with kubectl auth can-i, probe pods on a local kind cluster, kube-linter, kube-score and trivy config. Load when writing or reviewing RBAC, NetworkPolicy, Pod Security or securityContext settings."
when_to_use: "Editing Role/ClusterRole/RoleBinding/ServiceAccount/NetworkPolicy YAML or namespace labels; a pod is rejected with 'violates PodSecurity'; 'forbidden: User system:serviceaccount:... cannot'; hardening a chart to the restricted profile; asking which pods can talk to which; kube-linter, kube-score, trivy config or checkov findings."
---

# Kubernetes security policy

Defensive configuration of workloads and access. Threat modelling and full audits belong to
`security-auditor` (skill `security-review`); this skill is how to write the policy and prove it works.
Image-level hardening (non-root user, minimal base, scanning) is in `container-images`.

## 1. Pod Security Standards (PSS) and admission

Namespaces opt in with labels; the built-in Pod Security Admission controller enforces them.

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: shop
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest   # pin a minor (v1.31) for stable behaviour
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
```

Roll out with `warn`/`audit` first, read the warnings, then `enforce`. Dry-run the label against
existing pods (local cluster): `kubectl label --dry-run=server --overwrite ns shop
pod-security.kubernetes.io/enforce=restricted` prints every pod that would violate it.

| Profile | For | Blocks |
|---|---|---|
| privileged | system namespaces, CNI, CSI | nothing |
| baseline | legacy apps | hostNetwork/hostPID/hostIPC, privileged, hostPath, added capabilities beyond a small set, hostPort |
| restricted | every application namespace | baseline + must run as non-root, no privilege escalation, drop ALL capabilities (adding back only NET_BIND_SERVICE), seccomp RuntimeDefault or Localhost, restricted volume types |

### The restricted container template

```yaml
spec:
  automountServiceAccountToken: false
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001            # numeric; must match the image USER (see container-images)
    runAsGroup: 10001
    fsGroup: 10001
    seccompProfile: {type: RuntimeDefault}
  containers:
    - name: app
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities: {drop: ["ALL"]}
      volumeMounts: [{name: tmp, mountPath: /tmp}]
  volumes: [{name: tmp, emptyDir: {sizeLimit: 64Mi}}]
```

`readOnlyRootFilesystem` is not required by PSS but is expected by kube-linter/kube-score and
removes a whole class of persistence; every writable path becomes an explicit `emptyDir`.
Policy engines (Kyverno, OPA Gatekeeper, ValidatingAdmissionPolicy with CEL) add rules PSS lacks:
allowed registries, required digests, required labels, signature verification.

## 2. RBAC

Principles: one ServiceAccount per workload; `automountServiceAccountToken: false` unless the app
calls the API; namespaced `Role` over `ClusterRole`; list exact `resources`, `verbs` and, where
possible, `resourceNames`; no wildcards.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: {name: leader-election, namespace: shop}
rules:
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["get", "create", "update"]
    # resourceNames cannot restrict "create"; keep create separate if you narrow the others
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: api-leader-election, namespace: shop}
subjects: [{kind: ServiceAccount, name: api, namespace: shop}]
roleRef: {apiGroup: rbac.authorization.k8s.io, kind: Role, name: leader-election}
```

Dangerous grants (flag every one in review):

| Grant | Why it is effectively cluster-admin or a breakout |
|---|---|
| `*` on resources or verbs | everything, including future resources |
| `create` on `pods` (or workloads) in a namespace | can mount any Secret and ServiceAccount of that namespace, or run privileged where PSS allows |
| `get/list/watch` on `secrets` | reads every token and credential in scope |
| `escalate`, `bind`, `impersonate` | grants itself more |
| `create` on `serviceaccounts/token` | mints tokens for other identities |
| `update/patch` on `nodes/proxy`, `pods/exec`, `pods/attach`, `pods/ephemeralcontainers` | command execution in other pods |
| ClusterRoleBinding to `system:authenticated` or `system:anonymous` | everyone |

Proof (local cluster; impersonation itself needs admin rights there):

```bash
kubectl --context kind-dev auth can-i --list --as=system:serviceaccount:shop:api -n shop
kubectl --context kind-dev auth can-i get secrets --as=system:serviceaccount:shop:api -n shop   # expect: no
kubectl --context kind-dev auth can-i update leases --as=system:serviceaccount:shop:api -n shop  # expect: yes
```

Write the expected yes/no table into the Evidence; a policy without negative checks is unproven.
Offline review of rendered YAML: `kube-linter lint` (checks such as `access-to-secrets`,
`wildcard-in-rules`), `trivy config`, `rbac-tool`/`kubectl-who-can` where installed.

## 3. NetworkPolicy

Policies are allow-lists that apply only to pods they select, and only when the CNI enforces them.
Start each namespace with default deny, then allow named flows.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: default-deny, namespace: shop}
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: allow-dns, namespace: shop}
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}
          podSelector: {matchLabels: {k8s-app: kube-dns}}
      ports: [{protocol: UDP, port: 53}, {protocol: TCP, port: 53}]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: api-from-web, namespace: shop}
spec:
  podSelector: {matchLabels: {app.kubernetes.io/name: api}}
  policyTypes: [Ingress]
  ingress:
    - from: [{podSelector: {matchLabels: {app.kubernetes.io/name: web}}}]
      ports: [{protocol: TCP, port: 8080}]     # the container port, not the Service port
```

Pitfalls:
- `from: [{namespaceSelector: A, podSelector: B}]` (one element, AND) differs from
  `from: [{namespaceSelector: A}, {podSelector: B}]` (two elements, OR). Read the dashes.
- Default deny egress without the DNS rule breaks every name lookup; also allow the API server if the
  app calls it (its IP/port from `kubectl get endpoints kubernetes`, via `ipBlock`).
- Ports are pod ports after Service translation. `ipBlock` does not reliably match pod IPs.
- The CNI must enforce policies: Calico, Cilium and Antrea do; plain flannel does not. kind's default
  CNI (kindnetd, via kube-network-policies) enforces them since kind v0.24; if a probe shows a denied flow still works, the
  CNI is not enforcing: create the kind cluster with `disableDefaultCNI: true` and install Calico.
- L7 rules, FQDN egress and cluster-wide defaults need CNI-specific CRDs (CiliumNetworkPolicy,
  Calico GlobalNetworkPolicy) or the AdminNetworkPolicy API where available.

### Proving a policy (local cluster only)

```bash
C=kind-dev; NS=shop
kubectl --context $C -n $NS run probe-web --image=busybox:1.36 --labels=app.kubernetes.io/name=web --restart=Never -- sleep 3600
kubectl --context $C -n $NS run probe-other --image=busybox:1.36 --restart=Never -- sleep 3600
kubectl --context $C -n $NS wait --for=condition=Ready pod/probe-web pod/probe-other --timeout=60s
kubectl --context $C -n $NS exec probe-web   -- wget -qO- -T 3 http://api:8080/healthz   # expect success
kubectl --context $C -n $NS exec probe-other -- wget -qO- -T 3 http://api:8080/healthz   # expect timeout
kubectl --context $C -n $NS exec probe-other -- nslookup kubernetes.default              # expect success (DNS allowed)
kubectl --context $C -n $NS delete pod probe-web probe-other
```

Record each flow as `from -> to:port expected/observed`. Under restricted PSS these probe pods need the
restricted securityContext (or run them in a test namespace with the same policies).

## 4. Secrets

- Encrypt at rest (`EncryptionConfiguration` or the managed KMS option); RBAC on `secrets` as above.
- Source of truth outside git: External Secrets Operator, Sealed Secrets, SOPS, Secrets Store CSI.
- Mount as files, not env vars (env leaks into crash dumps, `/proc/<pid>/environ`, child processes).
- Never print Secret values while debugging: `kubectl get secret x -o jsonpath='{.data}' | jq 'keys'`
  lists keys only.

## 5. Supply chain at admission

- Pin images by digest in manifests (`image: repo@sha256:...`); tags are mutable.
- Verify signatures and provenance before admission (Kyverno `verifyImages`, Sigstore policy-controller,
  Connaisseur) for registries you own; sign in CI (`cosign sign`), see `container-images` for SBOM and
  attestations.
- Restrict registries with a policy rule; disallow `:latest`.

## 6. Gate

```bash
kube-linter lint rendered.yaml                         # exit 0
kube-score score --output-format ci rendered.yaml      # no CRITICAL
trivy config --severity HIGH,CRITICAL --exit-code 1 rendered.yaml
kubectl --context kind-dev apply --dry-run=server -f rendered.yaml   # PSA warnings appear here
# then the can-i table (section 2) and the probe matrix (section 3) on the local cluster
```

Missing tools: run from images (`stackrox/kube-linter`, `zegl/kube-score`, `aquasec/trivy`) with the
repo mounted read-only. Policy proof without a cluster is static only: say so and cap confidence.

## 7. Review checklist

- [ ] Every app namespace labelled `enforce: restricted` (or a documented exception with baseline).
- [ ] Every container passes the restricted template; writable paths are explicit emptyDirs.
- [ ] One ServiceAccount per workload; token automount off unless needed; no dangerous grants.
- [ ] Default-deny ingress and egress per namespace, DNS allowed, every allowed flow has a reason.
- [ ] can-i table with negative checks and a probe matrix recorded as Evidence (local cluster).
- [ ] No plaintext Secret in git; images by digest.

## 8. Worked example

Request: "harden the `payments` chart". Rendered it, kube-linter flagged `run-as-non-root`,
`no-read-only-root-fs`, `unset-cpu-requirements`; kube-score flagged missing NetworkPolicy. Added the
restricted template (image already ran as UID 10001; `/tmp` and `/var/cache/app` as emptyDirs),
a dedicated ServiceAccount with no RBAC and automount off, default-deny plus DNS plus
`ingress-nginx -> payments:8443` and `payments -> postgres:5432`. On kind with the namespace at
`enforce: restricted`: server dry-run without warnings, pods Ready, `auth can-i get secrets` -> no,
probe matrix 4/4 as expected (unlabelled pod to payments:8443 timed out, DNS resolved).
