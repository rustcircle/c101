---
name: podman-rootless
description: "Podman and Buildah in practice: rootless setup (subuid/subgid, user namespaces, keep-id, cgroup v2), pasta networking, volumes and SELinux labels, pods, podman kube play/generate, Quadlet systemd units (.container, .pod, .kube, .network, .volume, .image, .build) with auto-update and lingering, Buildah scripted builds, podman machine on macOS and Docker CLI/compose compatibility. Load when running, building or deploying containers with Podman or Buildah, or turning containers into systemd services."
when_to_use: "Editing *.container, *.pod, *.kube, *.network, *.volume, *.build Quadlet files or Containerfiles built with podman/buildah; 'permission denied' on a bind mount in rootless Podman; 'potentially insufficient UIDs or GIDs available in user namespace'; port below 1024 refused; container stops when the user logs out; migrating docker-compose or docker run scripts to Podman; podman machine on a Mac."
---

# Podman rootless

Daemonless containers run as the invoking user. Image build craft (layers, base images, BuildKit
features, scanning) is in `container-images`; Kubernetes YAML in `kubernetes-workloads`. Check the
version first: `podman version`, `podman info --format '{{.Host.NetworkBackend}} {{.Host.CgroupsVersion}} {{.Host.Security.Rootless}}'`.
Podman 5 changed defaults (pasta networking, netavark only); Podman 6 removed slirp4netns.

## 1. Rootless prerequisites

| Requirement | Check | Fix (needs root: hand back to the user unless this is a disposable VM) |
|---|---|---|
| subordinate ID ranges | `grep $USER /etc/subuid /etc/subgid` (65536+ each) | `usermod --add-subuids 100000-165535 --add-subgids 100000-165535 $USER`, then `podman system migrate` |
| cgroup v2 with delegation | `podman info` shows `cgroupVersion: v2`; `cat /sys/fs/cgroup/user.slice/user-$(id -u).slice/cgroup.controllers` includes cpu memory pids | systemd `Delegate=` drop-in for `user@.service` |
| `newuidmap`/`newgidmap` | `command -v newuidmap` | install `shadow-utils`/`uidmap` |
| storage driver | `podman info --format '{{.Store.GraphDriverName}}'` = overlay | native rootless overlay (kernel 5.13+) or fuse-overlayfs |
| user session for systemd units | `loginctl show-user $USER -p Linger` | `loginctl enable-linger $USER` |

## 2. User namespaces and file ownership

Rootless root inside the container is your UID on the host; other container UIDs map into your
subuid range. Consequences:

| Symptom | Cause | Fix |
|---|---|---|
| bind-mounted files appear owned by `nobody` or 100999 on the host | container UID 1000 maps to subuid 100999 | `--userns=keep-id` (your UID inside = your UID outside), or `--userns=keep-id:uid=10001,gid=10001` to match the image user |
| `permission denied` writing a bind mount on Fedora/RHEL | SELinux label | `-v ./data:/data:Z` (private) or `:z` (shared); never relabel `/home` or `/` |
| `permission denied` with correct labels | the container user cannot write host-owned dir | `podman unshare chown 10001:10001 ./data` (chown inside your namespace) or `:U` volume option |
| `insufficient UIDs or GIDs available in user namespace` | image has files owned by UIDs beyond your range | widen subuid/subgid ranges, then `podman system migrate` |

Inspect the mapping: `podman unshare cat /proc/self/uid_map`.

## 3. Networking

- Rootless default (Podman 5+): `pasta` (user-mode, keeps host addresses, good performance).
  Containers on a user-defined network (`podman network create app`) resolve each other by name via
  aardvark-dns; the default network does not do DNS.
- Ports below 1024 rootless: map a high port (`-p 8080:80`), or lower
  `net.ipv4.ip_unprivileged_port_start` (root, host-wide decision; hand back as a doubt).
- Reach the host from a container: `host.containers.internal`.
- Inside a pod, containers share one network namespace and talk over `localhost`.

## 4. Pods and Kubernetes YAML

```bash
podman pod create --name shop -p 8080:8080
podman run -d --pod shop --name db -e POSTGRES_PASSWORD_FILE=/run/secrets/pg --secret pg docker.io/library/postgres:17
podman run -d --pod shop --name api localhost/api:dev
podman kube generate shop > shop.yaml        # Pod YAML usable by kubectl (review it: hostPath, secrets)
podman kube play shop.yaml                   # run a Pod/Deployment YAML locally; --down to stop
podman kube play --build shop.yaml           # build images from Containerfiles named after containers
```

`podman kube play` supports a subset of Kubernetes (Pods, Deployments, ConfigMaps, Secrets, PVCs as
volumes); it is a smoke test for container wiring, not a substitute for a kind cluster.
`podman secret create pg ./pg.txt` stores secrets outside images and env.

## 5. Quadlet: containers as systemd services

Quadlet turns unit-like files into systemd services at `daemon-reload`. Locations: rootless
`~/.config/containers/systemd/`, rootful `/etc/containers/systemd/`. File types: `.container`,
`.pod` (Podman 5.0+), `.kube`, `.network`, `.volume`, `.image`, `.build` (5.2+), `.artifact` (recent).

```ini
# ~/.config/containers/systemd/api.container
[Unit]
Description=Shop API
After=network-online.target

[Container]
Image=registry.example.com/shop/api@sha256:0123...
ContainerName=api
Network=shop.network
PublishPort=127.0.0.1:8080:8080
Volume=api-data.volume:/var/lib/api:Z
Secret=api-token,type=mount,target=/run/secrets/token
Environment=LOG_LEVEL=info
User=10001
UserNS=keep-id:uid=10001,gid=10001
ReadOnly=true
NoNewPrivileges=true
DropCapability=ALL
HealthCmd=/app/healthcheck
HealthInterval=30s
HealthOnFailure=kill
AutoUpdate=registry
Notify=healthy

[Service]
Restart=on-failure
TimeoutStartSec=120

[Install]
WantedBy=default.target
```

```ini
# shop.network
[Network]
Subnet=10.89.10.0/24
# api-data.volume
[Volume]
```

Operate:

```bash
/usr/lib/systemd/system-generators/podman-system-generator --user --dryrun   # validate: prints units or errors
systemctl --user daemon-reload
systemctl --user start api.service            # name = file stem + .service; .network -> shop-network.service
systemctl --user status api.service; journalctl --user -u api.service -n 100
loginctl enable-linger $USER                  # keep user services running after logout and at boot
podman auto-update --dry-run                  # what AutoUpdate=registry would pull and restart
```

- `[Install]` in Quadlet files is honoured by the generator; `systemctl enable` on generated units is
  not used.
- `.kube` units run `podman kube play` on a YAML file: a bridge from Kubernetes manifests.
- Podman 5.6+ has `podman quadlet install|list|print|rm` to manage these files.
- `AutoUpdate=registry` needs a fully qualified image reference (tag, not digest); `local` checks local
  images. Rollback on failed health is built in when `Notify=healthy`.

## 6. Buildah and building with Podman

`podman build` uses Buildah internally and reads `Containerfile` or `Dockerfile`. It accepts most
BuildKit syntax: `RUN --mount=type=cache|secret|bind`, multi-stage, `--platform`. Differences:

| Docker/BuildKit | Podman/Buildah |
|---|---|
| `docker buildx build --platform linux/amd64,linux/arm64 -t x --push` | `podman build --platform linux/amd64,linux/arm64 --manifest x .` then `podman manifest push x docker://...` (push needs user confirmation) |
| `--cache-from type=registry` | `--layers --cache-from <repo> --cache-to <repo>` |
| `docker build --secret id=x,src=f` | same flags |
| BuildKit-only frontends (`# syntax=` custom frontends, heredoc edge cases) | check support; fall back to plain RUN |

Scripted builds without a Containerfile (Buildah):

```bash
ctr=$(buildah from --pull registry.access.redhat.com/ubi9/ubi-micro)
buildah copy "$ctr" ./dist/app /app/app
buildah config --user 10001 --entrypoint '["/app/app"]' --port 8080 "$ctr"
buildah commit --rm "$ctr" localhost/app:dev
```

`buildah unshare` enters the rootless namespace for `buildah mount` workflows. Builds run without a
daemon, which makes them suitable for CI runners without Docker socket access.

## 7. macOS and Windows: podman machine

```bash
podman machine init --cpus 4 --memory 8192 --disk-size 60 && podman machine start
podman machine ssh                         # the Linux VM where containers actually run
podman machine set --rootful               # only when a workload needs rootful (privileged ports in VM, some kind setups)
```

Bind mounts cross the VM boundary (slower; volume UIDs as in section 2). `podman machine` can
expose a Docker-compatible socket (shown by `podman machine start`), so `docker` CLI and
Testcontainers work via `DOCKER_HOST`.

## 8. Docker compatibility

- `alias docker=podman` covers most CLI use; differences: no daemon (`--restart` policies need
  systemd/Quadlet to survive reboots), short image names need `unqualified-search-registries` or
  fully qualified names (always use `docker.io/library/...`).
- Compose: `podman compose` delegates to `docker-compose` or `podman-compose`; the Docker API socket
  (`systemctl --user enable --now podman.socket`, `DOCKER_HOST=unix://$XDG_RUNTIME_DIR/podman/podman.sock`)
  lets the real `docker compose` work. Prefer Quadlet for long-running services.
- kind on Podman: `KIND_EXPERIMENTAL_PROVIDER=podman`.

## 9. Gate

```bash
podman build -t localhost/app:dev . && podman run --rm --read-only --userns=keep-id localhost/app:dev --version
podman image inspect localhost/app:dev --format '{{.Config.User}} {{.Architecture}}'
/usr/lib/systemd/system-generators/podman-system-generator --user --dryrun 2>&1 | tail -20   # Quadlet syntax
systemctl --user start app.service && systemctl --user is-active app.service                # active
curl -fsS http://127.0.0.1:8080/readyz
trivy image localhost/app:dev    # or grype; podman save -o app.tar for offline scanners
```

## 10. Pitfalls

- `podman generate systemd` is deprecated: write Quadlet files instead.
- Containers die at logout: lingering off.
- Health checks do nothing without systemd timers (rootless needs a user session) or Quadlet.
- `--privileged` rootless is still confined to your user's privileges; do not use it to "fix" a
  permission error you have not explained.
- Rootful and rootless Podman have separate image stores: an image built with `sudo podman` is not
  visible to `podman`.
