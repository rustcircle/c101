# Learner data files

Location: `$CLAUDE_STACK_DATA`, default `~/.claude/stack-data`. Outside the repo, never committed.
Read with `jq`; never edit by hand to steer recommendations.

| Path | Writer | Content |
|---|---|---|
| `obs/<session-id>.json` | `learn ingest` (idempotent: rewritten per session) | `{agent_id: record}` for the main thread and every subagent of one session |
| `recommendations.json` | `learn update` | `{generated_at, agents: {name: recommendation}}` |
| `budgets.json` | `learn update` | `{name: {max_output_tokens, recommend_1m_context, autoCompactWindow?, tokens}, "_global": {n_sessions, n_prompts, session, prompt, recommended, applied}}` |
| `history.jsonl` | `learn run` (SessionEnd) | One line per session (re-recording replaces it): `session_id`, `recorded_at`, `started_at`, `project`, `runs`, `tokens_total`, `agents: {type: {runs, capped, tool_errors, tokens_total, output_tokens, duration_s, effort, models, turns_median/max, tool_rounds_median/max, maxTurns, effort_setting}}`; read by `learn history` |
| `changes.jsonl` | `learn apply` (session-start hook, `learn start`) | One line per applied frontmatter edit |
| `spawns/<session-id>.jsonl` | `pre-agent` hook | `{tool_use_id, agent_type, limit_max_turns, ts}` per spawn: the maxTurns the agent file said at the spawn (pruned after 14 days) |
| `stops/<session-id>.jsonl` | `subagent-stop` hook | `{agent_id, agent_type, effort, ts}` per finished subagent; the effort in effect, authoritative over the transcript |
| `sessions/<session-id>.json` | `pre-agent` hook | Spawn counts: `spawns`, `by_depth`, `by_type`, `max_depth_seen` |
| `last_ingest`, `last_update` | `subagent-stop` hook | Timestamps (mtime) for debounce and the 30-min update interval |
| `learn.lock` | `subagent-stop`, `session-start` hooks, `learn run` | flock; a held lock makes the hooks skip, `learn run` waits |
| `learn.log` | `session-end` hook (detached run) | stdout/stderr of `learn run` |
| `hook-errors.log` | any hook | Exceptions swallowed by fail-open hooks |

## Observation record (one agent run)

| Field | Meaning |
|---|---|
| `agent_type` | `meta.json` agentType for subagents; `$CLAUDE_STACK_MAIN_AGENT` or `main` for the main thread; `unknown` if no meta (skipped by update) |
| `agent_id`, `session_id`, `transcript` | Identity and the transcript path (open it to see what the run did) |
| `tool_rounds` | Responses that called at least one tool (parallel calls in one response = one round); the quantity `maxTurns` limits and the learner models |
| `turns` | Unique assistant `message.id`s (Claude Code writes one line per content block); raw response count, diagnostic |
| `output_tokens`, `output_max_turn`, `output_estimated` | Total and largest single-turn output; estimated from content length (3.6 chars/token) when the line carried a stream-start usage snapshot |
| `thinking_tokens` | From `usage.output_tokens_details.thinking_tokens` when present |
| `ctx_peak`, `input_tokens_total`, `tokens_total` | Max per-turn context (input + cache read + cache creation); sums |
| `tool_calls`, `tool_errors`, `agent_spawns` | Diagnostics; `agent_spawns` maps child agent type to count |
| `effort`, `effort_transcript`, `model` | Effort in effect (SubagentStop payload when recorded, else the transcript's most common value, which is then also kept in `effort_transcript`); most common model |
| `duration_s`, `started_at` | Wall time; ordering for the forgetting weights |
| `spawn_depth`, `workflow`, `description`, `source` | Context; `workflow` is set when the run belongs to a saved workflow |
| `limit_max_turns`, `max_turns_hit`, `capped` | Limit in force at ingest; marker seen; `capped` = marker or tool_rounds >= limit |

Caveat: `limit_max_turns` is the agent file's value at ingest time, not at run time. Re-ingesting
old sessions after the learner raised a cap can turn old capped runs into uncapped ones (tool_rounds <
new limit) unless the transcript contains the max-turns marker. Prefer `--since-days` windows for
routine ingests; use `--all` after first install or after deleting obs files.

## Useful queries

```bash
D="${CLAUDE_STACK_DATA:-$HOME/.claude/stack-data}"
# runs per agent type
jq -r '.[] | .agent_type' "$D"/obs/*.json | sort | uniq -c | sort -rn | head -30
# capped runs of one agent with their transcripts
jq -r '.[] | select(.agent_type=="rust-expert" and .capped) | "\(.tool_rounds // .turns)\t\(.transcript)"' "$D"/obs/*.json
# share of estimated output tokens (high share = effort bands less reliable)
jq -s '[.[] | .[] | select(.agent_type=="rust-expert")] | (map(select(.output_estimated)) | length) / length' "$D"/obs/*.json
# runs whose effort differs from the current frontmatter (frontmatter changed during the window)
jq -r '.[] | select(.agent_type=="rust-expert") | .effort' "$D"/obs/*.json | sort | uniq -c
# latest recommendation for one agent
jq '.agents["rust-expert"] | {n, window, turns, maxTurns, effort: (.effort | {current, recommended, reason, p_fail_mean}), budget}' "$D/recommendations.json"
# last 10 applied changes
tail -n 10 "$D/changes.jsonl" | jq -c '{agent, updates, n_eff, reasons}'
# hook failures in the last day
tail -n 20 "$D/hook-errors.log"
```

## changes.jsonl line

```json
{"agent": "rust-expert", "path": "/abs/.claude/agents/experts/rust-expert.md",
 "updates": {"maxTurns": "156", "effort": "xhigh"}, "ts": 1760869620.1,
 "reasons": {"maxTurns": "q95 of predictive x 1.15 margin", "effort": "smallest band covering 80% of runs"},
 "n_eff": 14.0}
```

Only new values are stored. The previous value is the previous line for the same agent and key,
or, before the first learned change, the snapshot / version-control history of the agent file.
