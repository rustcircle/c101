# Bayesian self-tuning

After every session the stack learns, per agent type, how many steps (`maxTurns`), how much
reasoning (`effort`) and how many tokens it actually needs, and moves each agent's frontmatter
toward what the evidence supports. Code: `stack/learn/` (stdlib only). Config: `config/learning.json`.

## Data flow

```
SubagentStop (async, debounced)  ──> bin/stack learn ingest + update   (recommendations only; agent files untouched)
                                     also records, per stopped agent, the stop reason and the maxTurns in force
SessionStart                     ──> catch-up apply of anything still pending (see below)
PreToolUse Agent (pre-agent)     ──> records the agent file's maxTurns at the spawn (spawns/<session>.jsonl)
SessionEnd (detached background) ──> bin/stack learn run    transcripts -> ~/.claude/stack-data/obs/<session>.json
                                                            posteriors  -> recommendations.json, budgets.json
                                                            one line per session -> history.jsonl
                                                            apply_on "session_end": frontmatter <- maxTurns/effort/
                                                            autoCompactWindow (bounded, audited in changes.jsonl)
```

### When learned values take effect

Claude Code loads agent definitions when a session starts and watches `.claude/agents`: a changed file
is re-read from the **next turn** of a running session (measured with `-p`: a `maxTurns` raised between
turns was enforced from the next one). The watcher is not yet running while the session starts up, so a
write made during startup, such as the SessionStart apply, can be missed and wait for the next session.
Evidence (2026-10-26): `deep-researcher` ran with `maxTurns` 45 while its file already said 40. A session
can therefore run on a value one apply behind, and agent files can change under a running session
(another session ending, the catch-up).

So the default is `"apply_on": "session_end"`: the detached `learn run` ingests the finished session,
updates the posteriors and writes the new values, which puts them on disk before the next session loads
them and lets a session that is still running pick them up from its next turn.
`SessionStart` keeps a **catch-up** apply for a SessionEnd run that never finished (crash, `kill -9`,
closed terminal). `apply()` compares every value with the file as it is now and returns and logs only
writes that changed the file, so the catch-up after a SessionEnd apply is silent (no second
`changes.jsonl` row, no "Caught up" line); when it does write, its context line says the value is read from
the next turn and may only reach the next session. `apply_on: "session_start"` (legacy) applies only at
SessionStart, i.e. after the load. `"never"` or `auto_apply: false` disables both. If another learner run
holds `learn.lock`, the catch-up does nothing and the holder applies. `bin/stack-sdk run` applies before it
starts the CLI, so there the values are in force for that run.

Because files can change mid-session, the file is not a reliable record of what a run was held to. The
`pre-agent` hook therefore records, at every spawn, the target agent file's `maxTurns` keyed by the Agent
call's `tool_use_id` (`~/.claude/stack-data/spawns/<session>.jsonl`). `SubagentStop` finds that record
through the `toolUseId` in the agent's `.meta.json` and stores it as `limit_max_turns` with
`limit_basis: "spawn_record"`; without one it stores the file's value at stop time as `stop_frontmatter`.
Spawn records older than 14 days are pruned at SessionEnd.

### What is observed (per agent run)

Source: `~/.claude/projects/<project>/<session>.jsonl` (main thread) and
`<session>/subagents/**/agent-<id>.jsonl` + `.meta.json` (subagents; `agentType`, native `spawnDepth`).

| field | how it is measured |
|---|---|
| `tool_rounds` | responses that call ≥1 tool — the unit `maxTurns` counts (parallel calls in one response are one round) |
| `turns` | unique `message.id` among assistant records (Claude Code writes one line per content block) |
| `output_tokens` | final `usage.output_tokens`; sidechain records written from the stream's `message_start` carry placeholders (`stop_reason: null`), so those turns are estimated from content length (3.6 chars/token) and flagged `output_estimated` |
| `thinking_tokens` | `usage.output_tokens_details.thinking_tokens` |
| `ctx_peak` | max over turns of `input + cache_read + cache_creation` tokens — the context window actually used |
| `output_max_turn` | largest single-turn output — drives the max-output-tokens window |
| `effort` | the level in effect from the `SubagentStop` payload (`effort.level`, recorded by the hook); the transcript's per-line `effort` reflects the session level, so it is only a fallback |
| `model` | `message.model` (mode over the run) |
| `capped` | the run hit `maxTurns`: a max-turns stop reason or harness notice, or `tool_rounds >= limit` — a **right-censored** observation (rules below) |
| `tool_calls`, `tool_errors`, `agent_spawns`, `duration_s`, `spawn_depth`, `workflow` | diagnostics |

### How "capped" and the limit are decided

The turn limit in force is decided **once per run**, stored with the run (`limit_max_turns`, plus
`limit_source`, always the true basis) and never recomputed at re-ingest, so a later change to `maxTurns`
cannot reclassify old runs. Sources, best first:

1. the harness's own notice ("stopped at its N-turn limit", delivered to the parent): `harness_notice` (exact);
2. the spawn-time record of the run's `tool_use_id` (found by the engine, or carried by the `SubagentStop`
   record): `spawn_record`;
3. the agent file's `maxTurns` read by the `SubagentStop` hook: `stop_frontmatter` (wrong if the file changed
   while the run was going);
4. the value stored when the run was first ingested;
5. otherwise estimates: the frontmatter at first ingest (`frontmatter_at_first_ingest`), or the learner's change
   history around the session start (`change_history`; changes within 120 s of the start count as
   ambiguous and the smaller value is taken).

A run is `capped` when it carries a structured max-turns stop reason or a harness notice, or when
`tool_rounds >= limit` for the recorded limit, with or without a notice (every real cut-off seen had exactly
`limit` rounds). Capped runs enter the model as survival terms ("needed at least the limit").
Prose that merely quotes the notice (reports, thinking) is not a notice: only anchored forms count.

**Lowering is held, raising is not.** `maxTurns` is never lowered when the effective sample size is
below `min_obs_lower` (8; the code default if the key is absent) or when the most recent run was capped;
the reason is reported as `hold: ...`. Raising needs only `min_obs_turns` (3). Bounds always apply.

## Models

### maxTurns — censored log-normal, grid posterior

`log(tool_rounds) ~ Normal(μ, σ)`. Prior: `μ ~ N(log(maxTurns_current / 2.5), log 2.5)`,
`log σ ~ N(log 0.6, 0.6)` — i.e. the hand-set limit is taken as roughly 2.5× a typical run.
The posterior is computed exactly on a 48×28 grid over (μ, σ):

```
log p(μ,σ | data) = log prior
                  + Σ_exact  w_i · log φ((y_i − μ)/σ) − w_i log σ        (sufficient statistics)
                  + Σ_capped w_j · log(1 − Φ((log cap_j − μ)/σ))           (survival: "needed ≥ cap")
```

Censoring matters: if an agent keeps hitting a too-low cap, treating those runs as "needed exactly
cap turns" would lock the cap in place; as survival terms they push the posterior upward.

Recommendation = `ceil(q95 of the posterior predictive × 1.15)`, clamped to the agent's bounds,
moved at most ×2 / ÷2 per update, and only applied when it differs by ≥10% (hysteresis).
Requires an effective sample size ≥ 3.

### Data window — forgetting factor by prequential score

Observations are weighted `w_i = γ^(age_i)` (age in runs). γ ∈ {1, .99, .97, .94, .90, .85} is chosen
per agent by the **prequential log score**: for each of the last 12 runs, fit on the runs before it
and score the run with the predictive log density (or log survival if it was capped). Among the γ
within 1.5 nats of the best, the longest memory wins, so the window only shortens when there is
clear evidence of drift (new tasks, a model change). `effective_runs = (1−γⁿ)/(1−γ)` is reported.

### effort — Dirichlet over output-token bands + Beta failure rate

Each run is categorised by output tokens (thinking included) into a band:
`low < 4k ≤ medium < 16k ≤ high < 48k ≤ xhigh < 120k ≤ max`. A Dirichlet over the bands
(prior 0.5 each + stickiness 3 on the current level) gives the **smallest level covering 80%** of
runs. A Beta(1, 4) posterior on the failure rate (capped runs) then:

* escalates one level when `E[P(fail)] > 0.25` (the agent keeps running out of road), and
* blocks de-escalation while `E[P(fail)] > 0.08`.

Moves one level per update, within per-agent bounds (e.g. `mathematics-expert` never below `high`).
Requires an effective sample size ≥ 5.

### Token windows

Log-normal posteriors (same machinery, uncensored) on `output_tokens`, `tokens_total`, `ctx_peak`
and `output_max_turn` give `[min, median, max]` = predictive `[q05, q50, q95]` per agent, written to
`~/.claude/stack-data/budgets.json`:

* `max_output_tokens` = q95 of the largest single-turn output × 1.15, clamped to [8k, 128k] — use
  as `CLAUDE_CODE_MAX_OUTPUT_TOKENS` for headless runs of that agent;
* `recommend_1m_context` = q95 of `ctx_peak` > 80% of a 200k window — consider `model: opus[1m]`
  or `autoCompactWindow` for that agent;
* `autoCompactWindow` is raise-only. Every agent starts at **600000** (`default_traits` in
  `config/models.json`; also the floor in `config/learning.json` `default_bounds.autoCompactWindow`, whose
  upper bound is the tier model's `context_window`, 1,000,000 for all three tiers per Claude Code's model
  table). `bin/stack agents tiers --apply` raises any agent below the floor and clamps to the tier's window;
  `bin/stack doctor` warns below the floor and errors above the window. The learner code still clamps to
  100000..1000000 itself and does not yet read these bounds. The Agent SDK has no per-agent field for it:
  `stack_sdk` parses it, ignores it explicitly on the programmatic definition, and sends the largest value per
  model as `modelSettings.<model>.autoCompactWindow` in the session settings (agents loaded from disk read the
  frontmatter).

Internal agents (prompt suggestions, `/btw`) report an empty agent type and are ignored.

## Commands

```bash
bin/stack learn ingest --all            # backfill from every transcript on this machine
bin/stack learn update                  # recompute posteriors
bin/stack learn report                  # table: n, gamma, maxTurns cur->rec, effort cur->rec, P(fail), tokens
bin/stack learn report --agent rust-expert --json
bin/stack learn apply --dry-run         # what would change
bin/stack learn apply                   # write frontmatter (audited in ~/.claude/stack-data/changes.jsonl)
bin/stack learn start                   # apply pending values now (the SessionStart catch-up)
bin/stack learn history --by week       # per-agent trends from history.jsonl: turns, cap rate, errors, tokens
```

Set `"auto_apply": false` (or `"apply_on": "never"`) in `config/learning.json` to review changes before
they land, `"apply_on": "session_start"` for the legacy (one session later) timing, or `"enabled": false` to
stop learning. `min_obs_lower` (default 8) is the evidence needed before `maxTurns` may be lowered. Per-agent bounds live under `"agents"`; set `"learn": false`
there to freeze an agent. Changes are ordinary edits to tracked files, so `git diff .claude/agents`
shows exactly what the learner did.
