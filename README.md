<p align="center">
  <img src="blackcat.jpg" alt="A black cat grooming itself in the middle of an isometric city of small robots stacking blocks, wiring pipelines and checking off tasks" width="720">
</p>

<h1 align="center">c101</h1>

<p align="center">
  <b>A self-tuning, multi-agent stack for Claude Code and the Claude Agent SDK.</b><br>
  One delegator, orchestrators, swarms, meshes, expert ensembles and voting mediators — nested up to eight levels deep,
  bounded by token budgets, and learning from every session.
</p>

<p align="center">
  <img alt="Claude Code" src="https://img.shields.io/badge/Claude%20Code-2.1.30x-8A63D2">
  <img alt="Agent SDK" src="https://img.shields.io/badge/Claude%20Agent%20SDK-Python-8A63D2">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.13%20(uv)-3776AB">
  <img alt="Models" src="https://img.shields.io/badge/models-Opus%205.5%20%C2%B7%20Sonnet%205.5%20%C2%B7%20Haiku%205.5-1F9AA5">
</p>

---

## What it is

c101 is a complete Claude Code configuration (agents, skills, saved workflows, hooks, MCP servers and Python
tooling) that turns a single session into a coordinated team:

- **Orchestration.** A main-thread `delegator` routes every request to the cheapest adequate route: a single expert,
  an `orchestrator` running a plan DAG, a swarm over shards, a subagent mesh on a shared blackboard, an ensemble of
  experts, or a `mediator` where several agents solve the same problem independently and **vote** (Schulze, Borda,
  approval, plurality, logarithmic opinion pool).
- **63 agents in nine groups** (orchestration, planning, quality, research, experts, synthesis, image, writing, meta), each
  with a model tier, an effort level, a step budget, only the MCP servers it calls (connected only while it runs), and at most three role skills on
  top of the three protocol skills every agent preloads.
- **Depth 8, bounded.** Native nested subagents are raised from 3 to 8 levels. The `pre-agent` hook gives every child
  a `<stack-context>` header (depth, parent, remaining depth, spawn count, token budget, output directory) and
  enforces per-caller spawn rules, a 128-spawn session budget and whole-tree token budgets (session 2.5B guaranteed,
  7.5B soft, 10B hard; per prompt 100M, 300M, 400M).
- **Three model tiers.** `claude-opus-5-5`, `claude-sonnet-5-5` and `claude-haiku-5-5` are the only models allowed
  anywhere, enforced at seven layers; a caller that wants cheaper or stronger work picks a different agent, never a
  per-call model or effort.
- **Planning and quality.** Planners, an architect, a plan critic, reviewers with adversarial verification,
  validators, testers, quality control, code-quality analysis, optimisation, security and debugging; nothing reaches
  the user without a gate.
- **Research.** Quick and deep researchers, web search (Exa, Jina), scraping and crawling (Spider), real browsing
  (Playwright), computer use (the user's own macOS apps interactively, or a disposable, network-less desktop
  container that also runs under the Agent SDK), papers (arXiv/SSRN), fact checking, and summarizers, including a `file-summarizer`
  that keeps full output on disk and returns a compact digest.
- **Experts and synthesis.** Computer graphics, computer science, quantum computing, Rust, C++, Go, Haskell, Julia,
  Java, Kotlin, Python, TypeScript, mathematics, physics and graphic design, each backed by a hub skill and granular skills, plus
  synthesis agents that combine experts into higher-level answers (Delphi panels, debate, analogy, first principles).
- **Saved workflows.** Nine deterministic JavaScript workflows (`/swarm-run`, `/fanout`, `/mediate`,
  `/expert-panel`, `/research-sweep`, `/review-verify`, `/plan-tournament`, `/visual-iterate`, `/manuscript-review`): agents produce the
  content, and the script computes every decision (tallies, quantiles, stop rules, dedup, coverage ledgers).
- **Context first.** Output past ~60 lines goes to `.stack/out/<agent>/` and only a summary and a path travel up;
  every reply follows a five-section output contract; uncertain facts are verified or escalated as Open doubts, never
  guessed. The stack optimises for context usage, not speed.
- **Fiction writing and message checks.** A writing pack for markdown novels (`chapters/000_prologue.md`,
  `001_chapter-1.md`, ...): a project builder, a fiction writer, a developmental manuscript reviewer, a US English
  copy-editor and a prose stylist (show-not-tell, purple or generic prose, filter words, simplification), backed by
  local analysis scripts and the `/manuscript-review` workflow; plus `chat-aide` and `/polish` for checking a chat,
  email or DM before you send it. Analysis reports first and edits only on request; text never leaves the machine.
- **Images and vectors.** One MCP server with a tool per operation (generation, references, edits, transparency,
  segmentation, background removal, upscaling, SVG generation, tracing), each pointed at your own endpoint and model
  with no fallbacks, layered SVG and layered PDF output, and a `visual-reviewer` that scores every result against the
  brief until it passes.
- **Bayesian self-tuning.** After each session the learner updates per-agent posteriors (censored log-normal tool
  rounds, Dirichlet effort bands, Beta failure rate, token windows) and moves `maxTurns`, effort and context windows
  within bounds when a session ends (never mid-session; read by the next session), as audited edits to the agent files; `bin/stack learn
  history` shows the per-agent trends.
- **Two runtimes, one definition.** Everything runs interactively (`bin/claude-stack`) and programmatically through
  the Claude Agent SDK (`bin/stack-sdk`); secrets live only in `~/.claude/stack.env`.

## Quick start

```bash
git clone <this repo> c101 && cd c101
./install.sh                    # uv installs Python 3.13 + deps, makes it Claude's default; creates ~/.claude/stack.env (mode 600)
$EDITOR ~/.claude/stack.env     # add your keys and image endpoints (see below)
bin/stack keys                  # which keys are set (names only)
bin/stack doctor                # validates agents, skills, workflows, MCP, hooks, tiers, packs
bin/claude-stack                # Claude Code with the delegator as the main thread
```

Inside Claude Code, accept the folder trust dialog once: each agent defines its MCP servers inline, and Claude Code
connects them only in a trusted folder, only while that agent runs. Run `/mcp` once to enable computer use on the
host desktop; for sandboxed computer use install Docker or podman and run `bin/desktop-sandbox --build --profile recommended` once.

Use the stack in every project, with only the packs you want:

```bash
./install.sh --user --packs rust,quantum,graphic-design   # core is always included
./install.sh --enforce-models                               # restrict every project to the tier models (alone or with --user)
./install.sh --main-agent                                   # make the delegator the default main thread
./install.sh --adobe                                        # InDesign, Illustrator, Photoshop, After Effects, Premiere Pro MCP servers
```

Requirements: macOS or Linux, [uv](https://docs.astral.sh/uv/), Node 18+ (for the Playwright MCP server),
Claude Code 2.1.29x or later.

## Contents

The full reference manual lives in [`docs/reference/`](docs/reference/); each section below links into it.

- [What it is](#what-it-is)
- [Quick start](#quick-start)
- [Overview and request lifecycle](docs/reference/overview.md#overview-and-request-lifecycle)
  - [Two runtimes](docs/reference/overview.md#two-runtimes)
  - [Agent layers](docs/reference/overview.md#agent-layers)
  - [The control plane: eight hooks](docs/reference/overview.md#the-control-plane-eight-hooks)
  - [Lifecycle of one request](docs/reference/overview.md#lifecycle-of-one-request)
  - [Depth map of the example](docs/reference/overview.md#depth-map-of-the-example)
  - [How limits change behaviour mid-request](docs/reference/overview.md#how-limits-change-behaviour-mid-request)
- [Agents](docs/reference/agents.md#agents)
  - [Orchestration (`.claude/agents/orchestration/`)](docs/reference/agents.md#orchestration-claudeagentsorchestration)
  - [Planning (`.claude/agents/planning/`)](docs/reference/agents.md#planning-claudeagentsplanning)
  - [Quality (`.claude/agents/quality/`)](docs/reference/agents.md#quality-claudeagentsquality)
  - [Research (`.claude/agents/research/`)](docs/reference/agents.md#research-claudeagentsresearch)
  - [Synthesis (`.claude/agents/synthesis/`)](docs/reference/agents.md#synthesis-claudeagentssynthesis)
  - [Experts (`.claude/agents/experts/`)](docs/reference/agents.md#experts-claudeagentsexperts)
  - [Image (`.claude/agents/image/`)](docs/reference/agents.md#image-claudeagentsimage)
  - [Meta (`.claude/agents/meta/`)](docs/reference/agents.md#meta-claudeagentsmeta)
  - [Spawn policy](docs/reference/agents.md#spawn-policy)
  - [Common agent anatomy](docs/reference/agents.md#common-agent-anatomy)
  - [The visual-reviewer agent](docs/reference/agents.md#the-visual-reviewer-agent)
- [Delegation protocol, depth, doubts and context policy](docs/reference/delegation.md#delegation-protocol-depth-doubts-and-context-policy)
  - [The pre-agent hook](docs/reference/delegation.md#the-pre-agent-hook)
  - [The stack-context header](docs/reference/delegation.md#the-stack-context-header)
  - [Depth semantics](docs/reference/delegation.md#depth-semantics)
  - [Per-caller spawn rules](docs/reference/delegation.md#per-caller-spawn-rules)
  - [Spawn budget](docs/reference/delegation.md#spawn-budget)
  - [Token budgets as seen by delegation](docs/reference/delegation.md#token-budgets-as-seen-by-delegation)
  - [Delegate or do it yourself](docs/reference/delegation.md#delegate-or-do-it-yourself)
  - [Routing rubric: tiers, not overrides](docs/reference/delegation.md#routing-rubric-tiers-not-overrides)
  - [Writing the brief](docs/reference/delegation.md#writing-the-brief)
  - [Concurrency and the Workflow tool](docs/reference/delegation.md#concurrency-and-the-workflow-tool)
  - [Foreground calls and run_in_background](docs/reference/delegation.md#foreground-calls-and-run_in_background)
  - [Merging child results](docs/reference/delegation.md#merging-child-results)
  - [Output contract](docs/reference/delegation.md#output-contract)
  - [File offloading](docs/reference/delegation.md#file-offloading)
  - [Doubt escalation](docs/reference/delegation.md#doubt-escalation)
  - [Context-first policy](docs/reference/delegation.md#context-first-policy)
- [Saved workflows](docs/reference/workflows.md#saved-workflows)
  - [Workflows diagram](docs/reference/workflows.md#workflows-diagram)
  - [Launching](docs/reference/workflows.md#launching)
  - [Runtime contract](docs/reference/workflows.md#runtime-contract)
  - [fanout](docs/reference/workflows.md#fanout)
  - [swarm-run](docs/reference/workflows.md#swarm-run)
  - [mediate](docs/reference/workflows.md#mediate)
  - [expert-panel](docs/reference/workflows.md#expert-panel)
  - [research-sweep](docs/reference/workflows.md#research-sweep)
  - [review-verify](docs/reference/workflows.md#review-verify)
  - [plan-tournament](docs/reference/workflows.md#plan-tournament)
  - [visual-iterate](docs/reference/workflows.md#visual-iterate)
  - [manuscript-review](docs/reference/workflows.md#manuscript-review)
  - [Dry-run harness](docs/reference/workflows.md#dry-run-harness)
- [Hooks, model tiers and enforcement](docs/reference/hooks.md#hooks-model-tiers-and-enforcement)
  - [Hook wiring](docs/reference/hooks.md#hook-wiring)
  - [Fail-open contract](docs/reference/hooks.md#fail-open-contract)
  - [Latency](docs/reference/hooks.md#latency)
  - [`pre-agent`: depth guard, spawn rules, budgets and tier stripping](docs/reference/hooks.md#pre-agent-depth-guard-spawn-rules-budgets-and-tier-stripping)
  - [`subagent-stop`: telemetry and mid-session learning](docs/reference/hooks.md#subagent-stop-telemetry-and-mid-session-learning)
  - [`session-start`: status line](docs/reference/hooks.md#session-start-status-line)
  - [`session-end`: detached learner](docs/reference/hooks.md#session-end-detached-learner)
  - [`prompt-submit`: per-prompt budget note](docs/reference/hooks.md#prompt-submit-per-prompt-budget-note)
  - [Hook state files](docs/reference/hooks.md#hook-state-files)
  - [Hooks under the Agent SDK](docs/reference/hooks.md#hooks-under-the-agent-sdk)
  - [Model tiers](docs/reference/hooks.md#model-tiers)
  - [Enforcement layers](docs/reference/hooks.md#enforcement-layers)
  - [Token budgets](docs/reference/hooks.md#token-budgets)
- [Bayesian self-tuning](docs/reference/learning.md#bayesian-self-tuning)
  - [Data flow](docs/reference/learning.md#data-flow)
  - [What is observed per run](docs/reference/learning.md#what-is-observed-per-run)
  - [Models](docs/reference/learning.md#models)
  - [Applying changes](docs/reference/learning.md#applying-changes)
  - [Learner configuration reference](docs/reference/learning.md#learner-configuration-reference)
  - [Learner commands](docs/reference/learning.md#learner-commands)
- [Web content safety (prompt injection)](docs/reference/web-safety.md#web-content-safety-prompt-injection)
- [MCP servers, keys and the image server](docs/reference/mcp.md#mcp-servers-keys-and-the-image-server)
  - [Where keys live](docs/reference/mcp.md#where-keys-live)
  - [File format and parser rules](docs/reference/mcp.md#file-format-and-parser-rules)
  - [Delivering keys: `bin/mcp-run` and `headersHelper`](docs/reference/mcp.md#delivering-keys-binmcp-run-and-headershelper)
  - [Checking keys: `bin/stack keys`](docs/reference/mcp.md#checking-keys-binstack-keys)
  - [Stack servers (`config/mcp.servers.json`)](docs/reference/mcp.md#stack-servers-configmcpserversjson)
  - [Optional servers and `bin/stack mcp`](docs/reference/mcp.md#optional-servers-and-binstack-mcp)
  - [The image server](docs/reference/mcp.md#the-image-server)
- [Claude Agent SDK integration](docs/reference/sdk.md#claude-agent-sdk-integration)
  - [How a run is assembled](docs/reference/sdk.md#how-a-run-is-assembled)
  - [Two placements](docs/reference/sdk.md#two-placements)
  - [Agent definitions under the SDK](docs/reference/sdk.md#agent-definitions-under-the-sdk)
  - [MCP servers outside the repository](docs/reference/sdk.md#mcp-servers-outside-the-repository)
  - [Defaults for unattended runs](docs/reference/sdk.md#defaults-for-unattended-runs)
  - [Model allowlist and main-thread pinning](docs/reference/sdk.md#model-allowlist-and-main-thread-pinning)
  - [Hooks as Python callbacks](docs/reference/sdk.md#hooks-as-python-callbacks)
  - [Learning after a run](docs/reference/sdk.md#learning-after-a-run)
  - [Command-line interface](docs/reference/sdk.md#command-line-interface)
  - [Using it from Python](docs/reference/sdk.md#using-it-from-python)
  - [Runtime-compatibility rules](docs/reference/sdk.md#runtime-compatibility-rules)
  - [SDK limits](docs/reference/sdk.md#sdk-limits)
  - [SDK tests](docs/reference/sdk.md#sdk-tests)
- [Installation, packs, CLI and configuration reference](docs/reference/installation.md#installation-packs-cli-and-configuration-reference)
  - [Requirements](docs/reference/installation.md#requirements)
  - [Installation](docs/reference/installation.md#installation)
  - [Install packs](docs/reference/installation.md#install-packs)
  - [CLI reference](docs/reference/installation.md#cli-reference)
  - [Configuration reference](docs/reference/installation.md#configuration-reference)
  - [Runtime state](docs/reference/installation.md#runtime-state)
  - [Repository layout](docs/reference/installation.md#repository-layout)
  - [Testing](docs/reference/installation.md#testing)
  - [Doctor](docs/reference/installation.md#doctor)
  - [Troubleshooting](docs/reference/installation.md#troubleshooting)
- [Documentation](#documentation)

## Documentation

[Architecture](docs/ARCHITECTURE.md) · [Conventions](docs/CONVENTIONS.md) · [Depth and budgets](docs/DEPTH.md) ·
[Learning](docs/LEARNING.md) · [MCP servers](docs/MCP.md) · [Agent SDK](docs/SDK.md) · [Diagrams](docs/DIAGRAMS.md) ·
[Milestone relay](docs/MILESTONES.md) ·
[Reference manual](docs/reference/)
