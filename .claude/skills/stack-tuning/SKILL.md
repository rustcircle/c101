---
name: stack-tuning
description: "Operating the stack's Bayesian self-tuning loop: bin/stack learn ingest, update, apply, report and run; reading posteriors (censored log-normal tool rounds, effort bands with Dirichlet and Beta failure rate, token windows, forgetting factor gamma and effective runs); the learned raise-only autoCompactWindow and the global token budget report (budgets.json _global); diagnosing recommendations; editing per-agent bounds and global knobs in config/learning.json; safe manual overrides, freezing, snapshots and rollback."
when_to_use: "When asked why an agent's maxTurns or effort changed, to review or apply tuning recommendations, to set or change bounds in config/learning.json, to freeze or roll back an agent's budget, or when an agent keeps hitting its turn cap or looks over- or under-provisioned."
---

# Stack tuning

The learner moves each agent's `maxTurns` and `effort` toward what observed runs support, within
bounds you control. Your job: keep the data clean, read the posteriors correctly, let good
recommendations land, stop bad ones, and explain every change in numbers.

Code: `stack/learn/` (`ingest.py`, `bayes.py`, `model.py`, `engine.py`). Config:
`config/learning.json`. Human doc: `docs/LEARNING.md`. Math and a full worked example:
[learner math](references/learner-math.md). Data file formats:
[data files](references/data-files.md).

## 1. The loop

```
SubagentStop hook (async; appends the effort in effect to stops/<session>.jsonl; ingest
                   debounced 60 s; update at most every 30 min; never applies)
SessionEnd hook (detached `bin/stack learn run --transcript <main transcript>`, waits for learn.lock);
                   under the SDK `bin/stack-sdk run` runs the same learn run itself after the result
   -> ingest:  transcripts -> $CLAUDE_STACK_DATA/obs/<session>.json (one record per agent run)
   -> update:  posteriors  -> recommendations.json, budgets.json
   -> record:  one summary line per session -> history.jsonl
   -> apply:   (apply_on "session_end", inside learn run) frontmatter maxTurns/effort (bounded) and
               autoCompactWindow (raise-only) of managed agents + changes.jsonl audit line
SessionStart hook of the next session (`bin/stack learn start`; skipped if learn.lock is held)
   -> catch-up apply of anything still pending; "Caught up pending learned values ..." (silent when SessionEnd already wrote them)
```

`apply_on` in `config/learning.json` picks when apply runs: `"session_end"` (default, inside `learn run`),
`"session_start"` (legacy) or `"never"`. Claude Code loads agent files at session start and re-reads a changed one
from the next turn (not before its file watcher is up during startup), so a value written at session end is in force
from the next session's first delegation and a running session reads it on its next turn; one written at session
start can wait a session. The limit a run was held to is recorded at spawn (`spawns/<session>.jsonl`).

`$CLAUDE_STACK_DATA` defaults to `~/.claude/stack-data`. Debounce and interval come from
`config/policy.json` (`ingest_debounce_seconds`, `midsession_update_minutes`).

## 2. Commands

| Command | Does | Writes |
|---|---|---|
| `bin/stack learn ingest --all [--since-days N]` | Re-parse every session transcript under `~/.claude/projects` (idempotent per session) | `obs/*.json` |
| `bin/stack learn ingest --transcript P` | One session (main `.jsonl` plus its `subagents/**`) | `obs/<session>.json` |
| `bin/stack learn update [--agent A ...]` | Recompute posteriors (all agents unless filtered; filtered runs rewrite the files with only those agents) | `recommendations.json`, `budgets.json` |
| `bin/stack learn report [--agent A] [--json]` | Table or JSON of the latest recommendations | nothing |
| `bin/stack learn apply --dry-run [--agent A]` | Show what would change | nothing |
| `bin/stack learn apply [--agent A]` | Write recommended values into agent frontmatter | agent `.md`, `changes.jsonl` |
| `bin/stack learn run --transcript P` | ingest + update + record history; applies only with `apply_on: "session_end"` (what SessionEnd runs) | `obs/`, `recommendations.json`, `budgets.json`, `history.jsonl` |
| `bin/stack learn start` | Apply pending values now (what SessionStart runs) | agent `.md`, `changes.jsonl` |
| `bin/stack learn history [--agent A] [--since-days N] [--by week\|day\|session] [--json]` | Per-agent trends per period: sessions, runs, turns50, max turns, cap_rate, tool errors, maxTurns and effort cur->rec (`--json` adds tokens_per_run) | nothing |
| `bin/stack agents list [--json]` | Current model / effort / maxTurns per agent | nothing |
| `bin/stack agents set A maxTurns=N effort=E` | Manual frontmatter edit, re-validated by doctor (`tier=<TIER>` moves the agent to another model tier) | agent `.md` (`config/models.json` for tier) |
| `bin/stack agents tiers [--apply]` | Dry run / render tier model ids into frontmatter; fills missing effort/maxTurns from `config/models.json` | agent `.md` |
| `bin/stack depth [SESSION]` | Spawn counts per depth (context for anomalies) | nothing |

Helper script (uses the learner's own code, so numbers match):

```bash
T="$HOME/.claude/stack/.claude/skills/stack-tuning/scripts/tune_tool.py"; [ -f "$T" ] || T=.claude/skills/stack-tuning/scripts/tune_tool.py
python3 "$T" history [--agent A] [--since-days 14]      # applied changes with reasons and n_eff
python3 "$T" snapshot                                   # baseline of every agent's model/effort/maxTurns
python3 "$T" revert-plan --agent A [--steps N] [--snapshot PATH]
python3 "$T" whatif --agent A --set turns_quantile=0.9 --bounds maxTurns=40,120 --bounds effort=medium,high
```

Important: after a filtered `update --agent A`, run a full `bin/stack learn update` before a
global `apply`, otherwise `recommendations.json` only contains the filtered agents.

## 3. Reading the report

`bin/stack learn report` columns: `agent n gamma maxTurns(cur->rec) effort(cur->rec) P(fail) tokens out [min..max]`.
Rows with `status` other than `ok` are hidden; use `--json` for everything.

| JSON field | Meaning | How to use it |
|---|---|---|
| `n` | Runs observed (capped at `max_history_per_agent`, newest kept) | < 5: treat everything as provisional |
| `window.gamma` | Forgetting factor chosen by prequential log score from {1, .99, .97, .94, .90, .85} | 1.0 = stable behaviour; <= 0.94 = recent drift (new prompt, model, task mix) |
| `window.effective_runs` | (1 - gamma^n) / (1 - gamma) | How many runs the posterior effectively listens to |
| `turns.q50 / q90 / q95 / q99` | Posterior-predictive quantiles of tool rounds per run (responses that called at least one tool; parallel calls in one response count once), the unit `maxTurns` limits | q95 drives maxTurns; q50 is the typical run |
| `turns.n_eff`, `turns.n_capped` | Weighted sample size; runs that hit the cap | n_capped / n >= 0.2: the cap is binding |
| `maxTurns.recommended`, `.reason` | Proposed value and rule | Reasons: `q95 of predictive x 1.15 margin`, `within hysteresis band`, `insufficient data` |
| `effort.band_probs` | Dirichlet predictive over output-token bands | Mass above the current level means runs produce more than that level suggests |
| `effort.p_fail_mean`, `p_fail_q90` | Beta posterior of the cap-hit rate | > 0.25 escalates; > 0.08 blocks de-escalation |
| `effort.observed` | Most common effort in effect: from the SubagentStop payload (`stops/<session>.jsonl`) when recorded, else from the transcript | Differs from frontmatter: the frontmatter changed inside the window (section 6) |
| `tokens.*` | [q05, q50, q95] for output_tokens, tokens_total, ctx_peak, output_max_turn | Cost and context planning |
| `budget.max_output_tokens` | ceil(q95 of output_max_turn x 1.15) to 1k, clamped to [8k, 128k] | Use as `CLAUDE_CODE_MAX_OUTPUT_TOKENS` for headless runs of that agent |
| `budget.recommend_1m_context` | q95 of ctx_peak > 0.8 x 200k | Context pressure: the learner raises `autoCompactWindow` itself (next row); also push offloading and summarizer delegation. Model variants outside the three tiers are refused |
| `budget.autoCompactWindow` | Present when n_eff >= `min_obs_turns` and q95 ctx_peak > `context_pressure` (0.8) x the current window (frontmatter `autoCompactWindow`, else `context_window_tokens` 200k): ceil(q95 ctx_peak x 1.15) to 10k, clamped 100000..1000000, only if above the current window | `learn apply` writes it when `apply_compact_window` is true (config/learning.json); never lowered automatically. Set `apply_compact_window: false` to stop it, or lower it by hand with `bin/stack agents set A autoCompactWindow=N` |
| `managed` | Agent file found and `learn` not false | Only managed agents are written by apply |

Global token budgets: `jq ._global "${CLAUDE_STACK_DATA:-$HOME/.claude/stack-data}"/budgets.json` ->
`{n_sessions, n_prompts, session|prompt: {n, q50, q90, q95}, recommended, applied}`, fitted from
`sessions/*.usage.json` (>= 5 sessions, >= 10 prompts). Raise-only: soft = min(max(cfg_soft,
1.25 x q90), 2 x cfg_soft); max = min(max(cfg_max, 1.5 x q95, soft), 2 x cfg_max). They take effect
only with `token_budget.learn_global: "apply"` in config/policy.json (default `report`); the hooks
then read `_global.applied`. Report them; never lower config/policy.json limits from this data.

## 4. The rules in one screen

maxTurns (needs n_eff >= `min_obs_turns` = 3):
```
data:    y = log(tool_rounds) per run (raw API responses are kept as `turns` but not modelled)
prior:   y ~ N(mu, sigma); mu ~ N(log(maxTurns_current / r), log 2.5); log sigma ~ N(log 0.6, 0.6)
         r = prior_limit_ratio (3.0 in config/learning.json; `jq .prior_limit_ratio config/learning.json`)
target = ceil(Q_0.95(predictive) x 1.15)
target = clamp(target, floor(cur / 2), ceil(cur x 2))      # max_step_factor 2
target = clamp(target, bounds.lo, bounds.hi)
apply only if |target - cur| >= max(2, 0.10 x cur)          # hysteresis
capped runs (tool_rounds >= limit in force, or a max-turns marker) enter as survival terms: "needed >= cap"
```

effort (needs n_eff >= `min_obs_effort` = 5):
```
band of a run by output tokens: low <4k <= medium <16k <= high <48k <= xhigh <120k <= max
Dirichlet prior 0.5 per level + 3.0 on the current level; idx = smallest level with cumulative mass >= 0.80
P(fail) ~ Beta(1 + fails, 4 + successes), fails = capped runs (weighted by gamma)
if E[P(fail)] > 0.25: idx = max(idx, current + 1)
elif idx < current and E[P(fail)] > 0.08: idx = current
move at most one level per update; clamp to bounds
```

Facts that change interpretation:
- "Failure" is a cap hit. Tool errors are recorded (`tool_errors`) but not used by the model.
- Output tokens on subagent turns are often estimated from content length (3.6 chars/token,
  flagged `output_estimated`); thinking that is not written to the transcript is not counted, so
  effort bands can read low for heavy thinkers.
- The main thread is attributed to `$CLAUDE_STACK_MAIN_AGENT` (set by `bin/claude-stack` and
  `bin/stack-sdk run --agent`, default `delegator`), else to `main`, which has no agent file and is never applied.
- Subagents without a `meta.json` (and internal helpers with an empty type) are recorded as
  `unknown` and skipped by `update`.
- `config/models.json` holds each agent's tier and initial effort/maxTurns. `bin/stack agents tiers --apply`
  writes only `model` (and traits that are missing); `--reset-traits` rewrites effort and maxTurns of
  every agent back to the initial values, discarding everything learned. Snapshot first.
- A tier model change (new id for ADVANCED/MEDIUM/LOW_MODEL, or the env override) shifts every
  distribution of the affected agents; expect gamma to drop for a while and review after ~8 runs.

## 5. Review runbook (weekly, or when asked)

1. `python3 "$T" snapshot` (cheap insurance; keep the path for rollback).
2. `bin/stack learn ingest --all --since-days 14` then `bin/stack learn update`.
3. `bin/stack learn report` and `bin/stack learn apply --dry-run`.
4. Triage every proposed change with the table below. For each "investigate", open 1-2 capped
   transcripts; the observation records carry their paths:
   `jq -r '.[] | select(.agent_type=="A" and .capped) | .transcript' "${CLAUDE_STACK_DATA:-$HOME/.claude/stack-data}"/obs/*.json | tail -3`
   then extract with code instead of reading raw lines (one line can hold a whole tool result):
   `tail -n 200 <path> | jq -r 'select(.type=="assistant") | .message.content[]? | if .type=="tool_use" then "TOOL \(.name) \(.input|tostring|.[0:160])" elif .type=="text" then "TEXT \(.text[0:200])" else empty end' | tail -n 40`.
   For a full read, send the path to `file-summarizer` and work from its digest.
5. Apply the accepted ones: `bin/stack learn apply --agent A [--agent B ...]`. Pin or bound the
   rejected ones (section 7) so they do not land on the next auto-apply.
6. `bin/stack doctor 2>&1 | grep -E 'ERROR|learning.json'` must show nothing new.
7. Report: table of agent, old -> new, reason, n_eff, gamma, P(fail), and your verdict.

| Signal | Meaning | Action |
|---|---|---|
| maxTurns up, n_capped/n >= 0.2 | Cap is binding | Read 1-2 capped runs: real work cut short -> accept. Looping, retrying the same tool, waiting on a dead MCP -> reject, fix the prompt or tool, set an upper bound |
| maxTurns up to exactly 2x current | Step limit hit; true need may be higher | Accept; next update continues. Raise bounds.hi if it sits at the bound |
| maxTurns down, n_capped = 0, n_eff >= 10 | Over-provisioned | Accept unless runs are bimodal (rare huge tasks); then keep a higher floor |
| effort up via `escalate: P(fail)=...` | Keeps running out of turns | Check it is not a maxTurns problem first: raising turns may remove the failures |
| effort down for a quality-critical agent (mediator, mathematics-expert, adversarial-verifier) | Output volume is low, not difficulty | Reject via an effort floor in bounds |
| gamma <= 0.90 | Strong drift; effective window 6-10 runs | Fine after a deliberate change; otherwise investigate what changed |
| `observed` effort differs from frontmatter | Frontmatter changed during the window (apply, agents set) | Re-ingest with `--since-days` after the change (section 6) |
| recommend_1m_context true | Context peaks above 160k | Prefer offloading (output-contract) and summarizer delegation; check the learned `autoCompactWindow` landed |
| status `no-data` / not in report | Agent never ran since ingest | Nothing to do |

## 6. Observed effort differs from frontmatter

Per-call `model`/`effort` on Agent calls are stripped by the pre-agent hook (`enforce_tiers` in
config/policy.json), and saved workflows may override model only for `general-purpose`, which is
not managed. So an `observed` effort that differs from frontmatter means the frontmatter changed
inside the window (learned apply or `agents set`), or, for the main-thread agent only, the user
changed effort in the session (`/effort`). Re-ingest with a `--since-days` window that starts
after the change; do not freeze the agent for this.

## 7. Bounds and global knobs (config/learning.json)

Per-agent block, all keys optional; missing keys fall back to `default_bounds`
(`jq .default_bounds config/learning.json`; maxTurns [5, 1000], effort [low, max], learn true when
this was written):

```json
"agents": {
  "rust-expert":        {"maxTurns": [40, 200], "effort": ["high", "xhigh"]},
  "adversarial-verifier": {"effort": ["high", "max"]},
  "web-searcher":       {"maxTurns": [10, 60], "effort": ["low", "medium"]},
  "orchestrator":       {"learn": false}
}
```

- Pin a value: `"maxTurns": [80, 80]` (the learner can only recommend 80) or `"learn": false`
  (agent becomes unmanaged; apply skips it entirely).
- Edit with jq, then validate and preview:
  ```bash
  jq '.agents["rust-expert"] = {"maxTurns": [40, 200], "effort": ["high", "xhigh"]}' config/learning.json > config/learning.json.tmp \
    && python3 -m json.tool config/learning.json.tmp >/dev/null && mv config/learning.json.tmp config/learning.json
  bin/stack doctor 2>&1 | grep learning.json      # warns on unknown agent names
  bin/stack learn update && bin/stack learn apply --dry-run --agent rust-expert
  ```
- Bounds must stay within doctor's limits (maxTurns 1..3000; effort one of low, medium, high,
  xhigh, max) and lo <= hi.

Global knobs (change rarely; preview with `whatif --set key=value` first):

| Key | Default | Raise it to | Lower it to |
|---|---|---|---|
| `turns_quantile` | 0.95 | cut fewer runs short (0.98) | save turns on cheap agents (0.9) |
| `turns_margin` | 1.15 | add headroom | tighten caps |
| `prior_limit_ratio` | 3.0 | assume hand-set caps are generous | assume caps are tight |
| `min_obs_turns` / `min_obs_effort` | 3 / 5 | demand more evidence before any change | never below 3 / 5 |
| `min_change_frac` | 0.10 | fewer, larger edits (less churn) | finer tracking |
| `max_step_factor` | 2.0 | faster convergence | gentler moves |
| `effort_bands_output_tokens` | [4000, 16000, 48000, 120000] | if models get more verbose | if terser |
| `effort_cover_mass` | 0.80 | higher effort defaults | cheaper defaults |
| `fail_rate_escalate` / `fail_rate_deescalate` | 0.25 / 0.08 | tolerate more cap hits | react sooner |
| `max_history_per_agent` | 400 | longer memory ceiling | faster forgetting regardless of gamma |
| `apply_compact_window` | true | (boolean) apply writes the learned raise-only `autoCompactWindow` | false: report it only |

## 8. Freezing, manual overrides, rollback

| Goal | Do this | Note |
|---|---|---|
| Review before anything lands | `"auto_apply": false` or `"apply_on": "never"` | Nothing is applied automatically; recommendations still update |
| Apply right after each session | `"apply_on": "session_end"` | The detached `learn run` applies after update |
| Stop learning at session end | `"enabled": false` | Stops the SessionEnd run and all applying. The SubagentStop hook still ingests and updates recommendations every 30 min |
| Hand-set one agent permanently | `bin/stack agents set A maxTurns=N` and pin N in bounds (or `learn: false`) | Without a pin the next update moves it again (and the new value becomes the prior centre) |
| Temporary experiment | `python3 "$T" snapshot`, then `bin/stack agents set A effort=E maxTurns=N` (or the env var ADVANCED_MODEL / MEDIUM_MODEL / LOW_MODEL to trial a model id for a whole tier); revert from the snapshot afterwards | Per-call overrides are stripped by the pre-agent hook; experiment runs are ingested like any run |
| Roll back the last change | `python3 "$T" revert-plan --agent A` then run the printed `bin/stack agents set` and pin | `changes.jsonl` stores new values only; the value before the first learned change comes from a snapshot or `git log -p -- <agent file>` |
| Reset an agent's evidence | Move, never delete: `mkdir -p "$CLAUDE_STACK_DATA/obs.archive"` and move the affected session files | Obs files are per session and contain all agents of that session; filtering one agent out means rewriting the JSON (keep the original) |

## 9. Explaining a change (template)

```text
rust-expert maxTurns 80 -> 152, effort high -> xhigh (applied 2026-10-19 12:27).
Evidence: 14 runs, gamma 1.0 (no drift), 3 of 14 hit the 80-turn cap.
Tool-round posterior: median 43, q95 132.1; 132.1 x 1.15 = 151.9 -> 152 (within the x2 step limit 160).
Effort: 69% of runs fit high or lower, 98% fit xhigh or lower; smallest level covering 80% is xhigh.
P(cap hit) = 4/19 = 0.21 (below the 0.25 escalation threshold, so the move is from token volume, not failures).
Risk: higher cost per run (xhigh reasons longer). Rollback: bin/stack agents set rust-expert maxTurns=80 effort=high + pin.
```

The full derivation of these numbers is in [learner math](references/learner-math.md).

## 10. Never

- Never edit `recommendations.json`, `budgets.json` or `obs/*.json` by hand to steer results.
- Never delete `changes.jsonl`; it is the only audit trail of automatic edits.
- Never read or print `~/.claude/stack.env`; tuning needs no keys.
- Never widen bounds to "make a warning go away" without reading capped transcripts.
- Never apply globally while `recommendations.json` comes from a filtered update.
