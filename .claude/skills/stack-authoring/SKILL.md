---
name: stack-authoring
description: "Adding or changing agents, skills and saved workflows in this stack: the conventions in docs/CONVENTIONS.md as procedures and copy-ready templates, choosing model, effort, maxTurns, MCP servers and preloaded skills, writing routing descriptions, registering learning bounds and settings wiring, rendering tiers with bin/stack agents tiers --apply, validating with bin/stack doctor and bin/stack-sdk check, dry-running workflow scripts, and smoke-testing a new agent headless."
when_to_use: "Before creating, renaming, splitting or restructuring any file under .claude/agents, .claude/skills or .claude/workflows, when bin/stack doctor reports errors, or when a new capability must be wired into the delegator, settings and learning bounds."
---

# Stack authoring

Contract: `docs/CONVENTIONS.md` (read it first, every time; this skill turns it into procedure).
Enforcement: `bin/stack doctor` (`stack/doctor.py`). Templates:
[templates](references/templates.md). Every doctor message with cause and fix:
[doctor errors](references/doctor-errors.md). Workflow dry-run without tokens:
`scripts/wf_harness.js`.

## 1. Decide what to build

| Need | Build | Instead of |
|---|---|---|
| A role with its own model, budget, MCP servers or tool restrictions that other agents route to | agent | a skill pretending to be a role |
| Procedure or knowledge several agents reuse | skill (preload via `skills:` only if every run needs it; otherwise agents load it with Skill) | the same section pasted into N agents |
| Fixed multi-agent choreography (phases, tallies, dedup, retries in code) that recurs | saved workflow | an orchestrator re-deriving the steps every time |
| An existing agent sometimes needs more depth or a cheaper run | callers pick an existing agent of the right tier (`LOW_MODEL` / `MEDIUM_MODEL` / `ADVANCED_MODEL` in `config/models.json`); per-call `model`/`effort` is stripped by the pre-agent hook | a "senior" or "lite" clone |
| An existing agent covers most of the need | extend its body or its role skill | a near-duplicate (routing then becomes a coin flip) |

Overlap check before writing anything:

```bash
bin/stack agents list
grep -rh '^description:' .claude/agents | grep -iE 'keyword1|keyword2'
grep -h '^description:' .claude/skills/*/SKILL.md | grep -iE 'keyword1|keyword2'
ls .claude/workflows
```

Compare trigger examples, not titles. Two agents whose "Use when" examples overlap will steal each
other's work.

## 2. Names and places

| Artifact | Path | Name rule |
|---|---|---|
| Agent | `.claude/agents/<group>/<name>.md` | kebab-case, equals file stem, no `:`; group one of orchestration, planning, quality, research, experts, image, synthesis, writing, meta |
| Skill | `.claude/skills/<name>/SKILL.md` (+ `references/`, `scripts/`) | equals directory name |
| Workflow | `.claude/workflows/<name>.js` | `meta.name`; must not equal a skill name or `deep-research` |
| Model tier + initial traits | `config/models.json` → `agents.<name>` = `{tier, effort, maxTurns, why}` | agent name (doctor ERROR if missing) |
| Learning bounds | `config/learning.json` → `agents.<name>` | agent name |
| Spawn rules | `config/policy.json` → `spawn_rules` (`callers`, `groups`) | agent name |
| Workflow permission | `.claude/settings.json` → `permissions.allow` → `"Workflow(<name>)"` | workflow name |

Renaming an agent breaks callers and resets its learning history (observations are keyed by
agent type). Do it only with the caller list updated in the same change.

## 3. New agent

1. Write a design note (the template is in [templates](references/templates.md)) to
   `.stack/out/<your-agent-name>/$(date +%Y%m%d-%H%M)-<slug>.md`: mission, inputs/outputs,
   callers, callees, model, effort, maxTurns with rationale, MCP servers, skills, bounds, test plan.
2. Pick frontmatter values:

| Field | How to choose |
|---|---|
| tier -> `model` | Choose the tier, not a model id: `ADVANCED_MODEL` (alias opus) for judgment, orchestration, deep domain reasoning; `MEDIUM_MODEL` (sonnet) for tool-heavy operators, checkers and well-trodden ecosystems; `LOW_MODEL` (haiku) for mechanical leaves. The frontmatter `model` is rendered from the tier (`bin/stack agents set <name> tier=<TIER>`); the aliases (opus/sonnet/haiku) are used only by saved workflows for `general-purpose` agents, and per-call `model`/`effort` on this stack's agents is stripped by the pre-agent hook. Trade-offs: effort-and-model-selection |
| `effort` | low: mechanical leaves; medium: operators and checkers; high: experts, reviewers, planners; xhigh: architecture, mediation, hard science; max: only when every run is proof-grade reasoning |
| `maxTurns` | Counts tool-use rounds (responses that call at least one tool). A moderate allowance: about 2 x the tool rounds of a typical demanding run (`config/models.json`), checked against peers of the same shape (command below). The learner's prior then centres on maxTurns / `prior_limit_ratio` (3.0; `jq .prior_limit_ratio config/learning.json`) and adjusts from evidence |
| `mcpServers` | Only servers the procedure calls: playwright, exa, jina, spider, context7, image, fetch, neural-memory (cross-session memory; never for web-reading agents) (catalog `config/mcp.servers.json`; set them with `bin/stack agents set <name> mcpServers=a,b`, which writes each one inline as one-line JSON so it connects only while the agent runs; never hand-edit the inline copies, run `bin/stack mcp sync` after a catalog change, never add them to `.mcp.json`) or built-in computer-use as a plain name (interactive sessions only: absent under the SDK/-p, so the procedure must fall back to playwright or the optional peekaboo server, or return the item as blocked). Optional servers in `config/mcp.optional.json` must be enabled (`bin/stack mcp enable <name>`) before they can be referenced |
| `skills` | Always `delegation-protocol, doubt-escalation, output-contract`, plus at most 3 role skills. Each preloaded skill costs about `wc -c SKILL.md / 3.6` tokens on every spawn |
| `color` | orchestration purple, planning blue, quality red, research cyan, experts green, image pink, synthesis yellow, writing yellow, meta orange (allowed: red blue green yellow purple orange pink cyan) |
| `disallowedTools` | `Agent` only for pure leaves that must never spawn; otherwise omit `tools` and inherit everything |

   Peers for calibration (tier, effort, initial maxTurns of every agent):
   `jq -r '.agents | to_entries[] | "\(.key) \(.value.tier) \(.value.effort) \(.value.maxTurns)"' config/models.json`

   Frontmatter order: name, description, model, effort, maxTurns, mcpServers, skills, color,
   disallowedTools. Lists inline (`[a, b]`).
3. Write the description as one physical line in double quotes, no inner double quotes, 300-600
   characters:
   `"<Role> that <does what, with which tools/methods>. Use when <conditions>. Examples - <trigger 1>; <trigger 2>; <trigger 3>."`
   Triggers are concrete requests a user or caller would phrase, distinct from neighbours'.
4. Write the body (second person, 120-260 lines) in this section order: mission paragraph
   ("You are the <role> of this agent stack."), `## Expertise` (domain experts only),
   `## When you are called`, `## Operating procedure`, `## Delegation`, `## Quality bar`,
   `## Output`, `## Never`. Checklist:
   - [ ] Procedure steps are numbered and name real tools (`Read`, `Grep`, `Bash`, `Agent`,
         `mcp__<server>__<tool>` only for declared servers). `Workflow` only in a step guarded by
         "only if you are the main thread (no <stack-context> header)"; otherwise fan out with
         parallel Agent calls or return `Workflow name=<w> args={...}` as an Open doubt.
   - [ ] Delegation names exact agent names and the tier of each (pick a cheaper or stronger
         agent instead of overriding; per-call `model`/`effort` is stripped by the pre-agent hook),
         what runs in parallel (several Agent calls in one message), `run_in_background: false`
         on calls whose result is needed next, behaviour at `remaining_depth` 0 and 1-2, and where
         children write files.
   - [ ] Quality bar items are verifiable (a command, a count, a threshold), not adjectives.
   - [ ] Output specialises the five output-contract sections for the role.
   - [ ] Never lists role-specific hard prohibitions (secrets, destructive actions, scope).
   - [ ] Runtime compatibility (CONVENTIONS section 11): no AskUserQuestion (doubts go out as Open
         doubts); `budget` soft/hard behaviour from the header stated; output past ~60 lines / 3k
         chars offloaded to `.stack/out/<name>/`; irreversible actions (publish, delete, send,
         payments, a push the user did not ask for) returned as Open doubts, a requested
         `git push` only through the hook's approval prompt; no computer use or Chrome without a
         playwright/peekaboo fallback; no step that needs an interactive approval.
5. Register the tier entry (always), learning bounds (when the defaults are wrong) and spawn rules
   (when the role must be restricted or must be reachable from restricted callers): section 6.
6. Validate (section 7) and smoke-test (section 8).
7. Wire it: the delegator's routing table and roster, orchestrator rosters that should use it, and
   the docs catalog table (`bin/stack agents list --markdown`). If the brief does not allow edits
   to those files, return the exact proposed lines as an Open doubt.

## 4. New skill

1. Frontmatter: `name` (= directory), `description` (one line, double-quoted, what it is + when to
   load it, >= 40 chars), optional `when_to_use`. Extra keys only from: argument-hint, arguments,
   disable-model-invocation, user-invocable, allowed-tools, model, effort, context (fork), agent,
   paths.
2. Body: procedural; decision tables, checklists, formulas, commands, one worked example, failure
   modes. Under 500 lines (aim for 450); protocol skills preloaded everywhere stay under 150.
3. Deep material (catalogs, long examples, cheat-sheets) in `references/<topic>.md`, linked from
   SKILL.md with an ordinary relative markdown link. Doctor fails on any such link into
   `references/`, `scripts/`, `examples/` or `assets/` whose target is missing, placeholders included.
4. Scripts in `scripts/`: Python 3.9+ stdlib (or Pillow via the stack venv when imaging),
   argparse with `--help`, deterministic, JSON on stdout, exit 0 ok / 1 check failed / 2 usage.
   Test every subcommand on a scratch input before shipping. Resolve paths so the script works from
   the repo and from the user-scope install (`$HOME/.claude/stack/.claude/skills/<name>/scripts/`).
5. No secrets, no instruction to read `~/.claude/stack.env`, no commands that print key values.

## 5. New saved workflow

Rules doctor enforces or checks: first statement `export const meta = {...}` as a pure literal
(no template strings, spreads or calls; parentheses inside strings are fine); plain JavaScript; no
`import`; no `Date.now()`, `Math.random()`, `new Date()`; literal `agentType` values must be known
agents; `meta.name` and `meta.description` present and unique; `phase('X')` titles should appear
in `meta.phases`.

Rules doctor does not catch (check yourself):
- [ ] Args normalised (`typeof args === 'string' ? JSON.parse(args) : (args || {})`, parse
      errors caught) and `{started: false, reason, next}` returned for missing required args.
- [ ] Every `agent()` has `agentType`, `label` and `phase`; dynamic agentType values validated
      against a list.
- [ ] No `model`/`effort` in `agent()` opts for this stack's agentTypes (the hook strips them;
      tiers decide); `model` only for `general-purpose`, as an alias (opus/sonnet/haiku).
- [ ] `pipeline()` by default; a `parallel()` barrier only where a stage needs all prior results
      (dedup, vote, tally, early exit).
- [ ] Every cap, skip and failure is `log()`ged and returned (`skipped`, `failed` arrays).
- [ ] Return value is a structured object, never prose only.
- [ ] Schemas: root `{type: 'object', properties: {...}}`, `required` a subset of properties.
- [ ] Total agents bounded (runtime cap 1000 per run; default concurrency about 10-16).

Dry-run before the first real run (mocked agents, zero tokens):

```bash
H="$HOME/.claude/stack/.claude/skills/stack-authoring/scripts/wf_harness.js"; [ -f "$H" ] || H=.claude/skills/stack-authoring/scripts/wf_harness.js
node "$H" .claude/workflows/<name>.js                       # no args: must return {started:false,...}
node "$H" .claude/workflows/<name>.js --args '{"claims":["a","b"]}' --fixtures fx.json --quiet
```

Fixtures map agentType (or `label:<label>`) to the value `agent()` returns; arrays are served
round-robin and `null` simulates a dead agent, so failure paths get exercised. The harness warns on
missing label/phase/agentType, phases absent from `meta.phases`, and non-object returns.

Then add `"Workflow(<name>)"` to `.claude/settings.json` `permissions.allow` (when allowed by the
brief) and have it run once for real with a minimal input: if you are the main thread (no
<stack-context> header), call `Workflow` with name `<name>` and that input; otherwise return
`Workflow name=<name> args={<minimal input>}` as an Open doubt for the main thread.

## 6. Tier, learning bounds, spawn rules

Tier entry (required for every agent; doctor errors without it). Initial `effort`/`maxTurns` here
are written to frontmatter only when missing; afterwards the learner owns them.

```bash
jq '.agents["<name>"] = {"tier": "MEDIUM_MODEL", "effort": "medium", "maxTurns": 60, "why": "<one line>"}' \
  config/models.json > config/models.json.tmp && python3 -m json.tool config/models.json.tmp >/dev/null \
  && mv config/models.json.tmp config/models.json
bin/stack agents set <name> tier=MEDIUM_MODEL     # renders model (and missing traits) for this agent only
bin/stack agents tiers                            # dry run: model drift and missing traits for every agent
bin/stack agents tiers --apply                    # render tier model ids into all frontmatter; fills only missing effort/maxTurns, keeps learned values
```

Use `tiers --apply` after adding several agents or after changing a tier id in `config/models.json`;
the dry run must then report that all agents match their tiers.

Do not run `bin/stack agents tiers --apply --reset-traits` to fix one agent: it rewrites effort and
maxTurns of every agent and discards what the learner found.

Learning bounds (`config/learning.json` → `agents.<name>`) when `default_bounds` (read it:
`jq .default_bounds config/learning.json`) is wrong for the role:

| Role | Bounds | Why |
|---|---|---|
| Cheap leaf (summarizer, searcher, formatter) | `"maxTurns": [6, 200], "effort": ["low", "medium"]` | Never let a leaf drift into an expensive configuration |
| Quality-critical reasoner (mediator, verifier, math) | `"effort": ["high", "max"]` | Low output volume must not de-escalate effort |
| Orchestrator / main router | `"maxTurns": [60, 1000], "effort": ["medium", "max"]` | Long runs are normal; floor prevents starving |
| Bimodal workload (tiny and huge tasks) | `"learn": false` | One log-normal fits neither mode; manage by hand |

```bash
jq '.agents["<name>"] = {"maxTurns": [6, 200], "effort": ["low", "medium"]}' config/learning.json > config/learning.json.tmp \
  && python3 -m json.tool config/learning.json.tmp >/dev/null && mv config/learning.json.tmp config/learning.json
```

The frontmatter values must sit inside the bounds. Tuning existing agents belongs to stack-tuning.

Spawn rules (`config/policy.json` → `spawn_rules`, enforced by the pre-agent hook; `Agent(type)`
allowlists in `tools` are ignored by Claude Code, so this is the only way to restrict children):

| New agent is | Edit |
|---|---|
| A leaf that may only use summarizers/researchers | `callers.<name> = ["file-summarizer", "quick-researcher"]` (or `["@research_leaves"]`) |
| A research leaf other restricted agents should reach | append it to `groups.research_leaves` |
| A coordinator | append it to `groups.orchestration` (then it is never started below `orchestrators_until_depth`) |
| A doubt resolver | append it to `groups.doubt` |
| Anything else | nothing: callers not listed may spawn anything |

Validate with `python3 -m json.tool config/policy.json >/dev/null`.

## 7. Validate

```bash
bin/stack doctor 2>&1 | grep -F '<path you wrote>'           # zero ERROR lines for your files
awk '/^---$/{c++; next} c>=2' <agent.md> | wc -l             # agent body 120-260 lines
grep -n '^## ' <agent.md>                                    # sections present and in order
wc -l .claude/skills/<name>/SKILL.md                         # < 500
python3 -m json.tool config/learning.json >/dev/null         # if you touched it (same for models.json, policy.json)
bin/stack agents tiers                                       # no drift for the new agent
bin/stack-sdk check                                          # SDK AgentDefinitions for both placements; must exit 0
bin/stack-sdk agents --json | jq '.[] | select(.name=="<name>")'   # tier model id, effort, maxTurns, mcpServers, skills; dropped only ["color"]
```

`bin/stack-sdk check` fails when a frontmatter key cannot be represented as an SDK
`AgentDefinition` or the model is not one of the three tier ids.

Then check every name you reference exists: agents (`bin/stack agents list`), skills
(`ls .claude/skills`), workflows (`ls .claude/workflows`), MCP servers (`jq '.servers|keys' config/mcp.servers.json`, plus `.mcp.json`).
Ignore doctor errors about artifacts another writer is creating in the same batch only when that
is stated in your brief; otherwise fix or report them.

## 8. Smoke-test a new agent

Agent definitions load at session start; the session that wrote the file may not route to it.

```bash
mkdir -p .stack/out/smoke
# 1. Direct, as main thread (no stack-context header; depth 0 behaviour), with a hard cost cap
claude -p --agent <name> --max-budget-usd 0.50 --output-format json \
  "<tiny brief with one checkable acceptance criterion>" > .stack/out/smoke/<name>-direct.json
jq -r '.result' .stack/out/smoke/<name>-direct.json | grep -cE '^## (Result|Evidence|Files|Open doubts|Confidence)$'   # expect 5

# 2. Routed, as a subagent of the delegator (exercises the description and the pre-agent header)
bin/claude-stack -p --max-budget-usd 1.00 --output-format json \
  "<request matching one 'Use when' example, without naming the agent>" > .stack/out/smoke/<name>-routed.json
SID=$(jq -r '.session_id' .stack/out/smoke/<name>-routed.json)
find ~/.claude/projects -path "*$SID/subagents*" -name 'agent-*.meta.json' -exec jq -r '.agentType' {} \;   # expect <name>

# 3. Under the Agent SDK (dontAsk allow-list, foreground subagents)
bin/stack-sdk run --agent <name> --max-budget-usd 0.50 --json \
  "<tiny brief with one checkable acceptance criterion>" > .stack/out/smoke/<name>-sdk.json
```

Read the subagent transcript tail for: the stack-context header at the top of its prompt, tools
it actually called (only declared MCP servers), files under `.stack/out/<name>/`, and the five
output-contract headings. Do not use `--no-session-persistence` here; it removes the transcript.
Smoke runs are tiny and atypical; they get ingested like any run, so keep them few.

Acceptance for a new agent: doctor clean for its files; body 120-260 lines; `bin/stack-sdk check`
exits 0; direct and SDK smoke runs return the five headings and meet the criterion; routed run
lands on the agent for at least one of its trigger examples; bounds (if any) contain the
frontmatter values.

## 9. Changing existing definitions

- Read the whole file first; state the diff in your reply.
- Never hand-edit `maxTurns`/`effort` of an existing agent (the learner and stack-tuning own
  them); change bounds instead, or ask the caller.
- Description edits change routing for everyone: re-run the routed smoke test for the agent and
  its nearest neighbour.
- Removing an agent: grep for its name across `.claude/` and `config/` first and update callers,
  bounds and settings in the same change.

## 10. Worked example (a new agent that does not exist yet)

Need: "TypeScript help keeps going to general-purpose; we want a TypeScript expert."

1. Overlap: no `typescript` in agent descriptions; `java-expert`/`kotlin-expert` triggers do not
   mention TS. Decision: new expert agent plus a role skill `typescript-craft` (new skill dir).
2. Values: group experts, tier `MEDIUM_MODEL` (well-trodden ecosystem), `effort: high`, typical
   demanding run ~40 tool rounds -> `maxTurns: 80` (2 x 40),
   `mcpServers=context7` (written inline by `bin/stack agents set`), `skills: [delegation-protocol, doubt-escalation, output-contract, typescript-craft]`,
   `color: green`.
3. Write `.claude/skills/typescript-craft/SKILL.md` first (doctor fails the agent while its skill
   is missing), then `.claude/agents/experts/typescript-expert.md` from the expert template.
4. Tier entry `{"tier": "MEDIUM_MODEL", "effort": "high", "maxTurns": 80, "why": "TypeScript
   and Node toolchain specialist"}` in `config/models.json`, then
   `bin/stack agents set typescript-expert tier=MEDIUM_MODEL`. Bounds: none (defaults fit an
   expert). Spawn rules: none (unrestricted like the other experts).
5. `bin/stack doctor 2>&1 | grep -E 'typescript-(expert|craft)'` -> nothing. Body 190 lines.
6. Smoke: direct run "Fix the type error in this 20-line snippet; prove it with tsc --noEmit"
   returns 5 headings; routed run "why does tsc say Type 'string' is not assignable to type
   'never' here?" lands on typescript-expert.
7. Wiring proposed to the caller: one row in the delegator routing table, one line in the docs
   catalog.

## 11. Never

- Never invent frontmatter keys, models, MCP servers, tool names, agents or skills.
- Never give an agent `mcp__<server>__*` tools from a server it does not declare.
- Never ship with doctor errors on your files, or with a workflow that was never dry-run.
- Never put key values in any file, or instruct anyone to read `~/.claude/stack.env`.
- Never name a workflow after a skill or `deep-research`.
