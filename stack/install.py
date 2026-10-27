"""`bin/stack install` — wire the stack into ~/.claude.

Base install (always, idempotent):
  * ~/.claude/stack            -> symlink to this repo (stable path for user-scope configs)
  * ~/.claude/stack.env        <- created from config/stack.env.example if missing (mode 600)
  * ~/.claude/stack-data/      learning data directory
  * executable bits            restored on every repo script that starts with '#!' (lost by zip downloads or
                               copies; hooks and MCP servers run bin/* directly)
  * default Python             uv's CPython from .python-version (3.14) for every Claude Code session:
                               UV_PYTHON + UV_PYTHON_PREFERENCE=only-managed in ~/.claude/settings.json env, and
                               python/python3 in uv's bin directory (~/.local/bin) linked to it

--user        make agents, skills and workflows available in every project (per-file symlinks
              under ~/.claude/agents/stack/, ~/.claude/skills/<name>, ~/.claude/workflows/),
              register the MCP servers at user scope (via `claude mcp add-json`), and merge env +
              hooks into ~/.claude/settings.json (backup written first).
--main-agent  set "agent": "delegator" in ~/.claude/settings.json so every session's main thread
              is the delegator (undo with --no-main-agent).
--enforce-models  restrict every project to the tier models from ~/.claude/settings.json: availableModels (from
              config/models.json; prefix match outside managed settings), enforceAvailableModels and the
              PreModelSwitch guard (pins a stack main agent to its exact tier model). Works alone (nothing
              else is installed) or with --user. Undo with --no-enforce-models. Exact matching for every
              model needs managed settings: `sudo bin/stack managed-settings --install`.
--packs a,b   with --user: link only these install packs (+ core and requirements); see
              `bin/stack packs list`. Default: all packs.
--no-python-default  remove UV_PYTHON / UV_PYTHON_PREFERENCE from ~/.claude/settings.json (the python/python3
              links stay; `uv python uninstall` or deleting them removes them).
--adobe [APPS]  register the Adobe desktop-app MCP servers (InDesign, Illustrator, Photoshop, After Effects,
              Premiere Pro; entries tagged "_group": "adobe" in config/mcp.optional.json) at user scope, so every
              project sees them, then runs each app's one-time setup (stack/adobe.py: pinned clones and npm
              packages, builds, LaunchAgents for the Photoshop proxy and the InDesign bridge, the After Effects
              panel script and the Premiere CEP panel) and prints the few steps left to do inside the apps.
              APPS: all (default) or a comma list of server names. Works alone or with --user.
--adobe-no-setup  with --adobe: register only (print the manual setup instead of running it).
--no-adobe    unregister the Adobe servers and unload/remove their LaunchAgents (the checkouts under
              ~/.claude/stack-data/adobe stay).
--mcp a,b     register any optional servers from config/mcp.optional.json at user scope.
--dry-run     print what would change.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from typing import List, Optional

from . import paths

HOME = os.path.expanduser("~")
CLAUDE = paths.HOME_CLAUDE
LINK = os.path.join(CLAUDE, "stack")
HOOK_MARK = "/.claude/stack/bin/stack hook"


class Ctx:
    def __init__(self, dry: bool) -> None:
        self.dry = dry
        self.log: List[str] = []

    def do(self, msg: str, fn=None) -> None:
        self.log.append(("would " if self.dry else "") + msg)
        print(("[dry-run] " if self.dry else "") + msg)
        if fn and not self.dry:
            fn()


def _symlink(ctx: Ctx, target: str, link: str) -> None:
    if os.path.islink(link):
        if os.path.realpath(link) == os.path.realpath(target):
            return
        ctx.do("relink %s -> %s" % (link, target), lambda: (os.unlink(link), os.symlink(target, link)))
    elif os.path.exists(link):
        print("skip %s: exists and is not a symlink (move it away to let the stack manage it)" % link)
    else:
        ctx.do("link %s -> %s" % (link, target),
               lambda: (os.makedirs(os.path.dirname(link), exist_ok=True), os.symlink(target, link)))


def base(ctx: Ctx) -> None:
    _symlink(ctx, paths.REPO, LINK)
    env = os.path.join(CLAUDE, "stack.env")
    if not os.path.exists(env):
        def mk():
            shutil.copyfile(os.path.join(paths.CONFIG_DIR, "stack.env.example"), env)
            os.chmod(env, stat.S_IRUSR | stat.S_IWUSR)
        ctx.do("create %s from template (mode 600) — fill in your keys" % env, mk)
    else:
        mode = stat.S_IMODE(os.stat(env).st_mode)
        if mode & 0o077:
            ctx.do("tighten %s permissions to 600" % env, lambda: os.chmod(env, 0o600))
    d = os.path.join(CLAUDE, "stack-data")
    if not os.path.isdir(d):
        ctx.do("create %s" % d, lambda: os.makedirs(d, exist_ok=True))
    fix_executables(ctx)


def fix_executables(ctx: Ctx) -> None:
    """chmod +x (where readable) every repo script with a '#!' line that lost its executable bit."""
    stale = [p for p in paths.script_files() if not os.access(p, os.X_OK)]
    if not stale:
        return

    def fix():
        for p in stale:
            mode = stat.S_IMODE(os.stat(p).st_mode)
            os.chmod(p, mode | (mode & 0o444) >> 2)
    ctx.do("make %d script(s) executable: %s" % (len(stale), ", ".join(os.path.relpath(p, paths.REPO) for p in stale)),
           fix)


PYTHON_ENV_KEYS = ("UV_PYTHON", "UV_PYTHON_PREFERENCE")


def python_env(ctx: Ctx, on: bool) -> None:
    """Force uv's CPython from .python-version for every uv/uvx command Claude Code runs, in every project.

    UV_PYTHON overrides project pins (a project that requires another version needs an explicit --python);
    UV_PYTHON_PREFERENCE=only-managed keeps uv off the system and Homebrew interpreters.
    """
    user_path = os.path.join(CLAUDE, "settings.json")
    user = _load_settings(user_path)
    env = user.setdefault("env", {})
    want = dict(zip(PYTHON_ENV_KEYS, (paths.python_version(), "only-managed")))
    if on:
        if all(env.get(k) == v for k, v in want.items()):
            return
        env.update(want)
        why = "default Python: uv CPython %s" % want["UV_PYTHON"]
    else:
        if not any(k in env for k in PYTHON_ENV_KEYS):
            return
        for k in PYTHON_ENV_KEYS:
            env.pop(k, None)
        if not env:
            user.pop("env")
        why = "default Python removed"
    _write_settings(ctx, user_path, user, why)


def link_default_python(ctx: Ctx) -> None:
    """Point python and python3 in uv's bin directory (~/.local/bin) at uv's CPython from .python-version."""
    uv = shutil.which("uv")
    ver = paths.python_version()
    if not uv:
        print("uv not on PATH; skipped linking python/python3 to CPython %s" % ver)
        return

    def out(*args: str) -> str:
        r = subprocess.run([uv, *args], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    bindir, exe = out("python", "dir", "--bin"), out("python", "find", "--managed-python", ver)
    if bindir and exe and all(os.path.realpath(os.path.join(bindir, n)) == os.path.realpath(exe)
                              for n in ("python", "python3")):
        return

    def link():
        r = subprocess.run([uv, "python", "install", "--default", "--preview-features", "python-install-default", ver])
        if r.returncode != 0:
            print("  uv python install --default %s failed (exit %d); python/python3 unchanged" % (ver, r.returncode))
    ctx.do("link python/python3 in %s to uv's CPython %s" % (bindir or "uv's bin directory", ver), link)


def link_components(ctx: Ctx, selected: Optional[List[str]] = None) -> None:
    from . import packs as packs_mod
    sel = packs_mod.resolve(selected or ["all"])
    want_skills = packs_mod.skills_of(sel)
    want_agents = packs_mod.agents_of(sel)
    print("packs: %s (%d skills, %d agents)" % (", ".join(sel), len(want_skills), len(want_agents)))
    src_agents = os.path.join(paths.REPO, ".claude", "agents")
    for root, _dirs, files in os.walk(src_agents):
        for f in files:
            if f.endswith(".md") and f[:-3] in want_agents:
                rel = os.path.relpath(os.path.join(root, f), src_agents)
                _symlink(ctx, os.path.join(root, f), os.path.join(CLAUDE, "agents", "stack", rel))
    src_skills = os.path.join(paths.REPO, ".claude", "skills")
    for name in sorted(os.listdir(src_skills)):
        if os.path.isdir(os.path.join(src_skills, name)) and name in want_skills:
            _symlink(ctx, os.path.join(src_skills, name), os.path.join(CLAUDE, "skills", name))
    src_wf = os.path.join(paths.REPO, ".claude", "workflows")
    if os.path.isdir(src_wf):
        for f in sorted(os.listdir(src_wf)):
            if f.endswith(".js"):
                _symlink(ctx, os.path.join(src_wf, f), os.path.join(CLAUDE, "workflows", f))


def _user_mcp_entry(cfg: dict) -> dict:
    """Rewrite project-relative launcher paths to the stable ~/.claude/stack link."""
    s = json.dumps({k: v for k, v in cfg.items() if not k.startswith("_")})
    s = s.replace("${CLAUDE_PROJECT_DIR:-.}", LINK)
    s = s.replace("${CLAUDE_PROJECT_DIR:-$HOME/.claude/stack}", LINK)
    return json.loads(s)


def _register_user_mcp(ctx: Ctx, name: str, cfg: dict, claude: Optional[str]) -> None:
    entry = json.dumps(_user_mcp_entry(cfg))
    if not claude:
        print("claude CLI not on PATH; add manually: claude mcp add-json --scope user %s '%s'" % (name, entry))
        return

    def add():
        subprocess.run([claude, "mcp", "remove", "--scope", "user", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        r = subprocess.run([claude, "mcp", "add-json", "--scope", "user", name, entry],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print("  failed to register %s: %s" % (name, (r.stderr or r.stdout).strip()))
    ctx.do("register MCP server %s at user scope" % name, add)


def register_mcp(ctx: Ctx) -> None:
    claude = shutil.which("claude")
    with open(os.path.join(paths.REPO, ".mcp.json"), encoding="utf-8") as fh:
        servers = json.load(fh)["mcpServers"]
    from . import mcpcat
    lazy = sorted(mcpcat.catalog())
    if lazy:
        print("MCP servers %s load lazily inside the agents that use them (config/mcp.servers.json); nothing to "
              "register for them. If an earlier install registered them at user scope, remove those so they stop "
              "connecting for every session: claude mcp remove --scope user <name>" % ", ".join(lazy))
    for name, cfg in servers.items():
        _register_user_mcp(ctx, name, cfg, claude)


def optional_servers() -> dict:
    with open(os.path.join(paths.CONFIG_DIR, "mcp.optional.json"), encoding="utf-8") as fh:
        return json.load(fh)["mcpServers"]


def adobe_servers() -> List[str]:
    """Optional servers tagged "_group": "adobe", in file order."""
    return [n for n, c in optional_servers().items() if c.get("_group") == "adobe"]


def resolve_optional(names: List[str]) -> List[str]:
    """Validate optional server names; raises SystemExit naming the unknown ones."""
    known = optional_servers()
    bad = [n for n in names if n not in known]
    if bad:
        raise SystemExit("unknown optional MCP server(s): %s (see `bin/stack mcp list`)" % ", ".join(bad))
    return names


def register_optional(ctx: Ctx, names: List[str], automated: Optional[List[str]] = None) -> None:
    """Register optional servers from config/mcp.optional.json at user scope (every project). Servers whose setup
    the installer runs itself (`automated`) skip the printed `_setup` hint."""
    claude = shutil.which("claude")
    servers = optional_servers()
    for name in names:
        cfg = servers[name]
        _register_user_mcp(ctx, name, cfg, claude)
        if cfg.get("_setup") and name not in (automated or []):
            print("  %s setup: %s" % (name, cfg["_setup"]))


def unregister_optional(ctx: Ctx, names: List[str]) -> None:
    claude = shutil.which("claude")
    for name in names:
        if not claude:
            print("claude CLI not on PATH; remove manually: claude mcp remove --scope user %s" % name)
            continue
        ctx.do("remove MCP server %s from user scope" % name,
               lambda name=name: subprocess.run([claude, "mcp", "remove", "--scope", "user", name],
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))


def _load_settings(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _write_settings(ctx: Ctx, path: str, data: dict, why: str) -> None:
    def w():
        if os.path.exists(path):
            shutil.copyfile(path, "%s.bak-%d" % (path, int(time.time())))
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    ctx.do("update %s (%s; backup kept)" % (path, why), w)


def merge_settings(ctx: Ctx, enforce_models: bool = False) -> None:
    user_path = os.path.join(CLAUDE, "settings.json")
    user = _load_settings(user_path)
    with open(os.path.join(paths.REPO, ".claude", "settings.json"), encoding="utf-8") as fh:
        proj = json.load(fh)
    env = user.setdefault("env", {})
    for k, v in proj.get("env", {}).items():
        env.setdefault(k, v)
    if enforce_models:
        for k in ("availableModels", "enforceAvailableModels"):  # availableModelsMatch: managed settings only
            if k in proj:
                user[k] = proj[k]
    hooks = user.setdefault("hooks", {})
    for event, groups in proj.get("hooks", {}).items():
        if event == "PreModelSwitch" and not enforce_models:
            continue
        cur = hooks.setdefault(event, [])
        # drop previous stack hooks, then add fresh ones pointing at ~/.claude/stack
        cur[:] = [g for g in cur if not any(HOOK_MARK in h.get("command", "") for h in g.get("hooks", []))]
        for g in groups:
            g2 = json.loads(json.dumps(g))
            for h in g2.get("hooks", []):
                h["command"] = h.get("command", "").replace('"$CLAUDE_PROJECT_DIR"/bin/stack',
                                                            '"$HOME"/.claude/stack/bin/stack')
            cur.append(g2)
    _write_settings(ctx, user_path, user, "stack env + hooks")


MODEL_HOOK = '"$HOME"/.claude/stack/bin/stack hook model-switch'


def enforce_models_global(ctx: Ctx, on: bool) -> None:
    """Restrict every project to the tier models from ~/.claude/settings.json, without installing anything else.

    Writes availableModels (rendered from config/models.json), enforceAvailableModels and the PreModelSwitch
    guard. availableModels matches by prefix outside managed settings and enforceAvailableModels is read only while
    no managed settings exist; the guard blocks non-tier switches and pins a stack main agent to its exact tier
    model. availableModelsMatch is dropped: Claude Code ignores it outside managed settings.
    """
    from . import tiers
    user_path = os.path.join(CLAUDE, "settings.json")
    user = _load_settings(user_path)
    groups = user.setdefault("hooks", {}).setdefault("PreModelSwitch", [])
    groups[:] = [g for g in groups if not any(MODEL_HOOK in h.get("command", "") for h in g.get("hooks", []))]
    user.pop("availableModelsMatch", None)
    if on:
        user["availableModels"] = sorted(tiers.allowed_models())
        user["enforceAvailableModels"] = True
        groups.append({"hooks": [{"type": "command", "command": MODEL_HOOK, "timeout": 10}]})
    else:
        user.pop("availableModels", None)
        user.pop("enforceAvailableModels", None)
    if not groups:
        user["hooks"].pop("PreModelSwitch")
    if not user["hooks"]:
        user.pop("hooks")
    _write_settings(ctx, user_path, user, "tier-model enforcement %s" % ("on" if on else "off"))


def set_main_agent(ctx: Ctx, on: bool) -> None:
    user_path = os.path.join(CLAUDE, "settings.json")
    user = _load_settings(user_path)
    if on:
        user["agent"] = "delegator"
    else:
        user.pop("agent", None)
    _write_settings(ctx, user_path, user, "main agent %s" % ("delegator" if on else "default"))


def main(argv: List[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="stack install")
    p.add_argument("--user", action="store_true")
    p.add_argument("--main-agent", action="store_true")
    p.add_argument("--no-main-agent", action="store_true")
    p.add_argument("--enforce-models", action="store_true")
    p.add_argument("--no-enforce-models", action="store_true")
    p.add_argument("--packs", help="comma-separated packs for --user (default: all); core is always included")
    p.add_argument("--no-python-default", action="store_true")
    p.add_argument("--adobe", nargs="?", const="all", metavar="APPS",
                   help="register the Adobe app MCP servers at user scope: all, or a comma list of %s"
                        % ", ".join(adobe_servers()))
    p.add_argument("--adobe-no-setup", action="store_true",
                   help="with --adobe: only register; skip the clones, builds, LaunchAgents and panel installs")
    p.add_argument("--no-adobe", action="store_true",
                   help="unregister the Adobe servers and remove their LaunchAgents (checkouts stay)")
    p.add_argument("--mcp", metavar="NAMES", help="register these optional MCP servers (config/mcp.optional.json) "
                   "at user scope")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    rc = 0
    extra: List[str] = []
    if a.adobe:
        extra += adobe_servers() if a.adobe == "all" else [x.strip() for x in a.adobe.split(",") if x.strip()]
    if a.mcp:
        extra += [x.strip() for x in a.mcp.split(",") if x.strip()]
    extra = resolve_optional(list(dict.fromkeys(extra)))  # fail on unknown names before anything is written
    ctx = Ctx(a.dry_run)
    base(ctx)
    if a.user:
        link_components(ctx, [x.strip() for x in a.packs.split(",")] if a.packs else None)
        register_mcp(ctx)
        merge_settings(ctx, enforce_models=a.enforce_models)
    python_env(ctx, not a.no_python_default)
    if not a.no_python_default:
        link_default_python(ctx)
    adobe_sel = [n for n in extra if n in adobe_servers()] if a.adobe and not a.adobe_no_setup else []
    if extra:
        register_optional(ctx, extra, automated=adobe_sel)
    if adobe_sel:
        from . import adobe
        if adobe.setup(ctx, adobe_sel):
            rc = 1
    if a.no_adobe:
        from . import adobe
        unregister_optional(ctx, adobe_servers())
        if sys.platform == "darwin":
            adobe.remove_agents(ctx)
    if a.enforce_models or a.no_enforce_models:
        enforce_models_global(ctx, a.enforce_models)
    if a.main_agent or a.no_main_agent:
        set_main_agent(ctx, a.main_agent)
    if not ctx.log:
        print("nothing to do; already installed")
    print("\nnext: fill ~/.claude/stack.env, then `bin/stack keys` and `bin/stack doctor`.")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
