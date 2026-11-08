---
name: coding-general
description: "Coding hub: orientation in an unfamiliar repository, a language-agnostic definition of done, and a routing table to the granular coding playbooks (git, refactoring, codemods, API contracts, SQL tuning, migrations, regex, resilience, dependency upgrades, docs/ADRs, Python, TypeScript, CI, containers, shell, observability). Load first for general software-engineering work in any language."
when_to_use: "Any coding task that is not specific to one language hub: refactors, migrations, API or schema changes, CI or container work, Python or TypeScript projects, git history surgery, performance of SQL, flaky or slow pipelines."
---

# Coding hub

Start here for software-engineering work that is not owned by a language hub (`rust-craft`,
`cpp-craft`, `go-craft`, `haskell-craft`, `julia-craft`, `java-craft`, `kotlin-craft`). Load the
granular skill that matches the task with the Skill tool by name; they are listed by name only
(to keep every session's context lean), so the tables below are their descriptions. A skill whose
pack is not enabled in this install is off: work from this hub and say so.

## 1. Orient in an unfamiliar repository (five minutes)

```bash
git log --oneline -15; git status --short | head                       # recent intent, dirty state
ls; cat README* CONTRIBUTING* 2>/dev/null | head -60                    # declared workflow
ls -a | grep -E '^(\.github|\.gitlab-ci.yml|Makefile|justfile|Taskfile|pyproject.toml|package.json|Cargo.toml|go.mod|pom.xml|build.gradle.*|CMakeLists.txt)$'
cat .github/workflows/*.yml 2>/dev/null | grep -E 'run:' | head -30    # the commands CI really runs
ls *.lock uv.lock package-lock.json pnpm-lock.yaml yarn.lock Cargo.lock go.sum 2>/dev/null
cat CLAUDE.md AGENTS.md .editorconfig 2>/dev/null | head -40            # house rules
```

Record: languages and versions, package manager, the exact build / test / lint commands CI runs,
formatter, and any rules in CLAUDE.md. Reuse those commands; never introduce a second toolchain.

## 2. Definition of done (any language)

| Gate | Evidence |
|---|---|
| Builds | the CI build command passes locally |
| Tests | existing suite green; new behaviour has a test that failed before the change |
| Lint / format / types | the repo's own linters and type checker are clean on touched files |
| Scope | the diff contains only the requested change (no drive-by refactors or reformatting) |
| Compatibility | public APIs, schemas, CLI flags and config keys unchanged unless the task says so; migrations are reversible or expand-contract |
| Docs | README / CHANGELOG / ADR updated when behaviour or a decision changed |

Delegate the checks: `tester` for missing tests, `code-quality-analyst` for metrics, `reviewer` or
`/review-verify` for the diff, `security-auditor` for anything touching auth, input parsing or secrets.

## 3. Routing

### Language-agnostic (pack `coding-core`)

| skill | load when |
|---|---|
| `git-advanced-workflows` | rebasing, untangling history, resolving conflicts, running parallel worktrees or recovering lost work |
| `refactoring-playbook` | restructuring code without changing behaviour or executing items from a code-quality refactor list |
| `codemod-automation` | the same change must be applied at dozens to thousands of sites |
| `api-contract-design` | adding or changing an endpoint, RPC, event schema or SDK |
| `sql-query-tuning` | a query or endpoint is slow, a new query needs an index, or reviewing SQL performance |
| `zero-downtime-migrations` | writing, reviewing or sequencing a database migration |
| `regex-engineering` | writing, debugging or reviewing a regex or an rg/sed/perl rewrite |
| `resilience-patterns` | code calls networks, queues, databases or third-party APIs, or fans out work |
| `dependency-upgrades` | bumping dependencies, runtimes or toolchains, or configuring update bots |
| `docs-and-adr-writing` | writing or reviewing READMEs, API docs, docstrings, ADRs, changelogs or migration guides |

### Python 3.13 + uv (pack `python`)

| skill | load when |
|---|---|
| `python-uv-packaging` | creating, configuring, packaging or fixing a Python project's dependencies |
| `python-typing` | adding or fixing type hints or configuring a checker |
| `python-asyncio` | writing, reviewing or debugging async Python |
| `pytest-patterns` | writing, organising, speeding up or debugging a Python test suite |
| `fastapi-pydantic-services` | building, reviewing or debugging a FastAPI service |
| `python-performance-profiling` | Python code is slow or memory-hungry |

### TypeScript / Node (pack `typescript`)

| skill | load when |
|---|---|
| `typescript-strict-types` | writing, reviewing or fixing TypeScript types |
| `typescript-build-config` | creating or fixing tsconfig, module resolution, package publishing or TS builds |
| `typescript-testing-vitest` | writing, fixing or speeding up TS/JS unit and component tests |
| `node-runtime-patterns` | building, reviewing or debugging Node/Bun runtime code |
| `react-typescript-components` | writing, reviewing or debugging React components or hooks |

### Delivery and operations (pack `devops`)

| skill | load when |
|---|---|
| `ci-pipelines` | creating, speeding up, hardening or debugging a CI workflow |
| `container-images` | writing, reviewing, shrinking or debugging a Dockerfile or compose setup |
| `shell-scripting` | writing, reviewing or debugging a shell script, Makefile/justfile recipe or CI run step |
| `observability-instrumentation` | adding logging, tracing, metrics or alerts, or when debugging needs better telemetry |

### Containers and Kubernetes (pack `containers`, hub `container-craft`, agent `container-expert`)

| skill | load when |
|---|---|
| `container-craft` | any container or Kubernetes task: safety model for clusters and registries, the verification ladder, routing |
| `kubernetes-workloads` | writing or reviewing Kubernetes manifests, probes, resources, Helm charts or Kustomize overlays |
| `kubernetes-security-policy` | RBAC, NetworkPolicy, Pod Security Standards, securityContext hardening |
| `kubernetes-troubleshooting` | CrashLoopBackOff, OOMKilled, ImagePullBackOff, Pending pods, stuck rollouts, `kubectl debug` |
| `podman-rootless` | rootless Podman, pods, Quadlet systemd units, Buildah, podman machine |

Core skills that complement these: `testing-strategy`, `code-review-checklist`, `debugging-method`,
`performance-optimization`, `security-review`, `code-quality-metrics`.

## 4. Cross-cutting rules

- Behaviour-preserving work (refactors, codemods, dependency upgrades) starts with a safety net:
  characterization tests or a recorded baseline, then small reversible steps.
- Changes to anything another system consumes (API, schema, event, CLI, config) go through
  expand → migrate → contract; never rename and remove in one release.
- Measure before optimising (profiles, EXPLAIN plans, flame graphs); keep the before/after numbers
  in the PR.
- Automate repetition: more than ~30 similar edits is a codemod, not hand work.
- Pin and lock: lockfiles committed, toolchains pinned, CI uses the same commands as local.
