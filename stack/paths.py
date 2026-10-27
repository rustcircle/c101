"""Filesystem locations used by the stack (repo, config, learned data, agents)."""
from __future__ import annotations

import os
from typing import List, Optional

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(REPO, "config")
HOME_CLAUDE = os.path.join(os.path.expanduser("~"), ".claude")


def data_dir() -> str:
    d = os.environ.get("CLAUDE_STACK_DATA") or os.path.join(HOME_CLAUDE, "stack-data")
    os.makedirs(d, exist_ok=True)
    return d


def projects_root() -> str:
    return os.environ.get("CLAUDE_PROJECTS_ROOT") or os.path.join(HOME_CLAUDE, "projects")


def agent_dirs() -> List[str]:
    dirs = []
    proj = os.environ.get("CLAUDE_PROJECT_DIR")
    if proj:
        dirs.append(os.path.join(proj, ".claude", "agents"))
    dirs.append(os.path.join(REPO, ".claude", "agents"))
    dirs.append(os.path.join(HOME_CLAUDE, "agents"))
    seen, out = set(), []
    for d in dirs:
        r = os.path.realpath(d)
        if r not in seen and os.path.isdir(d):
            seen.add(r)
            out.append(d)
    return out


def find_agent_file(name: str) -> Optional[str]:
    """Locate an agent definition by name (file stem == frontmatter name here)."""
    for d in agent_dirs():
        for root, _dirs, files in os.walk(d, followlinks=True):
            if name + ".md" in files:
                return os.path.join(root, name + ".md")
    return None


def all_agent_files() -> List[str]:
    """Agent files in this repo (the stack's own agents)."""
    base = os.path.join(REPO, ".claude", "agents")
    out = []
    for root, _dirs, files in os.walk(base):
        out.extend(os.path.join(root, f) for f in files if f.endswith(".md"))
    return sorted(out)


def python_version() -> str:
    """The uv-managed CPython the stack runs on, from .python-version (e.g. "3.13")."""
    with open(os.path.join(REPO, ".python-version"), encoding="utf-8") as fh:
        return fh.read().strip()


_NOT_SOURCE = {".git", ".venv", ".stack", "node_modules", "__pycache__"}


def script_files() -> List[str]:
    """Repo files that start with '#!'; each must be executable (hooks, MCP configs and skills run them directly)."""
    out = []
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in _NOT_SOURCE]
        for f in files:
            p = os.path.join(root, f)
            try:
                with open(p, "rb") as fh:
                    if fh.read(2) == b"#!":
                        out.append(p)
            except OSError:
                continue
    return sorted(out)
