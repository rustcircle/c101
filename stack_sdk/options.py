"""Build ClaudeAgentOptions that run this agent stack under the Claude Agent SDK.

Two placements are supported:

* **in the repo** (``cwd`` inside this repository): the CLI discovers agents,
  skills, saved workflows, ``.mcp.json``, ``CLAUDE.md`` and the settings hooks
  from disk (``setting_sources`` includes ``project``); the main thread runs as
  the ``delegator`` via ``--agent``.
* **elsewhere** (any other project directory): agents are sent programmatically,
  MCP servers are resolved with absolute launcher paths, the stack's env
  (depth 8, concurrency) is passed explicitly, the hooks run as Python callbacks,
  and the delegator's prompt is appended to the Claude Code system prompt.

In both cases the main thread gets its tier model and effort, the per-prompt
token budget becomes the API task budget (a pacing hint; the hooks enforce the
hard limits), and skills are enabled.

Unattended-run defaults follow the SDK guidance: ``permission_mode='dontAsk'``
with an explicit allow-list and ``--permission-prompts none`` (no hangs, no retry
loops), the system ``claude`` CLI when present (parity with interactive sessions;
the SDK otherwise runs its bundled CLI), and foreground subagents
(``CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1``, ``CLAUDE_STACK_FOREGROUND=1``) so every
parent receives its children's results before continuing -- context usage over speed.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
from dataclasses import dataclass, field
from typing import Any, Literal

from claude_agent_sdk import ClaudeAgentOptions

from stack import budget, mcpcat, paths

from . import agents as agents_mod
from . import hooks as hooks_mod
from . import mcp as mcp_mod

UNATTENDED_TOOLS = ("Read", "Grep", "Glob", "Edit", "Write", "NotebookEdit", "Bash", "WebFetch", "WebSearch",
                    "TodoWrite", "Agent", "Workflow", "Skill", "ToolSearch", "Monitor", "TaskStop")

AgentsSource = Literal["auto", "filesystem", "programmatic"]
HooksMode = Literal["auto", "settings", "python", "none"]


@dataclass
class StackRunConfig:
    cwd: str | None = None
    main_agent: str | None = "delegator"
    agents_source: AgentsSource = "auto"
    hooks: HooksMode = "auto"
    setting_sources: list[str] | None = None
    permission_mode: str | None = "dontAsk"
    foreground: bool = True              # force subagents to return before the parent continues
    cli: Literal["system", "bundled"] = "system"
    model: str | None = None            # only for main_agent=None; must be an allowed tier model
    effort: str | None = None           # only for main_agent=None
    max_budget_usd: float | None = None
    task_budget_tokens: int | None = None   # default: max_prompt_tokens from config/policy.json
    max_turns: int | None = None
    extra_allowed_tools: list[str] = field(default_factory=list)
    extra_env: dict[str, str] = field(default_factory=dict)


def in_repo(cwd: str) -> bool:
    real = os.path.realpath(cwd)
    return real == paths.REPO or real.startswith(paths.REPO + os.sep)


def settings_json() -> dict:
    with open(os.path.join(paths.REPO, ".claude", "settings.json"), encoding="utf-8") as fh:
        return json.load(fh)


def build_options(cfg: StackRunConfig | None = None) -> ClaudeAgentOptions:
    cfg = cfg or StackRunConfig()
    cwd = os.path.abspath(cfg.cwd or os.getcwd())
    local = in_repo(cwd)
    source = cfg.agents_source if cfg.agents_source != "auto" else ("filesystem" if local else "programmatic")
    hooks_mode = cfg.hooks if cfg.hooks != "auto" else ("settings" if local else "python")
    settings = settings_json()

    loaded = agents_mod.load_all()
    main = loaded.get(cfg.main_agent) if cfg.main_agent else None
    if cfg.main_agent and not main:
        raise ValueError("unknown main agent %r" % cfg.main_agent)

    env = {k: str(v) for k, v in settings.get("env", {}).items()}
    env["CLAUDE_STACK_MAIN_AGENT"] = cfg.main_agent or "main"
    env["CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS"] = "0"   # never drop long workflows at exit
    if cfg.foreground:
        env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
        env["CLAUDE_STACK_FOREGROUND"] = "1"
    env.update(cfg.extra_env)

    # dontAsk denies anything not allowed here, so the list is the stack's whole capability set.
    allowed = [t for t in settings.get("permissions", {}).get("allow", []) if not t.startswith("Bash(")]
    allowed += list(UNATTENDED_TOOLS) + ["mcp__%s" % n for n in mcp_mod.project_servers()]
    allowed += ["mcp__%s" % n for n in mcpcat.catalog()]  # lazy servers inlined into agents
    allowed += list(cfg.extra_allowed_tools)

    kwargs: dict[str, Any] = dict(
        cwd=cwd,
        setting_sources=cfg.setting_sources or ["user", "project", "local"],
        skills="all",
        allowed_tools=sorted(set(allowed)),
        env=env,
        permission_mode=cfg.permission_mode,
        max_budget_usd=cfg.max_budget_usd,
        max_turns=cfg.max_turns,
        task_budget={"total": int(cfg.task_budget_tokens or budget.limits()["max_prompt_tokens"])},
    )
    extra_args: dict[str, str | None] = {}
    if cfg.permission_mode == "dontAsk":
        extra_args["permission-prompts"] = "none"
    if cfg.cli == "system" and shutil.which("claude"):
        kwargs["cli_path"] = shutil.which("claude")
    if not local:
        kwargs["mcp_servers"] = mcp_mod.load_mcp_servers()
        kwargs["add_dirs"] = [paths.REPO]  # skills/configs referenced by path stay readable
    if source == "programmatic":
        kwargs["agents"] = {n: a.definition if local else dataclasses.replace(a.definition, mcpServers=[
            {k: mcpcat.pin_repo(v, paths.REPO) for k, v in e.items()} if isinstance(e, dict) else e
            for e in a.definition.mcpServers]) if a.definition.mcpServers else a.definition
            for n, a in loaded.items()}
    if hooks_mode == "python":
        kwargs["hooks"] = hooks_mod.python_hooks()

    from stack import tiers
    allowed = tiers.allowed_models()
    # Same allowlist Claude Code enforces from settings; passed as SDK settings so it also holds
    # when this repo's project settings are not loaded.
    # availableModelsMatch is honoured only from managed settings (ignored with a warning in --settings)
    session_settings: dict[str, Any] = {"availableModels": allowed, "enforceAvailableModels": True}
    if source == "programmatic":
        # Programmatic AgentDefinitions cannot carry autoCompactWindow and the agent files are not read,
        # so it travels as the per-model setting instead (agents.compact_window_settings).
        model_settings = agents_mod.compact_window_settings(loaded)
        if model_settings:
            session_settings["modelSettings"] = model_settings
    kwargs["settings"] = json.dumps(session_settings)
    for name, ag in loaded.items():
        if ag.definition.model not in allowed:
            raise ValueError("agent %s uses %r, not an allowed tier model" % (name, ag.definition.model))
    if main:
        if cfg.model or cfg.effort:
            raise ValueError("the main thread runs %s on its tier model/effort; change config/models.json "
                             "instead of overriding (model=%r effort=%r)" % (main.name, cfg.model, cfg.effort))
        pinned = tiers.main_thread(main.name)
        kwargs["model"] = pinned["model"]
        kwargs["effort"] = pinned["effort"] or None
        if source == "filesystem":
            extra_args["agent"] = main.name  # --agent: the body replaces the system prompt
        else:
            kwargs["system_prompt"] = {"type": "preset", "preset": "claude_code", "append": main.definition.prompt}
            # Without --agent the main agent's inline servers are not attached; pass them as session servers
            # (subagents that name them then share this connection, as under --agent).
            inline = {k: (v if local else mcpcat.pin_repo(v, paths.REPO))
                      for e in main.definition.mcpServers or [] if isinstance(e, dict) for k, v in e.items()}
            if inline:
                kwargs["mcp_servers"] = {**(kwargs.get("mcp_servers") or {}), **inline}
    else:
        if cfg.model and cfg.model not in allowed:
            raise ValueError("model %r is not an allowed tier model %s" % (cfg.model, allowed))
        kwargs["model"] = cfg.model
        kwargs["effort"] = cfg.effort
    if extra_args:
        kwargs["extra_args"] = extra_args
    return ClaudeAgentOptions(**{k: v for k, v in kwargs.items() if v is not None})


def describe(opts: ClaudeAgentOptions) -> dict:
    """A secret-free summary of the options (for `stack-sdk check`)."""
    return {
        "cwd": str(opts.cwd), "model": opts.model, "effort": opts.effort,
        "setting_sources": opts.setting_sources, "permission_mode": opts.permission_mode,
        "skills": opts.skills, "task_budget": opts.task_budget, "max_budget_usd": opts.max_budget_usd,
        "main_agent_via": "--agent" if (opts.extra_args or {}).get("agent") else (
            "system_prompt.append" if isinstance(opts.system_prompt, dict) else "default"),
        "programmatic_agents": sorted((opts.agents or {}).keys()),
        "mcp_servers": sorted(opts.mcp_servers.keys()) if isinstance(opts.mcp_servers, dict) else str(opts.mcp_servers),
        "python_hooks": sorted((opts.hooks or {}).keys()),
        "cli_path": str(opts.cli_path) if opts.cli_path else "bundled",
        "extra_args": opts.extra_args,
        "model_settings": json.loads(opts.settings).get("modelSettings", {}) if opts.settings else {},
        "env": {k: v for k, v in opts.env.items()},
        "allowed_tools": opts.allowed_tools,
    }
