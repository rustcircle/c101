---
name: planning-dag
description: "Plan format and method for this stack: task DAG with ids, dependencies, owners (agent names), write-sets, acceptance criteria, verification, risk, parallel waves and critical path; markdown and JSON templates, a stdlib validator that computes waves and slack, re-planning triggers, and how orchestrators execute a DAG wave by wave."
when_to_use: "When decomposing a goal into delegated tasks, writing or reviewing a plan or dag.json, executing a plan as orchestrator, or deciding whether a failure or new fact requires re-planning."
---

# Planning DAG

A plan is a directed acyclic graph of nodes. Each node is one delegated task with one owner, one
write-set, and a checkable definition of done. The plan also states what can run at once, what
determines total duration, and what makes you stop and re-plan.

Files:
- planner (standalone): `<YYYYMMDD-HHMM>-<slug>.md` plus a sibling `.json` in its `out_dir`;
- orchestrator run: `.stack/out/orchestrator/<YYYYMMDD-HHMM>-<slug>/` with `plan.md`, `dag.json`,
  `ledger.md` and `nodes/<id>/` for node reports; a planner called by the orchestrator writes
  `plan.md` and `dag.json` there.

The JSON is the source of truth for structure and status; the markdown carries rationale, and the
ledger records every dispatch and verdict. Field reference: [plan schema](references/plan-schema.md).
Full example plans and anti-patterns: [plan examples](references/plan-examples.md).

## 1. Method

1. **Goal and done-when.** One-sentence goal; 2-6 `done_when` items, each checkable by a command, a
   test, a citation check or a named reviewer; explicit non-goals. An unclear goal is a scope doubt
   for your caller (doubt-escalation), not a planning problem.
2. **Assumptions and unknowns.** Blocking unknowns (the DAG's shape depends on them): resolve now
   with a cheap lookup or return an Open doubt. Non-blocking: a time-boxed spike node early in the
   plan whose output is a written decision. Every assumption that could be wrong gets a re-plan trigger.
3. **Deliverables.** List the artefacts that must exist at the end and work backwards; every node
   contributes to a deliverable, every deliverable traces to nodes.
4. **Decompose** with the sizing rules (section 2).
5. **Edges.** Only real dependencies: *data* (consumes another node's artefact), *knowledge* (needs
   a spike's or design's decision), *resource* (same file, table or config key: serialise or split
   the write-set). "Feels sequential" is not an edge; every false edge lengthens the critical path.
6. **Owners** from the owner table (section 3), checked against the executor's remaining depth.
7. **Acceptance criteria**, at least one per node, in checkable form (section 4).
8. **Verification** per node: method plus an independent verifier (section 5).
9. **Risk** per node: likelihood x impact, mitigation and rollback where required (section 6).
10. **Estimate** each node in owner turns (`est_turns`); compute waves, slack and the critical path
    with the script (section 7); restructure when the plan is serial or the critical path is long.
11. **Validate** with `dag.py` and the checklist (section 11). Eight or more nodes, or any
    irreversible node: plan-critic red-teams it before execution (one round).

## 2. Node sizing

A node is right-sized when all hold:
- one owner, one deliverable, one verification;
- `est_turns` at most 0.6 x the owner's maxTurns (live values: `bin/stack agents list`);
- at most ~5 acceptance criteria and at most 2 subsystems touched;
- inputs are paths or upstream node ids, never "context from the conversation".

Split a node when it spans two disciplines, produces two artefact kinds (code and a report),
exceeds 0.6 x maxTurns, mixes reversible and irreversible work ("write migration" versus "apply
migration in prod"), or has parts that could run in parallel.
Merge nodes when one is under ~3 turns (brief overhead dominates), or when two nodes cannot be
verified separately.

Plan size: 3-15 nodes is typical. Above ~25, go hierarchical: phases whose nodes are sub-plans owned
by an orchestrator (the executor needs remaining_depth >= 3), or one bulk node owned by
swarm-coordinator or concurrent-dispatcher for homogeneous items.

## 3. Owner table

| Node kind | Owner |
|---|---|
| requirement decision, approval, human checkpoint | `caller` (returned as an Open doubt; the main thread asks the user in plain text at the end of its turn, never AskUserQuestion) |
| one fact, doc or vendor limit | quick-researcher |
| multi-source research, cited report | deep-researcher |
| papers, equations, algorithms from literature | paper-researcher |
| scrape or crawl known sites | web-scraper, web-crawler |
| interactive web flow / native macOS app | browser-operator / computer-operator (interactive only; under the SDK it falls back to `peekaboo` or the node is blocked) |
| task plan or sub-plan | planner |
| undecided architecture or technology (spike) | architect |
| red-team a plan or design | plan-critic |
| code in a language with an expert | rust-expert, cpp-expert, go-expert, haskell-expert, julia-expert, java-expert, kotlin-expert, python-expert, typescript-expert |
| containers, images, Kubernetes manifests, Helm/Kustomize, Quadlet | container-expert |
| glue, config, scripts with no matching expert | built-in general-purpose (no per-call model/effort; the hook strips them) |
| algorithms, consistency, concurrency design | computer-science-expert |
| domain analysis | mathematics-expert, physics-expert, quantum-computing-expert, computer-graphics-expert |
| tests | tester |
| failure with unknown cause | debugger |
| latency, throughput or memory target | code-optimizer |
| auth, untrusted input, secrets, dependencies | security-auditor |
| review of a change | reviewer |
| refute a claim or finding | adversarial-verifier |
| mechanical gate (commands, schemas, thresholds) | validator |
| images, vectors, design critique | image-generator, image-editor, vector-artist, graphic-design-expert |
| integrate several expert outputs | cross-domain-synthesizer |
| genuine judgement call between options | mediator |
| many homogeneous items | swarm-coordinator or concurrent-dispatcher (one node) |
| final gate before the caller | quality-control |

Saved workflows (research-sweep, plan-tournament, review-verify, mediate, swarm-run, fanout) may own
a node only when the executor is the main thread (no <stack-context> header). A subagent executor
uses the agent owner, or returns `Workflow name=<w> args={...}` as an Open doubt.

Depth check: the executor spawns every owner. With remaining_depth 1-2 at the executor, owners must
be workers or leaves (delegation-protocol); record the minimum as `requires_depth` in the plan.

## 4. Acceptance criteria

| Weak | Checkable |
|---|---|
| API is fast | p95 of GET /items <= 50 ms at 200 rps, `wrk -t4 -c64 -d30s`, median of 3 runs |
| tests added | new tests fail on the base commit and pass on the branch; `pytest -q` exits 0 |
| well researched | 5+ sources, 3+ primary, every claim cites URL and access date, contradictions listed |
| good design | ADR with 2+ rejected alternatives scored on named, weighted criteria |
| docs updated | every new config key appears in docs/config.md (grep count equals key count) |
| image looks right | 1024x1024 PNG with alpha; palette within the brief's hex values; reviewed against the brief |
| bug fixed | reproduction exits non-zero before the fix and 0 after; regression test added |

Words like robust, clean, fast or scalable are banned unless a number follows. Every criterion names
its evidence; validation-gates turns criteria into a pass/fail matrix.

## 5. Verification

| `verify.method` | Typical `verify.by` | Evidence |
|---|---|---|
| `command` | validator | exact command (`verify.how`), exit code, output excerpt |
| `test` | tester or validator | test names, pass/fail, failing-before proof for bugs |
| `review` | reviewer, plan-critic, quality-control, or a named expert | rubric scores, findings with path:line |
| `citation-check` | fact-checker | each claim with URL, date, verdict |
| `adversarial` | adversarial-verifier | survives or refuted, with reproduction |
| `user` | caller | the user's answer, recorded in the ledger |

Author and verifier differ; only `command` may be self-run, because its evidence is mechanical.
Code plans end with a validator node over `done_when`, then a single quality-control node.

## 6. Risk

risk = likelihood (1-3) x impact (1-3): 1-2 low, 3-4 medium, 6 or 9 high.

High-risk nodes get a mitigation, a rollback, an independent verifier, and the earliest feasible
position (fail fast, before expensive nodes build on them). Irreversible nodes (`irreversible:
true`: data migrations, releases, deletions, publishing) also get a `caller` checkpoint node directly
upstream and never share a wave with the change they depend on. Plan-level risks (external quotas,
missing credentials, unclear ownership) go in `assumptions` with a matching re-plan trigger. Full
failure-mode analysis: the red-teaming skill.

## 7. Waves, schedule and critical path

Definitions, with `est_turns` as duration:
- `wave(n) = 0` without deps, else `1 + max(wave(d))`. Same-wave nodes may run together.
- Forward pass: `ES(n) = max(EF(d))` over deps (0 if none); `EF(n) = ES(n) + est(n)`.
- Plan length `L = max EF`; total work `W = sum est`; parallelism `P = W / L`.
- Backward pass: `LF(n) = min(LS(s))` over successors (`L` if none); `LS(n) = LF(n) - est(n)`.
- Slack `= LS - ES`; the critical path is the chain of zero-slack nodes.
- Uncertain estimate: PERT `est = (optimistic + 4 x likely + pessimistic) / 6`.

Run the script instead of computing by hand ([dag.py](scripts/dag.py), stdlib, Python 3.9+):

```bash
python3 .claude/skills/planning-dag/scripts/dag.py <plan>.json            # validate; waves; ES/EF/LS/LF/slack; critical path; P
python3 .claude/skills/planning-dag/scripts/dag.py <plan>.json --ready    # pending nodes whose deps are done or skipped
python3 .claude/skills/planning-dag/scripts/dag.py <plan>.json --mermaid  # flowchart for plan.md
python3 .claude/skills/planning-dag/scripts/dag.py <plan>.json --json     # everything, machine-readable
```

Errors (exit 1): duplicate ids, unknown deps, cycles (naming the nodes on the cycle), missing owner,
acceptance or verify, unknown status, and certain write conflicts between nodes that can run
concurrently (same path, or a directory and a path inside it). Warnings: unknown owners, possible
glob overlaps (`src/**` versus `src/api/*.rs`), self-verification, high risk without mitigation,
irreversible nodes without rollback or upstream checkpoint, waves wider than 20, several final
nodes. The report ends with `ERRORS: none` when clean; paste that output into Evidence.

Reading the numbers:
- `P` near 1: the plan is serial. Hang work that needs only the design (tests from the spec, docs,
  config) off the design node instead of the implementation.
- Shorten the critical path, not the total: splitting a zero-slack node shortens L; splitting a
  node with slack only adds overhead.
- Nodes with large slack are where a cheaper (LOW/MEDIUM-tier) owner costs no time.

## 8. Templates

`plan.md`:

```markdown
# Plan: <goal> (v1)
Plan id: <slug> | Author: <agent> | Created: <YYYY-MM-DD HH:MM> | requires_depth: <n>
## Goal, done-when, non-goals
## Assumptions and unknowns
## Nodes
| id | title | owner (tier) | deps | writes | acceptance | verify | risk | est |
## Waves and critical path
W0: R1, R2 | W1: D1 | ... Critical path R1 -> D1 -> I1 -> RV -> QC (33 turns), P = 1.55
## Risks, mitigations, rollbacks
## Re-plan triggers
## dag.py output
```

`ledger.md` row: `| wave | node | owner (tier) | attempt | verdict | evidence path | note |`.

`dag.json`, one node shown (full examples in the references):

```json
{
  "plan_id": "ratelimit-go", "plan_version": 1, "requires_depth": 2,
  "goal": "Per-client rate limiting on the public HTTP API, with tests and docs",
  "done_when": ["over-limit requests get 429 with Retry-After", "go test -race ./... exits 0"],
  "non_goals": ["distributed limiter across regions"],
  "assumptions": ["single region; in-process limiter acceptable for v1"],
  "nodes": [
    {"id": "I1", "title": "Implement limiter middleware", "phase": "implement", "owner": "go-expert",
     "deps": ["D1"],
     "inputs": [".stack/out/architect/ratelimit-adr.md"],
     "writes": ["internal/ratelimit/limiter.go", "internal/http/middleware.go"],
     "acceptance": ["go build ./... exits 0", "429 + Retry-After when the bucket is empty"],
     "verify": {"method": "command", "by": "validator", "how": "go build ./... && go vet ./..."},
     "risk": {"likelihood": 2, "impact": 3, "mitigation": "feature flag, default off", "rollback": "disable flag"},
     "est_turns": 12, "status": "pending", "attempts": 0, "result": null}
  ],
  "replan_triggers": ["any node fails its gate twice", "a node exceeds 1.5x est_turns"],
  "replan_log": []
}
```

`dag.py` also accepts the aliases `write_set` and `outputs` for `writes`, `estimate` for
`est_turns`, `severity` for `impact`, a bare string for `verify`, and statuses PASS, FAIL, SKIPPED in
any case.

## 9. Executing a plan (orchestrator loop)

```
dag.py dag.json                       -> fix every ERROR before launching anything
loop:
  ready = dag.py dag.json --ready     -> pending nodes whose deps are done or skipped
  if ready is empty and nothing runs: stop (all done, or stuck: re-plan)
  order ready: critical path first, then risk desc, then slack asc
  if budget="soft": dispatch only critical-path and verification nodes; mark spike or exploratory nodes skipped (logged)
  if budget="hard": dispatch nothing except validator/quality-control/file-summarizer/source-summarizer nodes;
    stop and return Status partial with the remaining nodes as Open doubts
  batch = first min(20, H/2) nodes; heavy nodes (experts, researchers) at most ~8 per message
  one brief per node (mapping below); launch the batch as Agent calls in ONE message with
    `run_in_background: false`
  per result:
    Status done and verify passes (validator gate for implementing nodes) -> status done
    otherwise -> attempts += 1; retry once with the failure evidence; then the failure ladder
  phase end (research, implement, verify) -> quality-control on the phase output
  persist dag.json after every result; append a ledger row
end: validator over done_when, then quality-control; reply per output-contract
```

H is spawn headroom and `budget` the token level from your header (delegation-protocol). The failure ladder: retry the same owner once with the
evidence; then escalate (debugger for failing tests or crashes, a stronger ADVANCED-tier agent for reasoning
failures, e.g. the domain expert or computer-science-expert instead of a MEDIUM-tier owner, the domain
auditor for security or performance gates); then re-plan (section 10).

Brief mapping (delegation-protocol template):

| Brief field | From the node |
|---|---|
| GOAL | project goal in one line, plus this node's title and deliverable |
| CONTEXT | why the node matters and which nodes consume its output |
| INPUTS | `inputs`, plus the recorded output paths of its deps |
| CONSTRAINTS | modify only the `writes` paths; plan assumptions; turn budget about 1.5 x `est_turns` |
| ACCEPTANCE | `acceptance` verbatim, plus the `verify.how` command if any |
| OUTPUT | output-contract with a Result of 15 lines or fewer; report in `nodes/<id>/` (orchestrator run) or the owner's out_dir |

Barrier caveat: Agent calls in one message return together, so one slow node holds its batch. Accept
that (context usage over speed). Do not use `run_in_background: true` to overlap waves: the SDK runner
forces foreground and background ordering is not guaranteed. Split the long node instead if it
dominates L. Never let a successor depend on background completion order.

Statuses: `pending`, `running`, `done`, `failed`, `blocked` (waiting on an Open doubt), `skipped`
(deliberately dropped or a false `condition`; counts as finished; log why), `cancelled` (removed by
a re-plan). Never leave a node silently absent from the final ledger.

## 10. Re-planning

| Trigger | Response |
|---|---|
| a node fails its gate twice | local repair: other owner, split, or insert a spike, research or debug node before it |
| a spike or new fact falsifies an assumption | re-plan the subgraph that relied on it (its descendants) |
| a node exceeds 1.5x its `est_turns` | re-estimate the remaining nodes; report when L grows more than 50% |
| a hidden dependency or missing step appears | insert the node or edge; re-run dag.py |
| an upstream interface changes | re-verify done nodes that consumed it; re-plan dependants |
| the caller changes scope | full re-plan; keep done nodes whose outputs remain valid |
| a critical-path node is blocked on an Open doubt | escalate the doubt now; run slack-positive nodes meanwhile |
| spawn headroom below the remaining node count | merge nodes or move homogeneous work into one bulk node |
| header `budget` turns `soft` or `hard` | soft: drop exploratory nodes, go straight to verification; hard: finishing nodes only, return Status partial |

Protocol: freeze done nodes and their artefacts; send planner the failed node, its evidence and the
remaining DAG and accept a DAG patch, not a fresh plan, unless the evidence falsifies the approach;
increment `plan_version` and keep the previous file; append `{version, trigger, change, reason}` to
`replan_log`; re-run dag.py; tell the caller when goal, done-when or length changed materially. At
most two re-plans per goal; a third trigger means the goal is mis-specified: stop and return
`Status: partial` with the diagnosis as an Open doubt.

## 11. Plan checklist

- [ ] dag.py prints `ERRORS: none`; every warning fixed or justified in plan.md.
- [ ] Every node: real owner (or `caller`, or a built-in), inputs, write-set, 1-5 checkable
      acceptance criteria, a verify method naming a real command or agent, `est_turns` within
      0.6 x the owner's maxTurns.
- [ ] Traceability both ways: requirement to node, node to requirement (no orphans, no gaps).
- [ ] No concurrent nodes share a write-set; waves wider than 20 batched or moved to a bulk node.
- [ ] High-risk nodes early, mitigated, rolled back, independently verified; irreversible nodes
      behind a `caller` checkpoint.
- [ ] `requires_depth` set; no coordinator owners when the executor has remaining_depth below 3.
- [ ] No per-node model/effort; cost is set by choosing the owner's tier (effort-and-model-selection).
- [ ] Ends with validator over done-when (when mechanical) and one quality-control node.
- [ ] Re-plan triggers listed; critical path, L and P stated.

## 12. Worked example

Goal: per-client rate limiting for a Go HTTP service, with tests and docs.

| id | owner | deps | est | ES-EF | slack |
|---|---|---|---|---|---|
| R1 survey middleware and config | go-expert | - | 4 | 0-4 | 0 |
| R2 token bucket vs sliding window | quick-researcher | - | 3 | 0-3 | 1 |
| D1 ADR: algorithm, keying, storage, config | architect | R1, R2 | 8 | 4-12 | 0 |
| I1 limiter middleware | go-expert | D1 | 12 | 12-24 | 0 |
| T1 tests from the ADR | tester | D1 | 8 | 12-20 | 4 |
| I2 config keys and docs | go-expert | D1 | 4 | 12-16 | 11 |
| V1 race tests, vet, lint over done-when | validator | I1, T1, I2 | 3 | 24-27 | 3 |
| RV review | reviewer | I1, T1 | 6 | 24-30 | 0 |
| QC final gate | quality-control | V1, RV, I2 | 3 | 30-33 | 0 |

Waves: W0 R1, R2; W1 D1; W2 I1, T1, I2; W3 RV, V1; W4 QC. Critical path R1 -> D1 -> I1 -> RV -> QC,
L = 33, W = 51, P = 1.55. What the numbers show:
- T1 depends on D1, not I1: tests are written from the ADR in parallel with the code and must fail
  before I1 lands, which is real evidence for the regression claim.
- I2 has 11 turns of slack: a cheaper owner costs no time.
- I1, T1 and I2 write disjoint paths, so they share a wave; had I2 also listed
  `internal/http/middleware.go`, dag.py would report a write conflict.
- To shorten L, split I1 (zero slack), for example limiter core versus middleware wiring. Splitting
  T1 shortens nothing.

The full `dag.json` of this plan, which validates cleanly, and three more examples (research report,
multi-expert decision with a conditional vote, image asset pipeline) are in
[plan examples](references/plan-examples.md).
