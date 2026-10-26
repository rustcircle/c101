"""`bin/stack-sdk` — run and inspect the agent stack through the Claude Agent SDK.

    stack-sdk run "PROMPT" [--agent delegator] [--cwd DIR] [--permission-mode MODE]
                  [--agents-source auto|filesystem|programmatic] [--hooks auto|settings|python|none]
                  [--max-budget-usd X] [--task-budget TOKENS] [--model ID] [--effort LEVEL] [--json]
    stack-sdk agents [--json]        agents as AgentDefinitions (model/effort/maxTurns/MCP/skills, dropped keys)
    stack-sdk check [--cwd DIR]      build options for a placement and validate them (no API call)
    stack-sdk mcp                    MCP servers as resolved for out-of-repo sessions (no secrets)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

from stack import paths


def _cmd_agents(a) -> int:
    from .agents import load_all
    rows = []
    for name, ag in sorted(load_all().items()):
        d = ag.definition
        rows.append({"name": name, "group": ag.group, "model": d.model, "effort": d.effort, "maxTurns": d.maxTurns,
                     "mcpServers": [next(iter(e)) if isinstance(e, dict) else e for e in d.mcpServers or []], "skills": d.skills or [], "disallowedTools": d.disallowedTools,
                     "prompt_chars": len(d.prompt), "dropped": sorted(ag.dropped), "autoCompactWindow": ag.auto_compact_window})
    if a.json:
        print(json.dumps(rows, indent=2))
    else:
        for r in rows:
            print("%-28s %-18s %-7s %4s  mcp=%s dropped=%s" % (r["name"], r["model"], r["effort"], r["maxTurns"],
                                                             ",".join(r["mcpServers"]) or "-", ",".join(r["dropped"]) or "-"))
    return 0


def _cmd_check(a) -> int:
    from .options import StackRunConfig, build_options, describe
    problems = []
    for label, cwd in (("in-repo", paths.REPO), ("elsewhere", a.cwd or os.path.expanduser("~"))):
        try:
            opts = build_options(StackRunConfig(cwd=cwd))
            info = describe(opts)
            print("== %s (%s)" % (label, cwd))
            print(json.dumps({k: v for k, v in info.items() if k != "allowed_tools"}, indent=2))
        except Exception as exc:  # report every placement
            problems.append("%s: %r" % (label, exc))
    from .agents import load_all
    for name, ag in load_all().items():
        d = ag.definition
        if not d.description or not d.prompt:
            problems.append("%s: empty description or prompt" % name)
        problems.extend(ag.problems)
        if set(ag.dropped) - {"color"}:
            problems.append("%s: frontmatter keys the SDK cannot model: %s" % (name, sorted(set(ag.dropped) - {"color"})))
    for p in problems:
        print("PROBLEM " + p)
    print("%d problem(s)" % len(problems))
    return 1 if problems else 0


def _cmd_mcp(_a) -> int:
    from .mcp import load_mcp_servers
    print(json.dumps(load_mcp_servers(), indent=2))
    return 0


# Set by a parent Claude Code session (e.g. bin/stack-sdk run from Bash inside a session). The child CLI would
# adopt the parent's session id, so hooks would share its spawn count, token budget and taint state. In a
# claude.ai cloud session the remote/ingress variables also attach the child to the parent's remote session.
# Proxy and egress variables are left alone: the child still needs them to reach the API.
PARENT_SESSION_VARS = (
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_CODE_REMOTE_SDK_URL", "CLAUDE_CODE_REMOTE_SEND_KEEPALIVES",
    "SESSION_INGRESS_URL", "CLAUDE_SESSION_INGRESS_TOKEN_FILE", "CLAUDE_CODE_POST_FOR_SESSION_INGRESS_V2",
    "CLAUDE_CODE_SYNC_SESSION_REFS",
)


async def _run(a) -> int:
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, query

    from .options import StackRunConfig, build_options
    for var in PARENT_SESSION_VARS:
        os.environ.pop(var, None)
    _learn_before()
    cfg = StackRunConfig(cwd=a.cwd, main_agent=None if a.agent == "none" else a.agent, agents_source=a.agents_source,
                         hooks=a.hooks, permission_mode=a.permission_mode, model=a.model, effort=a.effort,
                         max_budget_usd=a.max_budget_usd, task_budget_tokens=a.task_budget,
                         foreground=not a.background, cli=a.cli)
    opts = build_options(cfg)
    result = None
    async for msg in query(prompt=a.prompt, options=opts):
        if isinstance(msg, AssistantMessage) and not a.json:
            for block in msg.content:
                if isinstance(block, TextBlock):
                    print(block.text, flush=True)
        elif isinstance(msg, ResultMessage):
            result = msg
    if result is None:
        print("no result message received", file=sys.stderr)
        return 1
    if result.subtype == "error_max_turns":
        print("stopped at max_turns: the run is partial; resume with the session id", file=sys.stderr)
    elif result.subtype == "error_max_budget_usd":
        print("stopped at max_budget_usd: usage totals may be incomplete", file=sys.stderr)
    summary = {"session_id": result.session_id, "subtype": result.subtype, "is_error": result.is_error,
               "terminal_reason": getattr(result, "terminal_reason", None), "num_turns": result.num_turns,
               "duration_ms": result.duration_ms, "total_cost_usd": result.total_cost_usd,
               "model_usage": {k: (v if isinstance(v, dict) else getattr(v, "__dict__", str(v)))
                               for k, v in (result.model_usage or {}).items()}}
    if a.json:
        summary["result"] = result.result
        print(json.dumps(summary, indent=2, default=str))
    else:
        print("\n-- %s | turns %s | $%s | session %s" % (result.subtype, result.num_turns,
                                                       result.total_cost_usd, result.session_id), file=sys.stderr)
    _learn_after(opts, result.session_id)
    return 1 if result.is_error else 0


def _learn_before() -> None:
    """SDK sessions may run without the SessionStart hook: apply pending learned values first.

    Unlike the hook, this runs before the CLI starts and loads agent definitions, so what it writes
    is in force for this run."""
    try:
        from stack import hooks
        for c in hooks._apply_learned():
            print("applied learned values: %s %s" % (c["agent"], " ".join("%s=%s" % kv for kv in c["updates"].items())),
                  file=sys.stderr)
    except Exception as exc:  # learning must never fail a run
        print("learning skipped: %r" % exc, file=sys.stderr)


def _learn_after(opts, session_id: str) -> None:
    """SDK hooks have no SessionEnd: feed the finished session to the learner here (idempotent)."""
    try:
        from claude_agent_sdk import project_key_for_directory

        from stack.learn import engine
        tp = os.path.join(paths.projects_root(), project_key_for_directory(str(opts.cwd)), "%s.jsonl" % session_id)
        if os.path.exists(tp):
            engine.run_after_session(tp)
    except Exception as exc:  # learning must never fail a run
        print("learning skipped: %r" % exc, file=sys.stderr)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="stack-sdk", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("prompt")
    r.add_argument("--agent", default="delegator", help="main-thread agent, or 'none'")
    r.add_argument("--cwd")
    r.add_argument("--agents-source", default="auto", choices=["auto", "filesystem", "programmatic"])
    r.add_argument("--hooks", default="auto", choices=["auto", "settings", "python", "none"])
    r.add_argument("--permission-mode", default="dontAsk",
                   choices=["default", "acceptEdits", "plan", "bypassPermissions", "dontAsk", "auto"])
    r.add_argument("--model", help="only with --agent none; must be a tier model")
    r.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], help="only with --agent none")
    r.add_argument("--max-budget-usd", type=float)
    r.add_argument("--task-budget", type=int, help="API task budget in tokens (default: max_prompt_tokens)")
    r.add_argument("--background", action="store_true", help="allow background subagents (default: foreground)")
    r.add_argument("--cli", default="system", choices=["system", "bundled"])
    r.add_argument("--json", action="store_true")
    ag = sub.add_parser("agents")
    ag.add_argument("--json", action="store_true")
    ch = sub.add_parser("check")
    ch.add_argument("--cwd")
    sub.add_parser("mcp")
    a = p.parse_args(argv)
    if a.cmd == "run":
        return asyncio.run(_run(a))
    return {"agents": _cmd_agents, "check": _cmd_check, "mcp": _cmd_mcp}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
