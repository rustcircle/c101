"""Load this stack's .claude/agents/**/*.md files as Claude Agent SDK AgentDefinitions.

The markdown files are the single source of truth for both runtimes:

* interactive Claude Code (and SDK sessions whose ``setting_sources`` include the
  project) read them from disk;
* SDK sessions running in *another* directory get them programmatically through
  ``ClaudeAgentOptions.agents`` via :func:`load_agents`.

Field mapping is driven by the installed SDK's ``AgentDefinition`` dataclass, so
frontmatter keys the SDK does not model (``color``; and ``hooks``, ``isolation``,
``omitClaudeMd`` if ever used) are reported as dropped rather than passed through and
rejected.

``autoCompactWindow`` is the one key the learner writes on purpose (config/learning.json) that
neither ``AgentDefinition`` nor ``ClaudeAgentOptions`` can carry per agent.  It is therefore
*explicitly ignored* for the programmatic definition (listed in ``LoadedAgent.ignored``, never in
``dropped``), parsed and range-checked into ``LoadedAgent.auto_compact_window``, and re-expressed at
the only level the CLI exposes it to SDK sessions: ``modelSettings.<model>.autoCompactWindow`` in the
session settings (see :func:`compact_window_settings`, used by ``options.build_options`` when
agents are sent programmatically).  Sessions that load the agent files from disk read the
frontmatter value directly.
"""
from __future__ import annotations

import dataclasses
import os
import warnings
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import AgentDefinition

from stack import doctor, frontmatter, paths, tiers

SDK_FIELDS = {f.name for f in dataclasses.fields(AgentDefinition)}
LIST_FIELDS = {"tools", "disallowedTools", "skills", "mcpServers"}
INT_FIELDS = {"maxTurns"}
BOOL_FIELDS = {"background"}
# Frontmatter keys that are valid for Claude Code and owned by this stack, but have no
# AgentDefinition field.  Not "dropped" (a problem for `stack-sdk check`): deliberately not
# passed on the definition; see the module docstring.
STACK_ONLY_FIELDS = {"autoCompactWindow"}
COMPACT_WINDOW_RANGE = (100_000, 1_000_000)  # the range Claude Code accepts (stack/doctor.py)


@dataclass
class LoadedAgent:
    name: str
    path: str
    group: str
    definition: AgentDefinition
    dropped: dict[str, Any] = field(default_factory=dict)
    ignored: dict[str, Any] = field(default_factory=dict)
    auto_compact_window: int | None = None
    problems: list[str] = field(default_factory=list)   # reported by `stack-sdk check`; never fatal to a load


def _convert(key: str, value: Any) -> Any:
    if key in LIST_FIELDS:
        return doctor._as_list(value)  # handles "A, B, Agent(x, y)" and YAML lists
    if key in INT_FIELDS:
        return int(value)
    if key in BOOL_FIELDS:
        return str(value).strip().lower() in ("true", "yes", "1")
    return value


def parse_compact_window(value: Any, *, agent: str = "?") -> int:
    """Validate a frontmatter ``autoCompactWindow`` (tokens, 100000..1000000)."""
    text = str(value).strip()
    if not text.isdigit() or not COMPACT_WINDOW_RANGE[0] <= int(text) <= COMPACT_WINDOW_RANGE[1]:
        raise ValueError("%s: autoCompactWindow must be an integer %d..%d, got %r"
                         % (agent, *COMPACT_WINDOW_RANGE, value))
    return int(text)


def load_agent(path: str, use_tiers: bool = True) -> LoadedAgent:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    fm = frontmatter.parse(text)
    _, body = frontmatter.split(text)
    name = str(fm["name"])
    kwargs: dict[str, Any] = {"description": str(fm.get("description", "")), "prompt": body.strip()}
    dropped: dict[str, Any] = {}
    ignored: dict[str, Any] = {}
    problems: list[str] = []
    window: int | None = None
    for key, value in fm.items():
        if key in ("name", "description"):
            continue
        if key in STACK_ONLY_FIELDS:
            ignored[key] = value
            if key == "autoCompactWindow" and value not in (None, ""):
                try:
                    window = parse_compact_window(value, agent=name)
                except ValueError as exc:
                    # One hand-edited value ("600K") must not stop every SDK run: say so, skip the value and
                    # use the learner's floor (what `bin/stack agents tiers --apply` would restore).
                    fallback = tiers.compact_window_floor() or None
                    problems.append("%s; using %s" % (exc, fallback if fallback else "no window"))
                    warnings.warn(problems[-1], stacklevel=2)
                    window = fallback
        elif key in SDK_FIELDS:
            if value not in (None, "", []):
                kwargs[key] = _convert(key, value)
        else:
            dropped[key] = value
    if use_tiers:
        model = tiers.model_for(name)
        if model:
            kwargs["model"] = model  # honours ADVANCED_MODEL/MEDIUM_MODEL/LOW_MODEL env overrides
    group = os.path.relpath(os.path.dirname(path), os.path.join(paths.REPO, ".claude", "agents"))
    return LoadedAgent(name=name, path=path, group="" if group == "." else group,
                       definition=AgentDefinition(**kwargs), dropped=dropped, ignored=ignored,
                       auto_compact_window=window, problems=problems)


def load_all(use_tiers: bool = True) -> dict[str, LoadedAgent]:
    out: dict[str, LoadedAgent] = {}
    for path in paths.all_agent_files():
        a = load_agent(path, use_tiers=use_tiers)
        if a.name in out:
            raise ValueError("duplicate agent name %s (%s, %s)" % (a.name, out[a.name].path, path))
        out[a.name] = a
    return out


def load_agents(use_tiers: bool = True) -> dict[str, AgentDefinition]:
    """{name: AgentDefinition} ready for ``ClaudeAgentOptions(agents=...)``."""
    return {name: a.definition for name, a in load_all(use_tiers).items()}


def compact_window_settings(loaded: dict[str, LoadedAgent] | None = None) -> dict[str, dict[str, int]]:
    """``modelSettings`` for session settings: {model id: {"autoCompactWindow": tokens}}.

    The CLI exposes the compaction window to SDK sessions per *model*, not per agent, so each model
    gets the largest window any of its agents asks for (quality first: raising never compacts
    earlier than an agent wanted), clamped to the tier's ``context_window`` in config/models.json
    so a value the model cannot hold is never sent.  Agents without the key do not contribute.
    """
    loaded = load_all() if loaded is None else loaded
    limits = tiers.context_windows()
    out: dict[str, int] = {}
    for ag in loaded.values():
        model = ag.definition.model
        if not model or ag.auto_compact_window is None:
            continue
        out[model] = max(out.get(model, 0), min(ag.auto_compact_window, limits.get(model, ag.auto_compact_window)))
    return {m: {"autoCompactWindow": w} for m, w in sorted(out.items())}
