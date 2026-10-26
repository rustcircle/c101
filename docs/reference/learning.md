# Bayesian self-tuning

After every session the stack learns, per agent type, how many tool rounds (`maxTurns`), how much
reasoning (`effort`) and how much context and output each agent needs. At the start of the next session it
moves the agent's frontmatter toward what the evidence supports. Every move is bounded, uses hysteresis and is recorded
in an audit log. The learner is stdlib-only and Python 3.9 compatible, so it runs inside a hook even
on the system `python3` fallback of `bin/_pyenv.sh`.

| File | Role |
|---|---|
| `stack/learn/ingest.py` | Turns Claude Code transcripts into one observation record per agent run |
| `stack/learn/bayes.py` | Estimators: `LogNormalGrid` (censored log-normal, grid posterior), `BetaRate`, `DirichletCategories`, `select_forgetting` |
| `stack/learn/model.py` | `recommend_agent()`: from observations to `maxTurns`, `effort`, token windows and budget hints for one agent |
| `stack/learn/engine.py` | The ingest, update, record and apply pipeline (`run_after_session`, `start_of_session`, `history`), storage, and the global token-budget learner `global_budgets()` |
| `stack/hooks.py` | `subagent-stop`, `session-end` and `session-start` hook handlers that drive the pipeline |
| `config/learning.json` | All tunables and per-agent bounds (see [Learner configuration reference](#learner-configuration-reference)) |
| `docs/LEARNING.md` | Short design note |

## Data flow

```
Claude Code event            handler (stack/hooks.py)                 ~/.claude/stack-data/
-----------------            ------------------------                 ---------------------
PreToolUse(Agent|Task) ----> pre-agent ------ budget.session_usage --> sessions/<sid>.usage.json --+
UserPromptSubmit ----------> prompt-submit -/                                                       |
                                                                                                    |
SubagentStop (async) ------> subagent-stop -- _record_stop ----------> stops/<sid>.jsonl --+        |
                              | flock learn.lock (non-blocking)                             |        |
                              | skip if last_ingest < 60 s old                              v        |
                              +-- engine.ingest_transcript(<sid>.jsonl) <-- transcripts + stop events |
                              |        +-------------------------------> obs/<sid>.json ---+         |
                              +-- if last_update > 30 min old: update (no apply)           |         |
                                                                                           v         v
SessionEnd ----------------> session-end -- detached `stack learn run`:  engine.update --------------+
                                            flock learn.lock (waits)       |-> recommendations.json
                                            ingest + update + record       |-> budgets.json (+ _global)
                                                                         engine.record_session
                                                                           |-> history.jsonl
SessionStart (next) -------> session-start -- flock learn.lock (non-blocking)
                                              engine.start_of_session -> engine.apply
                                                                           |-> .claude/agents/**/<agent>.md
                                                                           |-> changes.jsonl
```

There are four steps:

1. **Ingest** parses one session's transcripts and writes `obs/<session-id>.json`.
2. **Update** fits the models for every agent type over all stored observations and writes
   `recommendations.json` and `budgets.json`.
3. **Record** (`engine.record_session`, SessionEnd only) writes the session's per-agent summary line to
   `history.jsonl`.
4. **Apply** writes the recommended values into the frontmatter of managed agents and appends each
   change to `changes.jsonl`. With the default `apply_on: "session_end"` it runs in the detached
   `learn run` when a session ends. Claude Code loads agent definitions at session start and re-reads a changed file from the next turn once its file watcher
   is running, so a write at SessionEnd is on disk before the next session loads and reaches a running session on its next
   turn, while a write at SessionStart (the legacy `apply_on: "session_start"`, or the catch-up described under Triggers) can
   land before the watcher is up and then wait a session. See [docs/LEARNING.md](../LEARNING.md#when-learned-values-take-effect).

### Triggers

| Trigger | What runs | Guards |
|---|---|---|
| `SubagentStop` (`.claude/settings.json`: `"async": true`, `"timeout": 120`) | `_record_stop` appends the stop event. Then the session is re-ingested. At most every `midsession_update_minutes` the hook also runs `update`; it never applies ([subagent-stop](hooks.md#subagent-stop-telemetry-and-mid-session-learning)). | Non-blocking `flock` on `learn.lock` (a running ingest will see this agent too); ingest skipped while `last_ingest` is younger than `ingest_debounce_seconds` (60), because a 500-agent workflow would otherwise re-parse the session 500 times and SessionEnd always does a final full ingest; update only when `last_update` is older than `midsession_update_minutes` (30). Both keys live in `config/policy.json`. |
| `SessionEnd` (`"timeout": 5`) | `_detach` starts `python -m stack.cli learn run --transcript <path>` with `start_new_session=True`: ingest, update, `record_session` and, when `apply_on` is `"session_end"` (the default), `apply`. Its output goes to `learn.log` ([session-end](hooks.md#session-end-detached-learner)). | Detached, because SessionEnd hooks share a 1.5 s budget. `learn run` waits for `learn.lock`, and returns `{"skipped": "learning disabled"}` when `enabled` is false. |
| `bin/stack-sdk run` | The SDK has no SessionEnd callback. After the query ends, `_learn_after` calls `engine.run_after_session()` on `<projects root>/<project_key_for_directory(cwd)>/<session_id>.jsonl`. SDK `SubagentStop` callbacks run the same `subagent-stop` handler in-process through `asyncio.to_thread`. | Errors are printed as `learning skipped: ...` and never fail the run. |
| `SessionStart` | `_apply_learned` runs `engine.apply()` as a catch-up when `apply_on` is `"session_end"` or `"session_start"`; `apply()` returns only writes that changed a file, so after a SessionEnd apply it is silent. When it did write it adds `Caught up pending learned values (Claude Code reads agent files again from the next turn; a write this early in startup may only reach the next session): <agent> maxTurns=..,effort=..; ...` to the session context. Otherwise it adds `Recently self-tuned: <agent> k=v,...; ...` (the last 5 lines of `changes.jsonl`) ([session-start](hooks.md#session-start-status-line)). | Non-blocking `flock` on `learn.lock`: if a previous session's SessionEnd run still holds it, nothing is applied and the holder applies. Errors go to `hook-errors.log` and never block the start. The recent note only when `changes.jsonl` was modified in the last 7 days. |

Every handler fails open: exceptions are appended to `hook-errors.log`, and the hook exits 0.

`enabled: false` makes `learn run` (the SessionEnd path and the SDK runner) a no-op and disables
applying; the SubagentStop path still ingests and updates recommendations. To keep frontmatter frozen
completely, set `"auto_apply": false` or `"apply_on": "never"` (`engine.apply_on()` returns `"never"` when
`enabled` or `auto_apply` is false). The SDK runner has no SessionStart hook: it applies pending values itself before starting the CLI (in force for that run), and
applies again after the run when `apply_on` is `"session_end"`.

### Files in `~/.claude/stack-data/`

The data directory is `$CLAUDE_STACK_DATA` (default `~/.claude/stack-data`). It is created by
`stack install`, or on first use by `paths.data_dir()`, and lives outside the repository. Transcripts
are read from `$CLAUDE_PROJECTS_ROOT` (default `~/.claude/projects`).

| Path | Written by | Contents |
|---|---|---|
| `obs/<session-id>.json` | `engine.ingest_transcript` | `{agent_id: record}` for the main thread (key `"main"`) and every subagent of one session, using the fields [below](#what-is-observed-per-run). The whole file is rewritten on every ingest, so re-ingesting is idempotent. |
| `stops/<session-id>.jsonl` | `hooks._record_stop` | One line per SubagentStop: `{"agent_id", "agent_type", "effort", "stop_reason", "limit_max_turns", "limit_basis", "ts"}`. `effort` is the level in effect, taken from the payload's `effort.level` or a bare string. `stop_reason` is whatever `stop_reason`/`subtype`/`reason` the payload carries (else null). `limit_max_turns` is the maxTurns in force with its basis: `spawn_record` (the pre-agent record found through the agent's `toolUseId`) or `stop_frontmatter` (the file at stop time). |
| `spawns/<session-id>.jsonl` | `hooks._record_spawn` (pre-agent) | One line per Agent spawn: `{"tool_use_id", "agent_type", "limit_max_turns", "ts"}`, the agent file's maxTurns at that moment. Pruned after 14 days at SessionEnd. |
| `recommendations.json` | `engine.update` | `{"generated_at", "agents": {name: recommendation}, "global": global_budgets()}`. Each recommendation holds `n`, `current`, `window`, `turns`, `maxTurns`, `effort`, `tokens`, `budget`, `status`, `managed` and `path`. |
| `budgets.json` | `engine.update` | `{name: {max_output_tokens, recommend_1m_context, autoCompactWindow?, tokens}}` plus `"_global"`, a copy of the global block. `budget.limits()` reads `_global.applied`. |
| `history.jsonl` | `engine.record_session` (SessionEnd `learn run`) | One JSON line per session; re-recording a session replaces its line: `{"session_id", "recorded_at", "started_at", "project"` (transcript directory name)`, "runs", "tokens_total", "agents": {agent_type: {runs, capped, tool_errors, tokens_total, output_tokens, duration_s, effort: {level: count}, models, turns_median, turns_max, tool_rounds_median, tool_rounds_max, maxTurns: {current, recommended}, effort_setting: {current, recommended}}}}`. Read by `learn history`. |
| `changes.jsonl` | `engine.apply` | Audit log, one line per agent changed: `{"agent", "path", "updates", "ts", "reasons": {"maxTurns", "effort"}, "n_eff"}`. |
| `sessions/<session-id>.usage.json` (+ `.lock`) | `budget.session_usage` (from the `pre-agent` and `prompt-submit` hooks) | Incremental token totals: `files` holds per-transcript `{offset, prompt, mid, out, chars}`, `session` holds `{input, cache_creation, cache_read, output}`, and `prompts` holds `{promptId: totals}`. This is the input to the global budget learner. |
| `sessions/<session-id>.json` (+ `.lock`) | `pre-agent` (depth guard) | Spawn counter: `spawns`, `by_depth`, `by_type`, `max_depth_seen`, `updated_at` (read by `bin/stack depth`). The learner does not read this file. |
| `learn.lock`, `last_ingest`, `last_update` | `subagent-stop` (lock also `learn run`, `session-start`) | The lock file and two empty stamp files. Only their mtimes are used. |
| `learn.log` | detached `learn run` | stdout and stderr of the SessionEnd learning run. |
| `hook-errors.log` | all hooks | Timestamped exceptions that the hooks swallowed. |

All JSON outputs are written atomically: the file is written to `<file>.tmp`, then renamed with
`os.replace`. Readers such as the `pre-agent` hook therefore never see a partial file.

## What is observed per run

Transcript layout, as written by Claude Code 2.1.x:

```
~/.claude/projects/<project-slug>/<session-id>.jsonl                          main thread
~/.claude/projects/<project-slug>/<session-id>/subagents/**/agent-<id>.jsonl   one subagent run
~/.claude/projects/<project-slug>/<session-id>/subagents/**/agent-<id>.meta.json
    {"agentType": "...", "description": "...", "spawnDepth": 1, ...}
```

`ingest.summarize_transcript()` aggregates one file into one record. `ingest_session()` adds identity
fields. `engine.ingest_transcript()` then adds the cap, effort and timestamp fields.

| Field | How it is measured |
|---|---|
| `agent_type` | From `meta.agentType` for subagents, or `"unknown"` if missing. The main thread uses `$CLAUDE_STACK_MAIN_AGENT`, falling back to `"main"`. `bin/claude-stack` exports `CLAUDE_STACK_MAIN_AGENT=delegator`, so main-thread runs teach the `delegator` agent. |
| `agent_id`, `session_id` | From the rows' `agentId` and `sessionId`. The fallback for `agent_id` is the `agent-<id>` file name. The main thread always uses `"main"`. |
| `source`, `spawn_depth`, `description`, `workflow`, `transcript` | `"main"` or `"subagent"`, then the native `spawnDepth` (0 for main), the meta `description`, the workflow name (the path segment after `subagents/workflows/`), and the file path. |
| `turns` | Number of unique API responses: distinct `message.id`, falling back to `requestId`, then `uuid`. Claude Code writes one JSONL line per content block, and all lines of a response share the same id and the same `usage` snapshot. |
| `tool_rounds` | Responses that contain at least one `tool_use` block. This is the unit `maxTurns` counts: parallel tool calls in one response are one round, and a final text-only reply is not a round. |
| `output_tokens` | Sum over responses of the per-response output. Thinking tokens are included. See [output estimation](#output-estimation). |
| `output_max_turn` | The largest single-response output. It drives the max-output-tokens window. |
| `output_estimated` | True when at least one response used the content-length estimate. |
| `thinking_tokens` | Sum of `usage.output_tokens_details.thinking_tokens`. |
| `ctx_peak` | `max` over responses of `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`: the largest context window the agent actually used. |
| `input_tokens_total`, `tokens_total` | Sum of that per-response input side, and `input_tokens_total + output_tokens`. |
| `tool_calls`, `tool_errors` | Count of `tool_use` blocks, and count of user-side `tool_result` blocks with `is_error: true`. |
| `agent_spawns` | `{subagent_type: count}` over `Agent` and `Task` tool calls. The default type is `general-purpose`. |
| `model` | Mode of `message.model`, counted once per response. |
| `effort`, `effort_transcript` | See [effort](#effort-from-subagentstop-payloads). |
| `started_at`, `duration_s` | First timestamp, and last minus first. Observations are ordered by `started_at`. |
| `max_turns_hit` | A `system` row whose JSON content, lowercased, contains `max turns`, `maxturns` or `max_turns`, or any row with `subtype: "error_max_turns"`. |
| `limit_max_turns` | The agent's `maxTurns` frontmatter at ingest time, or `null`. |
| `capped` | `max_turns_hit` or `tool_rounds >= limit_max_turns`. The run is treated as a right-censored observation. |
| `ingested_at` | Wall-clock time of the ingest. |

`engine.load_observations()` skips records whose `agent_type` is empty or `"unknown"`. Claude Code's
internal agents, such as prompt suggestions and `/btw`, report an empty type. `update()` keeps the
latest `max_history_per_agent` (400) records per agent, sorted by `started_at`.

### Output estimation

Main-thread lines carry the final usage, with `stop_reason` set. Sidechain (subagent) lines are often
written from the stream's `message_start` snapshot. In those lines `stop_reason` is `null` and
`output_tokens` is a placeholder of a few tokens. For each response, ingest keeps the `usage`
snapshot with the largest `output_tokens` and the last non-null `stop_reason`, and sums content
characters over all its blocks:

```
chars    = len(text) + len(thinking) + len(json.dumps(tool_use.input, separators=(",", ":")))
estimate = ceil(chars / 3.6)                        # CHARS_PER_TOKEN = 3.6
turn_out = estimate   if stop_reason is None and estimate > reported_output_tokens
           reported   otherwise
```

The input-side counts are complete in both cases, so `ctx_peak` and `tokens_total` never need
estimation. Redacted thinking has no visible characters, so estimated outputs lean low. This is why
the record carries `output_estimated`.

### Effort from SubagentStop payloads

The per-line `effort` in a transcript reflects the session level, not the level the subagent
actually ran at. Only the SubagentStop payload carries the level in effect. The `subagent-stop` hook
appends that level to `stops/<sid>.jsonl`. At ingest, the last stop event for each `agent_id`
overrides `effort`, and the transcript value is kept as `effort_transcript`. The main thread has no
stop event, so it keeps the transcript mode. The effort model does not use `effort` as an input,
because bands come from output tokens. The field is reported as `effort.observed` (the mode) for
comparison.

### Censoring

A run that hits `maxTurns` does not reveal how many rounds it needed, only that it needed at least
that many. Such runs are flagged `capped` and enter the turns model as right-censored observations,
through survival terms instead of density terms. If an agent keeps hitting a cap that is too low,
treating those runs as "needed exactly N" would lock the cap in place. As survival terms they push
the posterior upward. The cap check compares `tool_rounds` against the limit in force at ingest time.
A `capped` run also counts as a failure in the effort model.

## Models

`recommend_agent(name, obs, current, cfg, bounds)` in `stack/learn/model.py` runs the following
steps for each agent type that has at least one observation. With zero observations it returns
`status: "no-data"`.

### `maxTurns`: censored log-normal with a grid posterior

**Likelihood.** Let `y = ln(max(tool_rounds, 1))`. The model is `y ~ Normal(mu, sigma)`, so tool
rounds are log-normal. This fits a positive, right-skewed count whose spread scales with its size.

**Prior** (`LogNormalPrior.around`):

```
typical  = current_maxTurns / prior_limit_ratio        # 3.0; prior_turns_typical = 12 if no maxTurns
mu       ~ Normal(ln(max(typical, 1)), ln(prior_spread))   # prior_spread = 2.5 -> sd 0.916
ln sigma ~ Normal(ln 0.6, 0.6)                          # sigma_med = 0.6, sigma_sd = 0.6
```

The hand-set limit is read as roughly three times a typical run. One prior standard deviation is a
factor of 2.5 either way. For example, `maxTurns: 40` gives a prior median of 13.3 rounds, with a
1-sd range of 5.3 to 33.

**Grid.** `mu` takes 48 points, linearly spaced over `[m0 - 4 s0, m0 + 4 s0]`. That range is widened
to cover `[min(y) - 1.5, max(y) + 2.5]`. The upper side gets more room because censored points push
mass upward. `sigma` takes 28 points, log-spaced over `[0.05, 2.5]`. Because the `sigma` grid is
log-spaced, the prior on `ln sigma` needs no Jacobian.

**Posterior.** Each cell's posterior is computed exactly from weighted observations. `w_i` are the
forgetting weights described in the next section.

```
log p(mu, sigma | D) = log prior(mu, sigma)
    - W ln sigma - (S2 - 2 mu S1 + mu^2 W) / (2 sigma^2)          # exact runs, sufficient statistics
    + sum_{j capped} w_j * ln(1 - Phi((y_j - mu) / sigma))         # censored runs: P(Y >= y_j)

W = sum w_i,   S1 = sum w_i y_i,   S2 = sum w_i y_i^2              # over uncensored runs
```

The cells are normalised with log-sum-exp. `ln(1 - Phi(z))` (`norm_logsf`) uses `erfc` for `z < 5`
and a Mills-ratio expansion beyond that, so far-tail censored points stay finite.

**Predictive.** The posterior predictive is a mixture of log-normals over the grid cells:
`F(x) = sum_k p_k Phi((ln x - mu_k) / sigma_k)`, skipping cells with log weight below -30. Quantiles
come from bisection on `ln x` (80 iterations, tolerance 1e-4). `recommendations.json` reports
`turns.q50`, `q90`, `q95`, `q99`, `n_eff` (the sum of weights) and `n_capped`.

**Recommendation.** The steps run in this order:

```
target = ceil(Q_pred(turns_quantile = 0.95) * turns_margin (1.15))
target = clamp(target, floor(cur / max_step_factor), ceil(cur * max_step_factor))   # 2.0: at most x2 or /2
target = clamp(target, bounds.maxTurns)                                            # per agent, default [5, 1000]
apply only if cur is None or |target - cur| >= max(2, min_change_frac * cur)        # 0.1: hysteresis
requires n_eff >= min_obs_turns (3)
```

The reasons recorded are `"q95 of predictive x 1.15 margin"`, `"within hysteresis band"` or
`"insufficient data"`. The step limit keeps a burst of unusual runs from moving the limit far in one
update. The hysteresis band keeps a converged limit from twitching by one or two rounds after every
session.

Worked examples, computed with the shipped config at `maxTurns: 40`:

| Evidence (10 runs) | Predictive q95 | `ceil(q95 x 1.15)` | After step clamp [20, 80] | Result |
|---|---|---|---|---|
| 9-16 rounds, none capped | 18.3 | 22 | 22 | 40 -> 22 (change 18 >= 4) |
| Same, but 4 runs capped at 40 (censored) | 139.1 | 160 | 80 | 40 -> 80 |
| Same 4 runs treated as exactly 40 (no censoring) | 61.7 | 71 | 71 | 40 -> 71 |

### Data window: forgetting factor chosen by prequential score

Observations are weighted by age in runs, oldest first. The newest run always has weight 1:

```
w_i = gamma^(n - 1 - i)          effective_runs = (1 - gamma^n) / (1 - gamma)     (n if gamma = 1)
```

`select_forgetting()` chooses `gamma` per agent from `DEFAULT_GAMMAS = (1.0, 0.99, 0.97, 0.94, 0.9, 0.85)`
using the prequential (one-step-ahead) log score of the turns series:

1. If there are fewer than `min_points_for_window` (8) runs, use `gamma = 1.0` and record no scores.
2. For each `gamma` and each of the last 12 runs `t` (`holdout = 12`), fit a `LogNormalGrid` (a
   coarser 32 x 20 grid) on runs `0..t-1` with that `gamma`'s weights. Score run `t` by its
   predictive log density, or by its predictive log survival `ln P(Y >= y_t)` if it was capped. Both
   are proper scores for what was actually seen. Sum the 12 scores.
3. **Tolerance rule:** among the gammas whose score is within `tolerance = 1.5` nats of the best,
   choose the largest gamma, which has the longest memory.

Prequential scores are noisy, so the tolerance rule acts like a one-standard-error rule. The window
shortens only when the evidence for drift is clear, for example after a prompt change, new callers or
a model change. A better score by itself is not enough. For example, the scores
`{0.85: -46.27, ..., 1.0: -46.51}` select `gamma = 1.0`, because every candidate is within 1.5 nats of
the best.

| gamma | 1.0 | 0.99 | 0.97 | 0.94 | 0.9 | 0.85 |
|---|---|---|---|---|---|---|
| Asymptotic effective runs `1/(1 - gamma)` | all (<= 400) | 100 | 33.3 | 16.7 | 10 | 6.7 |

The `gamma` chosen on the turns series also weights the effort counts, the failure rate and the token
windows. All models therefore use the same data window. `window` in `recommendations.json` holds
`gamma`, `effective_runs` and the score for each candidate.

### `effort`: Dirichlet over output-token bands

Each run falls into a band according to its total `output_tokens`, thinking included, using
`effort_bands_output_tokens = [4000, 16000, 48000, 120000]`:

| Level | `low` | `medium` | `high` | `xhigh` | `max` |
|---|---|---|---|---|---|
| Output tokens per run | `< 4k` | `4k - 16k` | `16k - 48k` | `48k - 120k` | `>= 120k` |

The model is a Dirichlet-multinomial over the five ordered levels.

- The prior is `alpha0 = effort_prior_alpha` (0.5) per level, plus `effort_prior_stickiness` (3.0) on
  the current level. When the current level is known, the prior holds 5.5 pseudo-counts in total.
- The posterior is `alpha = alpha0 + weighted band counts`, and the predictive is `p_k = alpha_k / sum(alpha)`.
- The candidate is the smallest level `c` with `sum_{k <= c} p_k >= effort_cover_mass` (0.8), via
  `smallest_covering`.

Stickiness makes the current level the default answer, so a level changes only when enough weighted
runs land elsewhere. Moving down one level from index `c` (`low = 0` ... `max = 4`) needs
`(0.5 c + n) / (5.5 + n) >= 0.8` with `n` weighted runs in lower bands. That gives
`n >= 22 - 2.5 c`:

| Step down | `medium -> low` | `high -> medium` | `xhigh -> high` | `max -> xhigh` |
|---|---|---|---|---|
| Weighted runs needed | 19.5 | 17 | 14.5 | 12 |

The total weight is capped near `1/(1 - gamma)`. At `gamma = 0.94` (16.7) neither `high -> medium`
nor `medium -> low` can happen, and at `gamma <= 0.9` no step down is possible. Shortening the window
therefore makes the learner conservative about lowering effort.

### Failure rate: Beta escalation and de-escalation

A run counts as a failure when it is `capped`, or when it carries a truthy `failed` field. The
ingester sets only `capped`. With `F` and `S` as the weighted failure and success counts:

```
P(fail) ~ Beta(fail_prior[0] + F, fail_prior[1] + S) = Beta(1 + F, 4 + S)     prior mean 0.2
E[P(fail)] = (1 + F) / (5 + F + S)
```

The decision logic, simplified from `model.py` and applied when `n_eff >= min_obs_effort` (5):

```python
idx = dirich.smallest_covering(cfg["effort_cover_mass"])
if fail_post.mean > cfg["fail_rate_escalate"]:                       # 0.25
    idx = max(idx, (ci if ci is not None else idx) + 1)                # escalate
elif ci is not None and idx < ci and fail_post.mean > cfg["fail_rate_deescalate"]:   # 0.08
    idx = ci                                                           # failures block de-escalation
if ci is not None:
    idx = clamp(idx, ci - 1, ci + 1)                                   # one level per update
idx = clamp(idx, bounds.effort)                                        # per agent, default [low, max]
```

These rules imply the following thresholds:

- **Escalate** when `3F > 1 + S`. For example, 3 capped runs out of 10 give `E = 4/15 = 0.27`, which
  moves effort up one level even if output tokens alone would not.
- **De-escalation is allowed** only when `S >= 7.5 + 11.5 F`. With no failures, that is about eight
  clean weighted runs.

Escalation is fast and de-escalation is slow on purpose. Under-provisioning costs failed work, while
over-provisioning costs only tokens. Running out of road (a cap) usually means the agent had to
reason more and needs more turns. The turns model raises `maxTurns` at the same time through
censoring. The recorded reasons are `escalate: P(fail)=..`, `hold: failures block de-escalation`,
`smallest band covering 80% of runs` or `insufficient data`.

`recommendations.json` also reports `effort.band_probs`, `p_fail_mean`, `p_fail_q90` and `observed`.
`p_fail_q90` is the Beta quantile, computed by bisection on the regularised incomplete beta function
using a Lentz continued fraction.

### Token windows

For each of `output_tokens`, `tokens_total`, `ctx_peak` and `output_max_turn`, the learner fits an
uncensored `LogNormalGrid` with the same forgetting weights. Zero values are dropped. The prior is
`LogNormalPrior.around(median of positive values, spread_factor = 4.0)`, so `mu ~ N(ln median, ln 4)`
and `sigma` has the same prior as the turns model. The windows are:

```
tokens.<metric> = {min: Q(0.05), median: Q(0.5), max: Q(0.95)}      # token_window_quantiles = [0.05, 0.95]
```

These windows need no minimum sample size because they are descriptive. They are written to
`budgets.json` together with two derived budget hints:

| Hint | Formula | Use |
|---|---|---|
| `max_output_tokens` | `clamp(1000 * ceil(Q95(output_max_turn) * 1.15 / 1000), 8000, 128000)` (`max_output_tokens_bounds`) | Value for `CLAUDE_CODE_MAX_OUTPUT_TOKENS` in headless runs of that agent. Report only. |
| `recommend_1m_context` | `Q95(ctx_peak) > context_window_tokens * context_pressure` (`200000 * 0.8 = 160000`) | Flags agents whose context regularly approaches the standard window. Report only. |

### Raise-only `autoCompactWindow`

When an agent's context regularly reaches the compaction point, long tasks get compacted lossily
mid-flight. The learner trades tokens for quality and raises the window:

```
cur_win = frontmatter autoCompactWindow if it is an integer, else context_window_tokens (200000)
if n_eff >= min_obs_turns and Q95(ctx_peak) > cur_win * context_pressure:       # 0.8
    want = clamp(10000 * ceil(Q95(ctx_peak) * 1.15 / 10000), 100000, 1000000)
    if want > cur_win: budget.autoCompactWindow = want                            # never lowers
```

For example, `Q95(ctx_peak) = 304466` gives `ceil(350136 / 10000) * 10000 = 360000`. Apply writes the
value when `apply_compact_window` is true. The `100000..1000000` clamp matches the range that
`stack doctor` enforces.

### Global token budgets

`engine.global_budgets()` learns from all sessions combined, not per agent. It runs inside every
`stack learn update`, so also mid-session from `subagent-stop` and after `SessionEnd`. It covers the whole-tree
session and per-prompt limits in `config/policy.json` → `token_budget`. The configured values are
floors chosen for demanding work, so history can only raise them.

- **Input.** Each `sessions/*.usage.json` contributes one session total and one total per
  `promptId`. Prompts with id `"unknown"` are excluded. Usage is counted as
  `effective = input + cache_creation + output + cache_read_weight * cache_read`, with
  `cache_read_weight = 1.0`.
- **Fit.** A `LogNormalGrid` with prior `around(soft / 3, spread_factor = 3.0)`, no forgetting, over
  positive values. It needs at least 5 sessions for the session scope and at least 10 prompts for
  the prompt scope.
- **Recommendation**, for `key` in `global` (session) and `prompt`:

```
soft = min(max(cfg_soft, int(Q90 * 1.25)), 2 * cfg_soft)
max  = min(max(cfg_max,  int(Q95 * 1.5), soft), 2 * cfg_max)
```

  The results are `recommended.soft_<key>_tokens` and `recommended.max_<key>_tokens`. The
  `min_*_tokens` guarantees are never learned. They are stored in `budgets.json` under `_global`
  (`n_sessions`, `n_prompts`, per-scope `q50`/`q90`/`q95`, `recommended`, `applied`) and in
  `recommendations.json` under `global`.
- **Apply.** `token_budget.learn_global` is `"report"` in the shipped policy, which only records the
  numbers. With `"apply"`, `applied` copies `recommended`. `budget.limits()` then uses
  `max(configured, applied)` for each key, so the result is raise-only even if the configuration
  later changes.
- **Ceiling.** Learned values are computed from the configured values on every update and stored
  only in `budgets.json`, never written back to `policy.json`. The x2 cap is therefore an absolute
  ceiling of twice the configured limit, so one outlier session cannot open the budget without limit.

Example: 11 prompts with `Q90 = 556.3M` and `Q95 = 1.024B` give `soft_prompt_tokens = min(max(300M, 695.4M), 600M) = 600M`
and `max_prompt_tokens = min(max(400M, 1.536B, 600M), 800M) = 800M`.

## Applying changes

`engine.apply(dry_run=False, only=None)` reads `recommendations.json` and changes an agent only when
all of the following hold:

- The recommendation has `managed: true`. This requires an agent file found by
  `paths.find_agent_file`, which searches `$CLAUDE_PROJECT_DIR/.claude/agents`, then the repository's
  `.claude/agents`, then `~/.claude/agents`, and it requires that the agent's bounds do not set
  `"learn": false`. Built-in types such as `general-purpose`, and `main`, are reported but never
  written.
- `status` is `"ok"` and `path` is set.
- At least one value differs from the current one: `maxTurns` (recommended is set and differs from
  current), `effort` (a valid level that differs from current), or `autoCompactWindow` (present in
  `budget` and `apply_compact_window` is true).

All guard rails are applied in the model, before apply sees a value:

| Guard | `maxTurns` | `effort` | `autoCompactWindow` |
|---|---|---|---|
| Minimum evidence | `n_eff >= 3` | `n_eff >= 5` | `n_eff >= 3` |
| Bounds | per-agent `[lo, hi]`, default `[5, 1000]` | per-agent `[lo, hi]`, default `[low, max]` | configured `default_bounds.autoCompactWindow` `[600000, 1000000]` (floor = initial value, upper = tier `context_window`); the code still clamps to `[100000, 1000000]` |
| Step limit | x2 or /2 per update | one level per update | none (raise-only) |
| Hysteresis | `>= max(2, 10%)` change | stickiness 3.0 and failure hold | only when `want > current` |

Apply writes with `frontmatter.update_file()`. That function replaces only the lines of the changed
keys, appends missing keys and preserves comments, key order and the body byte for byte. The write
is atomic (`mkstemp` in the target directory, then `os.replace`) and goes to the symlink's target.
Installed agents in `~/.claude/agents/stack/` are symlinks into the repository, so every learned
change is an ordinary edit to a tracked file and shows up in `git diff .claude/agents`. Each change
is also appended to `changes.jsonl`:

```json
{"agent": "debugger", "path": "/Users/you/c101/.claude/agents/quality/debugger.md",
 "updates": {"maxTurns": "80", "effort": "xhigh"}, "ts": 1792416079.7,
 "reasons": {"maxTurns": "q95 of predictive x 1.15 margin", "effort": "escalate: P(fail)=0.33"}, "n_eff": 10.0}
```

The learned values take effect for the following reasons:

- The `pre-agent` hook strips any per-call `model` and `effort` from `Agent` and `Task` calls when
  `enforce_tiers` is true, so a caller cannot override them.
- `bin/claude-stack` reads the main agent's `effort` from its frontmatter at launch.
- `stack agents tiers` writes `effort` and `maxTurns` from `config/models.json` only when they are
  missing, or with `--reset-traits`. After that, the learner owns them.

Apply writes whatever the last `update` recommended: at SessionStart that is the previous session's
SessionEnd update. After a hand edit, run `update` before a manual `apply`.

When apply runs is set by `apply_on`:

| `apply_on` | Applied by | Notes |
|---|---|---|
| `"session_end"` (default) | the detached `learn run` after update and record; the session-start hook (or `bin/stack learn start`) only catches up on anything still pending | Values land on disk before the next session loads agent definitions, so they are in force from its first delegation, and a running session reads them from its next turn |
| `"session_start"` (legacy) | `session-start` hook, or `bin/stack learn start` | Written during startup, possibly before Claude Code's file watcher is running, so it can wait for the next session (evidence: deep-researcher ran at 45 turns while the file said 40) |
| `"never"` | only a manual `bin/stack learn apply` | Same as `auto_apply: false` or `enabled: false` |

## Learner configuration reference

`config/learning.json`:

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | `false` makes `learn run` (SessionEnd and SDK runner) a no-op and disables applying. |
| `auto_apply` | `true` | `false` disables automatic applying entirely (`apply_on()` returns `"never"`). |
| `apply_on` | `"session_end"` | When learned values are written: `"session_end"` (detached `learn run`; the session-start hook catches up on anything pending), `"session_start"` (legacy, lands a session later) or `"never"`. Mid-session updates never apply. |
| `turns_quantile` | `0.95` | Predictive quantile of tool rounds that `maxTurns` should cover. |
| `turns_margin` | `1.15` | Multiplier on that quantile. Also the margin for `max_output_tokens` and `autoCompactWindow`. |
| `prior_limit_ratio` | `3.0` | Prior typical run = current `maxTurns` / this. |
| `prior_turns_typical` | `12` | Prior typical run when the agent has no `maxTurns`. |
| `prior_spread` | `2.5` | 1-sd multiplicative spread of the prior on the typical run (`mu_sd = ln 2.5`). |
| `min_obs_turns` | `3` | Effective runs needed before `maxTurns` or `autoCompactWindow` is recommended. |
| `min_obs_effort` | `5` | Effective runs needed before `effort` is recommended. |
| `min_points_for_window` | `8` | Runs needed before `gamma` is selected; below this `gamma = 1.0`. |
| `min_change_frac` | `0.1` | Hysteresis: a `maxTurns` change must be at least `max(2, 0.1 x current)`. |
| `max_step_factor` | `2.0` | `maxTurns` moves at most x2 or /2 per update. |
| `effort_bands_output_tokens` | `[4000, 16000, 48000, 120000]` | Output-token thresholds between the five effort levels. |
| `effort_cover_mass` | `0.8` | Predictive mass the recommended level must cover. |
| `effort_prior_alpha` | `0.5` | Dirichlet pseudo-count per level. |
| `effort_prior_stickiness` | `3.0` | Extra pseudo-count on the current level. |
| `fail_prior` | `[1.0, 4.0]` | Beta prior `(a, b)` on the failure rate (mean 0.2). |
| `fail_rate_escalate` | `0.25` | `E[P(fail)]` above which effort rises one level. |
| `fail_rate_deescalate` | `0.08` | `E[P(fail)]` above which effort may not fall. |
| `token_window_quantiles` | `[0.05, 0.95]` | Quantiles reported as `min` and `max` of each token window. |
| `max_output_tokens_bounds` | `[8000, 128000]` | Clamp for the `max_output_tokens` hint. |
| `context_window_tokens` | `200000` | Standard context window, the default for `cur_win` and the `recommend_1m_context` threshold. |
| `context_pressure` | `0.8` | Fraction of the window that counts as pressure. |
| `max_history_per_agent` | `400` | Most recent runs per agent kept for fitting. |
| `default_bounds` | `{"maxTurns": [5, 1000], "effort": ["low", "max"], "learn": true}` | Bounds for every agent. |
| `agents` | see below | Per-agent overrides, merged key by key over `default_bounds`. |
| `apply_compact_window` | `true` | Whether apply writes the raise-only `autoCompactWindow`. |

Per-agent bounds shipped in `agents`. Agents without an entry use `default_bounds`:

| Agent | `maxTurns` | `effort` |
|---|---|---|
| `delegator` | [80, 1000] | [medium, max] |
| `orchestrator` | [60, 1000] | [medium, max] |
| `swarm-coordinator`, `mesh-router` | [40, 1000] | default |
| `mediator` | [40, 600] | [high, max] |
| `deep-researcher` | [40, 800] | default |
| `mathematics-expert` | [40, 600] | [high, max] |
| `cross-domain-synthesizer`, `architect` | default | [high, max] |
| `quick-researcher` | [8, 200] | [low, medium] |
| `source-summarizer`, `file-summarizer` | [6, 200] | [low, medium] |
| `general-chat` | [6, 200] | [low, high] |

Set `"learn": false` on an agent to freeze it: it is still reported but never written. Equal bounds,
such as `"effort": ["xhigh", "xhigh"]`, pin a value. `stack doctor` warns about bounds for agent
names that do not exist.

Related keys in `config/policy.json`: `ingest_debounce_seconds` (60), `midsession_update_minutes`
(30), and in `token_budget`: `learn_global` (`"report"` or `"apply"`), `cache_read_weight` (1.0),
`soft_global_tokens` (7.5B), `max_global_tokens` (10B), `soft_prompt_tokens` (300M) and
`max_prompt_tokens` (400M).

Fixed constants in code:

| Constant | Value | Where |
|---|---|---|
| Candidate gammas | `1.0, 0.99, 0.97, 0.94, 0.9, 0.85` | `bayes.DEFAULT_GAMMAS` |
| Prequential holdout, tolerance, grid | 12 runs, 1.5 nats, 32 x 20 | `bayes.prequential_score`, `select_forgetting` |
| Posterior grid | 48 `mu` x 28 `sigma`, `sigma` in [0.05, 2.5] | `LogNormalGrid` |
| `sigma` prior | median 0.6, log-sd 0.6 | `LogNormalPrior` |
| Characters per token | 3.6 | `ingest.CHARS_PER_TOKEN` |
| Token-window prior spread | 4.0 | `model.recommend_agent` |
| Global fit: minimum n, prior spread, quantile margins, cap | 5 sessions or 10 prompts, 3.0, Q90 x 1.25 and Q95 x 1.5, x2 | `engine.global_budgets` |

Environment variables: `CLAUDE_STACK_DATA` (data directory), `CLAUDE_PROJECTS_ROOT` (transcripts),
`CLAUDE_STACK_MAIN_AGENT` (agent type of the main thread) and `CLAUDE_PROJECT_DIR` (first location
searched for agent files).

## Learner commands

```bash
bin/stack learn ingest --transcript PATH      # one session (main thread + subagents) -> obs/<sid>.json
bin/stack learn ingest --all                  # every ~/.claude/projects/*/*.jsonl (also the default without --transcript)
bin/stack learn ingest --all --since-days 30  # only transcripts modified in the last 30 days
bin/stack learn update                        # refit all agents -> recommendations.json, budgets.json
bin/stack learn report                        # table: agent, n, gamma, maxTurns cur->rec, effort cur->rec, P(fail), output-token window
bin/stack learn report --agent NAME --json    # full recommendation record(s); --agent may repeat
bin/stack learn apply --dry-run [--agent NAME]   # "would set <agent> k=v  (maxTurns: reason; effort: reason)"
bin/stack learn apply [--agent NAME]          # write frontmatter, append changes.jsonl
bin/stack learn run --transcript PATH         # ingest + update + record history.jsonl, as the SessionEnd hook does (waits for learn.lock)
bin/stack learn start                         # apply pending values now, as the SessionStart hook does
bin/stack learn history [--agent NAME] [--since-days N] [--by week|day|session] [--json]
```

`history` reads `history.jsonl` and prints one row per agent and period (`--by week`, the default, uses
ISO weeks; `session` uses the first 8 characters of the session id): `sess` (sessions), `runs`, `turns50`
(median of the per-session median turns), `turnsmx` (max turns), `cap_rate` (capped / runs), `errors`
(tool errors), `maxTurns` and `effort` as current->recommended. `--json` dumps the rows, which also hold
`capped`, `tokens_total`, `tokens_per_run` and the effort level counts, for your own analysis.

`update --agent NAME` rewrites both `recommendations.json` and `budgets.json` with only the named
agents. To narrow the view, use a full `update` followed by `report --agent NAME` or
`apply --dry-run --agent NAME`. The table from `report` lists only agents with `status: "ok"`, while
`--json` returns every record. To review changes before they land, set `"auto_apply": false` (or
`"apply_on": "never"`) and use
`apply --dry-run`. To revert a change, use `git diff .claude/agents` and the matching
`changes.jsonl` line, then pin the agent's bounds or set `learn: false` so the next update does not
move it back. The `stack-tuner` agent (`.claude/agents/meta/stack-tuner.md`) runs this loop and
explains any change with the numbers behind it.
