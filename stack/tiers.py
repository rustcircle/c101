"""Model tiers: ADVANCED_MODEL / MEDIUM_MODEL / LOW_MODEL -> concrete model ids.

`config/models.json` is the single place that decides which model each agent
runs on and its *initial* effort / maxTurns.  `sync()` renders it into agent
frontmatter:

* ``model`` is always set to the tier's model id (env vars ``ADVANCED_MODEL``,
  ``MEDIUM_MODEL``, ``LOW_MODEL`` override the configured ids, e.g. to trial a
  new release without editing files);
* ``effort`` / ``maxTurns`` are written only when missing, or for every agent
  with ``reset_traits=True`` -- after that the Bayesian learner owns them;
* ``autoCompactWindow`` (initial value ``default_traits`` in models.json, clamped to the tier's
  ``context_window``) is also learner-owned, but ``sync`` additionally raises a value that sits
  below the floor (config/learning.json ``default_bounds.autoCompactWindow[0]``), so a learner
  or hand edit can never leave an agent compacting earlier than the policy allows.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from . import frontmatter, paths

TIER_NAMES = ("ADVANCED_MODEL", "MEDIUM_MODEL", "LOW_MODEL")
CONFIG = os.path.join(paths.CONFIG_DIR, "models.json")


def load() -> dict:
    with open(CONFIG, encoding="utf-8") as fh:
        return json.load(fh)


def save(cfg: dict) -> None:
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, CONFIG)


def tier_models(cfg: Optional[dict] = None) -> Dict[str, str]:
    """Tier name -> model id, with environment overrides applied."""
    cfg = cfg or load()
    out = {}
    for name, spec in cfg["tiers"].items():
        out[name] = (os.environ.get(name) or spec["model"]).strip()
    return out


def context_windows(cfg: Optional[dict] = None) -> Dict[str, int]:
    """Effective model id -> context window in tokens (the tier's ``context_window``).

    An env override (``ADVANCED_MODEL`` ...) swaps the model id but keeps the tier's window, so
    point it at a model with at least that window or lower ``context_window`` in models.json.
    """
    cfg = cfg or load()
    models = tier_models(cfg)
    return {models[name]: int(spec["context_window"])
            for name, spec in cfg["tiers"].items() if spec.get("context_window")}


def compact_window_floor() -> int:
    """Lowest autoCompactWindow the learner may leave an agent at (config/learning.json bounds)."""
    try:
        with open(os.path.join(paths.CONFIG_DIR, "learning.json"), encoding="utf-8") as fh:
            lo = json.load(fh).get("default_bounds", {}).get("autoCompactWindow", [0])[0]
        return int(lo)
    except (OSError, ValueError, IndexError, TypeError):
        return 0


def initial_compact_window(agent: str, cfg: Optional[dict] = None) -> Optional[int]:
    """autoCompactWindow an agent starts with: its own entry, else ``default_traits``, clamped to
    what its tier's model can hold.  None when no value is configured."""
    cfg = cfg or load()
    entry = cfg["agents"].get(agent) or {}
    want = entry.get("autoCompactWindow", (cfg.get("default_traits") or {}).get("autoCompactWindow"))
    if want in (None, ""):
        return None
    want = int(want)
    window = (cfg["tiers"].get(entry.get("tier", "")) or {}).get("context_window")
    return min(want, int(window)) if window else want


def tier_aliases(cfg: Optional[dict] = None) -> Dict[str, str]:
    cfg = cfg or load()
    return {name: spec.get("alias", "") for name, spec in cfg["tiers"].items()}


def model_for(agent: str, cfg: Optional[dict] = None) -> Optional[str]:
    cfg = cfg or load()
    entry = cfg["agents"].get(agent)
    if not entry:
        return None
    return tier_models(cfg).get(entry["tier"])


def sync(apply: bool = False, reset_traits: bool = False, only: Optional[List[str]] = None) -> List[dict]:
    """Return the per-agent changes; write them when ``apply``."""
    cfg = load()
    models = tier_models(cfg)
    changes = []
    for name, entry in sorted(cfg["agents"].items()):
        if only and name not in only:
            continue
        path = paths.find_agent_file(name)
        if not path:
            changes.append({"agent": name, "error": "no agent file"})
            continue
        if entry["tier"] not in models:
            changes.append({"agent": name, "error": "unknown tier %s" % entry["tier"]})
            continue
        fm = frontmatter.read(path)
        upd: Dict[str, Optional[str]] = {}
        if fm.get("model") != models[entry["tier"]]:
            upd["model"] = models[entry["tier"]]
        for key in ("effort", "maxTurns"):
            want = entry.get(key)
            if want is None:
                continue
            cur = fm.get(key)
            if (cur in (None, "") or reset_traits) and str(cur) != str(want):
                upd[key] = str(want)
        want_win = initial_compact_window(name, cfg)
        if want_win is not None:
            cur_win = fm.get("autoCompactWindow")
            cur_ok = str(cur_win or "").isdigit()
            if reset_traits or not cur_ok or int(cur_win) < min(compact_window_floor(), want_win):
                if str(cur_win) != str(want_win):
                    upd["autoCompactWindow"] = str(want_win)
        if upd:
            if apply:
                frontmatter.update_file(path, upd)
            changes.append({"agent": name, "tier": entry["tier"], "updates": upd,
                            "path": os.path.relpath(path, paths.REPO)})
    return changes


def set_tier(agent: str, tier: str) -> None:
    if tier not in TIER_NAMES:
        raise ValueError("tier must be one of %s" % ", ".join(TIER_NAMES))
    cfg = load()
    entry = cfg["agents"].setdefault(agent, {})
    entry["tier"] = tier
    save(cfg)
    sync(apply=True, only=[agent])


def allowed_models(cfg: Optional[dict] = None) -> List[str]:
    """The only model ids agents and the main thread may run on (the three tiers)."""
    return sorted(set(tier_models(cfg).values()))


def alias_models(cfg: Optional[dict] = None) -> Dict[str, str]:
    """Family alias -> tier model id (opus/sonnet/haiku), for resolving workflow/agent aliases."""
    cfg = cfg or load()
    models = tier_models(cfg)
    return {spec.get("alias"): models[name] for name, spec in cfg["tiers"].items() if spec.get("alias")}


def main_thread(agent: str) -> Dict[str, str]:
    """Model and effort the main thread must run with when `agent` is the main agent."""
    from . import frontmatter as fm_mod
    path = paths.find_agent_file(agent)
    if not path:
        raise ValueError("unknown agent %s" % agent)
    fm = fm_mod.read(path)
    model = model_for(agent) or str(fm.get("model") or "")
    if model not in allowed_models():
        raise ValueError("%s resolves to %r, which is not an allowed tier model" % (agent, model))
    return {"model": model, "effort": str(fm.get("effort") or "")}
