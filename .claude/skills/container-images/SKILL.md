---
name: container-images
description: "Small, fast-building, secure container images: multi-stage Dockerfiles per stack (Python/uv, Node/pnpm, static Go, Rust/cargo-chef, JVM layered jars), BuildKit cache/secret mounts, layer order, base image choice (distroless, Chainguard/Wolfi, slim, Alpine/musl), non-root and PID 1 signals, multi-arch buildx, SBOM/provenance, scanning, size analysis, local compose. Load when writing, reviewing, shrinking or debugging a Dockerfile or compose setup."
when_to_use: "Editing a Dockerfile, Containerfile, .dockerignore, compose.yaml or docker-bake.hcl; an image is over a few hundred MB or rebuilds everything on each code change; exit code 137/143; container ignores SIGTERM; exec format error on arm64/amd64; trivy, grype or hadolint findings; building multi-arch images or adding SBOM, provenance or signing."
---

# Container images

Build-side engineering for OCI images. The security checklist for containers (privileges, secrets,
runtime hardening review) stays in `security-review`; this skill is how to build images that pass it.
Image tags below were current in October 2026; pin by digest in real files (section 4).

Deep material:
[Dockerfile templates for Node, Go, Rust, JVM](references/dockerfile-templates.md) |
[multi-arch CI build, scanning, signing, compose](references/build-release-compose.md)

## 1. Layer ordering, context, cache and secret mounts

Order layers from least to most frequently changed. Every instruction after the first changed input is
rebuilt.

```
FROM base@digest              # changes monthly (Renovate)
system packages               # changes rarely
COPY lockfiles only           # changes when deps change
install dependencies          # cached unless lockfiles changed
COPY source                   # changes every commit
build / install project       # cheap, last
```

`.dockerignore` (start from deny-by-default for large repos):
```
.git
**/.venv
**/node_modules
**/__pycache__
**/target
dist/
build/
.env*
*.pem
*.key
compose*.yaml
Dockerfile*
```

BuildKit mounts (`# syntax=docker/dockerfile:1` on line 1):

| Mount | Example | Effect |
|---|---|---|
| cache | `RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked` | package cache survives across builds, never lands in a layer |
| cache (pnpm) | `--mount=type=cache,id=pnpm,target=/var/cache/pnpm` + `--store-dir /var/cache/pnpm` | shared store |
| cache (Go) | `--mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build` | module + build cache |
| cache (Cargo) | `--mount=type=cache,target=/usr/local/cargo/registry` | crate downloads |
| bind | `--mount=type=bind,source=uv.lock,target=uv.lock` | use a file without a COPY layer |
| secret | `RUN --mount=type=secret,id=npmrc,target=/root/.npmrc pnpm install` with `docker buildx build --secret id=npmrc,src=$HOME/.npmrc .` | credential available to one RUN, absent from layers and history |
| ssh | `RUN --mount=type=ssh git clone git@github.com:org/private.git` with `--ssh default` | agent forwarding for private repos |

Never pass secrets via `ARG` or `ENV`: both are recorded in image metadata (`docker history`,
`docker inspect`), and `docker build --check .` flags `SecretsUsedInArgOrEnv`.
Cache mounts are local to the builder; in CI pair them with an exported layer cache
(`cache-to: type=gha,mode=max` or `type=registry`), see `ci-pipelines`.

## 2. Python + uv template

```dockerfile
# syntax=docker/dockerfile:1
ARG PYTHON_IMAGE=python:3.13-slim-trixie

FROM ${PYTHON_IMAGE} AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# 1) dependencies only: cached until uv.lock or pyproject.toml change
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
# 2) the project itself
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
ENTRYPOINT ["uvicorn", "checkout_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Why each line:
- `UV_COMPILE_BYTECODE=1`: `.pyc` compiled at build time, faster cold start, no writes at runtime.
- `UV_LINK_MODE=copy`: the cache mount is a different filesystem; hardlinks would fail with warnings.
- `UV_PYTHON_DOWNLOADS=0`: use the image's interpreter. The venv's `bin/python` is a symlink to the
  builder's interpreter path (`/usr/local/bin/python3.13` here), so the runtime image must have the same
  Python minor version at the same path. Same base image in both stages guarantees it.
- `--no-install-project` then full sync: dependency layer survives source edits.
- `--no-editable`: the project is installed into site-packages as a wheel (needs a `[build-system]`),
  so only `.venv` is copied; no source tree in the runtime image.
- Workspaces: the first sync needs every member's `pyproject.toml`; bind them too, or use `--frozen`
  for that step (lock not re-validated) and keep `--locked` on the final sync.
- Files stay root-owned and the process runs as 10001, so the app cannot rewrite its own code.

Distroless Python: `gcr.io/distroless/python3-debian13` ships Debian's interpreter at `/usr/bin`, which
does not match `python:*` images. Either build in a Debian 13 builder with `apt-get install python3
python3-venv` (same path, same version), or install a uv-managed Python into a fixed directory
(`UV_PYTHON_INSTALL_DIR=/python`, `uv python install 3.13`) and copy `/python` plus `.venv` into
`gcr.io/distroless/cc-debian13`.

## 3. Other stacks (full Dockerfiles in [templates](references/dockerfile-templates.md))

| Stack | Builder essentials | Runtime | Signals |
|---|---|---|---|
| Node + pnpm | `COPY pnpm-lock.yaml pnpm-workspace.yaml` -> `pnpm fetch` -> `COPY . .` -> `pnpm install --offline --frozen-lockfile` -> build -> `pnpm --filter=api --prod deploy /prod/api` | `gcr.io/distroless/nodejs24-debian13:nonroot`, `CMD ["dist/server.js"]` | run `node` directly, not `npm start`/`pnpm start` (an extra process, often a shell, sits between PID 1 and the app; forwarding varies by version); app handles SIGTERM |
| Go | `CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /out/app ./cmd/app` with module and build cache mounts; `FROM --platform=$BUILDPLATFORM` + `GOOS=$TARGETOS GOARCH=$TARGETARCH` cross-compiles without emulation | `gcr.io/distroless/static-debian13:nonroot` or `scratch` + CA certs + `-tags timetzdata` | `signal.NotifyContext(ctx, syscall.SIGTERM, os.Interrupt)` |
| Rust | cargo-chef: planner (`cargo chef prepare --recipe-path recipe.json`), cook (`cargo chef cook --release --recipe-path recipe.json`), then `cargo build --release --locked` | `gcr.io/distroless/cc-debian13:nonroot` (glibc) or `static` with a musl target | `tokio::signal` handler |
| JVM (Spring Boot) | `java -Djarmode=tools -jar application.jar extract --layers --destination extracted`, one `COPY` per layer (dependencies, spring-boot-loader, snapshot-dependencies, application) | `eclipse-temurin:25-jre` or a `jlink` runtime on a slim base | JVM handles SIGTERM; Spring `server.shutdown=graceful` |

pnpm notes: older pnpm majors refused `deploy` for non-injected workspace packages unless
`inject-workspace-packages=true` or `--legacy`; current pnpm (12.x) deploys without it. Corepack is not
bundled with Node 25+, so install a pinned pnpm (`npm install -g pnpm@12.14.0`) or use the
`ghcr.io/pnpm/pnpm` image.

## 4. Base image choice

| Base | Shell / pkg manager | libc | Size class | Use when | Watch out |
|---|---|---|---|---|---|
| `gcr.io/distroless/static-debian13` | none | none | ~2 MB | static Go/Rust binaries | no shell; use `:debug` (busybox) to troubleshoot |
| `gcr.io/distroless/cc-debian13`, `base-debian13` | none | glibc | ~20-30 MB | Rust/C++ dynamic, uv-managed Python | match builder glibc (build on same or older Debian) |
| `gcr.io/distroless/{python3,nodejs24,java25}-debian13` | none | glibc | language runtime | interpreted apps | interpreter path/version fixed by Debian |
| Chainguard / Wolfi (`cgr.dev/chainguard/*`) | none in runtime, `-dev` variants have apk | glibc | minimal | lowest CVE counts, daily rebuilds | free tier has limited tags; check your entitlement before pinning versions |
| Debian slim (`python:3.13-slim-trixie`, `node:24-slim`) | sh, apt | glibc | 75-250 MB | maximum compatibility, debuggable | remove apt lists; more packages = more CVEs |
| Alpine | sh, apk | musl | 5-60 MB | tiny shells, static tools | musl DNS resolver differences (no `search`/`ndots` parity, TCP fallback history), slower malloc for allocation-heavy code, Python needs musllinux wheels or compiles from source |

Pin by digest and let Renovate (docker datasource, `pinDigests: true`) bump it:
```dockerfile
FROM python:3.13-slim-trixie@sha256:<digest>   # tag kept for humans, digest for reproducibility
```
Get the index digest from the `Digest:` line of `docker buildx imagetools inspect python:3.13-slim-trixie`.
Distroless tags: `latest`, `nonroot` (uid 65532), `debug`, `debug-nonroot`; other tags are deprecated.

## 5. Runtime correctness

| Concern | Rule | Check |
|---|---|---|
| ENTRYPOINT/CMD form | exec form `["bin", "arg"]`; shell form wraps the command in `/bin/sh -c`, and unless the shell execs it, the shell is PID 1 and does not forward signals | `docker build --check .` (JSONArgsRecommended) |
| PID 1 | Linux gives PID 1 no default signal handlers: an app without a SIGTERM handler ignores `docker stop` and is SIGKILLed after 10 s (exit 137). Handle SIGTERM in the app, or run with `docker run --init` / tini to forward signals and reap zombies | `time docker stop <ctr>` < 2 s, exit 0 |
| Wrapper scripts | end with `exec "$@"` or `exec app` so the app replaces the shell | `docker exec <ctr> cat /proc/1/cmdline` |
| User | numeric `USER 10001:10001` (Kubernetes `runAsNonRoot` can verify numeric UIDs only) | `docker run --rm img id` |
| Filesystem | run with read-only root; writable paths explicit (`--tmpfs /tmp`, K8s `emptyDir`) | `docker run --read-only --tmpfs /tmp img` works |
| Health | `HEALTHCHECK` for compose/Docker; Kubernetes ignores it, use liveness/readiness/startup probes | `docker inspect -f '{{.State.Health.Status}}'` |
| Stop signal | `STOPSIGNAL SIGQUIT` for nginx graceful stop, `SIGINT` for some CLIs; default SIGTERM | |
| TLS and time | CA bundle at `/etc/ssl/certs/ca-certificates.crt`, tzdata or embedded zoneinfo | HTTPS call and `TZ=Europe/Berlin` in a smoke test |
| Capabilities | none needed for ports > 1024; run with `--cap-drop ALL` | |

## 6. Size and inspection

```bash
docker image ls ghcr.io/acme/api                                   # size per tag
docker history --no-trunc --format '{{.Size}}\t{{.CreatedBy}}' ghcr.io/acme/api:dev | sort -h | tail
dive ghcr.io/acme/api:dev                                          # per-layer files, wasted bytes
CI=true dive ghcr.io/acme/api:dev                                  # gate with .dive-ci rules
docker buildx imagetools inspect ghcr.io/acme/api:1.4.0            # platforms, digests, attestations
```
`.dive-ci` example: `lowestEfficiency: 0.95`, `highestWastedBytes: 20MB`, `highestUserWastedPercent: 0.10`.

Shrinking, in payoff order: multi-stage (toolchains stay in the builder), smaller base, no dev
dependencies, no package-manager caches in layers (cache mounts, or `rm -rf /var/lib/apt/lists/*` in
the same `RUN` as `apt-get install --no-install-recommends`), strip binaries, drop docs/tests from
site-packages only if measured. Report sizes as a before/after table (section 12).

## 7. Multi-arch

```bash
docker buildx create --name multi --use
docker buildx build --platform linux/amd64,linux/arm64 -t ghcr.io/acme/api:1.4.0 --push .   # CI only
docker buildx build --platform linux/amd64,linux/arm64 --output type=oci,dest=api-oci.tar .   # local check, no push
```
- Pushing and signing (`--push`, `imagetools create`, `cosign sign`) write to shared registries and
  public transparency logs: run them in CI (`ci-pipelines`); locally use `--load` (one platform) or an
  OCI tar, and leave pushes to the user.
- QEMU emulation is commonly 5-20x slower for compile-heavy steps. Prefer native runners
  (`ubuntu-24.04` and `ubuntu-24.04-arm` on GitHub, available for public and private repos), push
  each platform by digest, then merge: `docker buildx imagetools create -t ghcr.io/acme/api:1.4.0
  ghcr.io/acme/api@sha256:<amd64> ghcr.io/acme/api@sha256:<arm64>` (workflow in the reference).
- For compiled languages cross-compile instead: `FROM --platform=$BUILDPLATFORM golang:1.27 AS build`
  with `ARG TARGETOS TARGETARCH`; Rust via `cargo zigbuild` or cross toolchains.
- Apple Silicon laptops build `linux/arm64` by default; production on amd64 needs `--platform
  linux/amd64` or, better, CI-built images. "exec format error" = binary for the wrong architecture.
- Arch-specific artifacts: install wheels/npm native modules inside the target-platform stage; never
  download a fixed `x86_64` binary without branching on `TARGETARCH`.

## 8. Supply chain

| Step | Command | Gate |
|---|---|---|
| Lint Dockerfile | `hadolint Dockerfile` (or `docker run --rm -i hadolint/hadolint < Dockerfile`); `docker build --check .` | errors fail |
| Attestations | `docker buildx build --provenance=mode=max --sbom=true --push ...` | attached to the image index |
| SBOM file | `syft ghcr.io/acme/api@sha256:<d> -o spdx-json=sbom.spdx.json` | stored with the release |
| Scan | `trivy image --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 <img>`; `grype <img> --fail-on critical`; `docker scout cves --exit-code --only-severity critical,high <img>` | critical = block; high = block if fixable |
| Sign | `cosign sign --yes ghcr.io/acme/api@sha256:<d>` (keyless, OIDC identity of the CI job) | |
| Verify | `cosign verify --certificate-identity-regexp '^https://github.com/acme/api/' --certificate-oidc-issuer https://token.actions.githubusercontent.com ghcr.io/acme/api@sha256:<d>` | admission policy |

Always sign and scan by digest, never by tag. Rescan released images daily; new CVEs appear without
code changes. Triage details and false-positive handling: `security-review` supply-chain section.

## 9. Local dev with compose

```yaml
services:
  api:
    build: { context: ./apps/api, target: dev }
    command: ["uvicorn", "checkout_api.main:app", "--host", "0.0.0.0", "--reload"]
    env_file: [.env]                    # local only; .env is in .dockerignore
    ports: ["8000:8000"]
    depends_on:
      db: { condition: service_healthy }
    develop:
      watch:
        - { action: sync, path: ./apps/api/src, target: /app/src }
        - { action: rebuild, path: ./apps/api/uv.lock }
  db:
    image: postgres:18
    environment: { POSTGRES_PASSWORD: local-dev-only }
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 2s
      retries: 15
    volumes: ["pgdata:/var/lib/postgresql"]   # postgres 18+ moved the volume from .../data
  jaeger:
    image: jaegertracing/jaeger:2.22.0
    profiles: [tracing]                 # started only with --profile tracing
volumes:
  pgdata:
```
The `dev` target is one extra stage between `builder` and `runtime` (the last stage stays the default
target), so `--reload` sees synced source through an editable install:
```dockerfile
FROM builder AS dev
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked   # editable project + dev group
ENV PATH="/app/.venv/bin:$PATH"
```
Run `docker compose up --watch` (or `docker compose watch` to keep logs separate). `sync` copies edited
files into the container; `rebuild` rebuilds the image when the lockfile changes.

## 10. Debugging

| Symptom | Diagnose | Fix |
|---|---|---|
| Every build reinstalls deps | `docker buildx build --progress=plain .` twice; first step not marked `CACHED` is the buster | move lockfile COPY above source COPY; tighten `.dockerignore` |
| Need to rebuild one stage | `--no-cache-filter runtime` | |
| Need a shell in the image | `docker run --rm -it --entrypoint sh <img>`; distroless: `:debug` tag with `--entrypoint /busybox/sh`; Kubernetes: `kubectl debug -it <pod> --image=busybox --target=<container>` | |
| Exit 137 | `docker inspect -f '{{.State.OOMKilled}}' <ctr>`: true = memory limit; false = SIGKILL after stop timeout | raise limit or fix leak; handle SIGTERM |
| Exit 143 | process terminated by SIGTERM without graceful handling | add handler, drain, exit 0 |
| `exec format error` | wrong architecture or missing shebang interpreter | section 7 |
| `no such file or directory` for an existing binary | dynamic binary on `static`/`scratch` (missing loader/glibc) or CRLF shebang | `CGO_ENABLED=0`, use `cc` base, `file <binary>` |
| Permission denied writing | read-only root or non-root user | explicit writable volume/tmpfs |

## 11. Pitfalls

| Pitfall | Consequence | Fix |
|---|---|---|
| `COPY . .` before dependency install | full reinstall on every commit | lockfiles first (section 1) |
| `RUN apt-get update` and `RUN apt-get install` in separate layers | stale cached index, install of removed versions | one `RUN apt-get update && apt-get install -y --no-install-recommends ... && rm -rf /var/lib/apt/lists/*` |
| `FROM x:latest` | unreproducible builds, surprise major upgrades | tag + digest |
| No `USER` | root in container; any escape is root on the node | numeric non-root user |
| Shell-form `CMD npm start` | wrappers between PID 1 and the app; SIGTERM may never arrive; 10 s stop then kill | exec form, run the runtime directly |
| Secrets via `ARG`/`ENV`/`COPY` then `rm` | visible in `docker history` or earlier layers | `--mount=type=secret` |
| Host `.venv` or `node_modules` copied in | macOS binaries in a Linux image, wrong arch | `.dockerignore` them; install inside the build |
| `pip install` without lockfile in Dockerfile | dependency drift between builds | `uv sync --locked`, `pnpm install --frozen-lockfile` |
| Distroless runtime with mismatched Python path | `.venv/bin/python: not found` | same interpreter path in both stages |

## 12. Worked example: FastAPI image 1.24 GB to 138 MB

Before (`apps/api/Dockerfile`):
```dockerfile
FROM python:3.13
WORKDIR /app
COPY . .
RUN pip install uv && uv sync
CMD uv run uvicorn checkout_api.main:app --host 0.0.0.0
```
Problems: full Debian with compilers, `.git` and `.venv` from the host in the context, dev deps
installed, any edit invalidates the install layer, root user, shell-form CMD through `uv run` (two
wrappers between PID 1 and uvicorn; here `docker stop` took 10 s and exited 137).

After: the section 2 template and the section 1 `.dockerignore`, build context `apps/api` (its own
`pyproject.toml`, `uv.lock`, `src/checkout_api/`). Steps run:
```bash
hadolint apps/api/Dockerfile && docker build --check apps/api
docker buildx build -t api:dev --load apps/api                                 # cold
echo '# touch' >> apps/api/src/checkout_api/main.py
time docker buildx build -t api:dev --load apps/api                            # code-only change
docker run -d --name api --read-only --tmpfs /tmp --cap-drop ALL -p 8000:8000 api:dev
sleep 12; docker inspect -f '{{.State.Health.Status}}' api                   # healthy
time docker stop api; docker inspect -f '{{.State.ExitCode}}' api           # 0.6 s, 0
trivy image --severity CRITICAL --exit-code 1 api:dev                         # 0 critical
docker buildx build --platform linux/amd64,linux/arm64 \
  --provenance=mode=max --sbom=true -t ghcr.io/acme/checkout-api:1.4.0 --push apps/api
docker buildx imagetools inspect ghcr.io/acme/checkout-api:1.4.0             # 2 platforms + attestations
```

| Metric | Before | After |
|---|---|---|
| Image size (`docker image ls`) | 1.24 GB | 138 MB |
| Build after a code-only change | 6m02s (all deps reinstalled, two sdists compiled) | 40 s (deps layer `CACHED`) |
| Context sent | 410 MB (`.git`, `.venv`) | 2.1 MB |
| User | root | 10001 |
| `docker stop` | 10 s, exit 137 | 0.6 s, exit 0 |
| Trivy critical / high | 3 / 41 | 0 / 2 (no fix available, documented) |
| Platforms | amd64 | amd64 + arm64 (native runners in CI) |

Related: `ci-pipelines`, `shell-scripting`, `observability-instrumentation`, `python-uv-packaging`,
`fastapi-pydantic-services`, `node-runtime-patterns`, `go-modules-tooling`, `cargo-workspaces-features`,
`security-review`, hub `coding-general`.
