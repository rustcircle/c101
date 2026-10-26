"""`bin/stack doctor`: validate every agent, skill, workflow, MCP and hook entry.

Claude Code silently ignores unknown or misspelled frontmatter keys, so a typo
like ``maxturns`` would quietly do nothing.  This checker is the guard rail.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Dict, List, Set, Tuple

from . import frontmatter, mcpcat, paths

AGENT_FIELDS = {
    "name", "description", "tools", "disallowedTools", "model", "effort", "maxTurns", "mcpServers",
    "skills", "memory", "hooks", "permissionMode", "isolation", "background", "color", "initialPrompt",
    "omitClaudeMd", "autoCompactWindow", "experimental",
}
SKILL_FIELDS = {
    "name", "description", "when_to_use", "argument-hint", "arguments", "disable-model-invocation",
    "user-invocable", "allowed-tools", "disallowed-tools", "model", "effort", "context", "agent",
    "background", "hooks", "paths", "shell", "metadata", "license", "compatibility",
}
MODELS = {"opus", "sonnet", "haiku", "fable", "inherit", "default", "best", "opusplan",
          "opus[1m]", "sonnet[1m]"}
EFFORTS = {"low", "medium", "high", "xhigh", "max"}
COLORS = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}
BUILTIN_AGENTS = {"general-purpose", "Explore", "Plan", "statusline-setup", "claude-code-guide", "fork"}
BUILTIN_MCP = {"computer-use", "claude-in-chrome"}
RESERVED_WORKFLOW_NAMES = {"deep-research"}
BUILTIN_TOOLS = {
    "Agent", "Task", "Bash", "Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "WebFetch", "WebSearch",
    "NotebookEdit", "TodoWrite", "Skill", "Workflow", "SendMessage", "TaskCreate", "TaskGet", "TaskList",
    "TaskUpdate", "TaskStop", "Monitor", "ToolSearch", "BashOutput", "KillShell", "ExitPlanMode",
}


class Report:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def err(self, where: str, msg: str) -> None:
        self.errors.append("%s: %s" % (where, msg))

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append("%s: %s" % (where, msg))


def read_text(p: str) -> str:
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def read_json(p: str):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _rel(p: str) -> str:
    return os.path.relpath(p, paths.REPO)


def _as_list(v) -> List[str]:
    if v is None or v == "":
        return []
    if isinstance(v, list):  # inline mcpServers definitions stay dicts
        return [x if isinstance(x, dict) else x.strip() for x in v if isinstance(x, dict) or x.strip()]
    # comma-separated, but keep Agent(a, b) groups intact
    out, depth, cur = [], 0, ""
    for ch in v:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def mcp_names() -> Set[str]:
    try:
        with open(os.path.join(paths.REPO, ".mcp.json"), encoding="utf-8") as fh:
            return set(json.load(fh).get("mcpServers", {}).keys())
    except (OSError, ValueError):
        return set()


def skill_names() -> Set[str]:
    base = os.path.join(paths.REPO, ".claude", "skills")
    if not os.path.isdir(base):
        return set()
    return {d for d in os.listdir(base) if os.path.isfile(os.path.join(base, d, "SKILL.md"))}


def agent_names() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for f in paths.all_agent_files():
        try:
            n = frontmatter.read(f).get("name")
        except (OSError, frontmatter.FrontmatterError):
            continue
        if isinstance(n, str):
            out[n] = f
    return out


# --------------------------------------------------------------------------- #
def check_agents(rep: Report) -> None:
    servers = mcp_names() | BUILTIN_MCP
    cat, owners = mcpcat.catalog(), mcpcat.shared()
    skills = skill_names()
    seen: Dict[str, str] = {}
    files = paths.all_agent_files()
    if not files:
        rep.err(".claude/agents", "no agent files found")
    for f in files:
        where = _rel(f)
        try:
            text = read_text(f)
            fm = frontmatter.parse(text)
            _, body = frontmatter.split(text)
        except (OSError, frontmatter.FrontmatterError) as e:
            rep.err(where, "frontmatter: %s" % e)
            continue
        name = fm.get("name")
        if not isinstance(name, str) or not name:
            rep.err(where, "missing name")
            continue
        if ":" in name or name.startswith("-") or len(name) > 256:
            rep.err(where, "invalid name %r" % name)
        if name in seen:
            rep.err(where, "duplicate agent name %r (also %s)" % (name, _rel(seen[name])))
        seen[name] = f
        if os.path.splitext(os.path.basename(f))[0] != name:
            rep.warn(where, "file stem differs from name %r" % name)
        desc = fm.get("description")
        if not isinstance(desc, str) or len(desc) < 40:
            rep.err(where, "description missing or too short (it drives automatic delegation)")
        for k in fm:
            if k not in AGENT_FIELDS:
                rep.err(where, "unknown frontmatter key %r (Claude Code would ignore it)" % k)
        model = fm.get("model")
        if model and model not in MODELS and not str(model).startswith("claude-"):
            rep.err(where, "unknown model %r" % model)
        eff = fm.get("effort")
        if eff and eff not in EFFORTS:
            rep.err(where, "effort must be one of %s" % sorted(EFFORTS))
        mt = fm.get("maxTurns")
        if mt not in (None, ""):
            if not str(mt).isdigit() or not (1 <= int(mt) <= 3000):
                rep.err(where, "maxTurns must be an integer 1..3000, got %r" % mt)
        acw = fm.get("autoCompactWindow")
        if acw not in (None, ""):
            if not str(acw).isdigit() or not (100000 <= int(acw) <= 1000000):
                rep.err(where, "autoCompactWindow must be an integer 100000..1000000")
        col = fm.get("color")
        if col and col not in COLORS:
            rep.err(where, "color must be one of %s" % sorted(COLORS))
        entries = _as_list(fm.get("mcpServers"))
        for e in entries:
            name = mcpcat.entry_name(e)
            if isinstance(e, dict) and name not in cat:
                rep.err(where, "inline mcpServers entry %r is not in config/mcp.servers.json" % (name or e))
            elif not isinstance(e, dict) and name not in servers | set(cat):
                rep.err(where, "mcpServers references unknown server %r" % name)
        for name in mcpcat.drift(entries, cat, str(fm.get("name", "")), owners):
            rep.err(where, "MCP server %r is not as config/mcp.servers.json renders it (inline copy missing or stale, "
                           "or a shared server inlined outside its owner; run bin/stack mcp sync)" % name)
        for s in _as_list(fm.get("skills")):
            if s not in skills:
                rep.err(where, "skills references missing skill %r" % s)
        for t in _as_list(fm.get("tools")) + _as_list(fm.get("disallowedTools")):
            base = t.split("(")[0].strip()
            if base not in BUILTIN_TOOLS and not base.startswith("mcp__"):
                rep.warn(where, "unrecognised tool %r" % t)
        if len(body.strip()) < 600:
            rep.err(where, "body too thin (%d chars); agents need a real operating procedure" % len(body.strip()))
        if "## Output" not in body:
            rep.warn(where, "no '## Output' section (output contract)")


def check_tiers(rep: Report) -> None:
    from . import tiers
    try:
        cfg = tiers.load()
    except (OSError, ValueError) as e:
        rep.err("config/models.json", "unreadable: %s" % e)
        return
    models = tiers.tier_models(cfg)
    for t in tiers.TIER_NAMES:
        if t not in models:
            rep.err("config/models.json", "missing tier %s" % t)
    names = agent_names()
    for name, path in names.items():
        entry = cfg["agents"].get(name)
        where = _rel(path)
        if not entry:
            rep.err(where, "no tier in config/models.json (add it, then bin/stack agents tiers --apply)")
            continue
        if entry.get("tier") not in models:
            rep.err("config/models.json", "%s has unknown tier %r" % (name, entry.get("tier")))
            continue
        cur = frontmatter.read(path).get("model")
        if cur not in tiers.allowed_models(cfg):
            rep.err(where, "model %r is not one of the allowed tier models %s" % (cur, tiers.allowed_models(cfg)))
        elif cur != models[entry["tier"]]:
            rep.warn(where, "model %r differs from its tier %s=%s (bin/stack agents tiers --apply)"
                     % (cur, entry["tier"], models[entry["tier"]]))
        acw = frontmatter.read(path).get("autoCompactWindow")
        if str(acw or "").isdigit():
            window = tiers.context_windows(cfg).get(str(cur))
            if window and int(acw) > window:
                rep.err(where, "autoCompactWindow %s exceeds the %s context window (%d)" % (acw, cur, window))
            elif int(acw) < tiers.compact_window_floor():
                rep.warn(where, "autoCompactWindow %s is below the learner floor %d in config/learning.json "
                         "default_bounds (bin/stack agents tiers --apply raises it)" % (acw, tiers.compact_window_floor()))
    for name in cfg["agents"]:
        if name not in names:
            rep.warn("config/models.json", "tier entry for unknown agent %r" % name)


def check_packs(rep: Report) -> None:
    from . import packs
    try:
        cfg = packs.load()
    except (OSError, ValueError) as e:
        rep.err("config/packs.json", "unreadable: %s" % e)
        return
    skills, agents = skill_names(), set(agent_names())
    in_pack = set()
    for name, p in cfg["packs"].items():
        for r in p.get("requires", []):
            if r not in cfg["packs"]:
                rep.err("config/packs.json", "pack %s requires unknown pack %s" % (name, r))
        for s in p.get("skills", []):
            in_pack.add(s)
            if s not in skills:
                rep.err("config/packs.json", "pack %s lists missing skill %s" % (name, s))
        for a in p.get("agents", []):
            if a not in agents:
                rep.err("config/packs.json", "pack %s lists missing agent %s" % (name, a))
        if p.get("hub") and p["hub"] not in p.get("skills", []):
            rep.err("config/packs.json", "pack %s hub %s is not in its skills" % (name, p["hub"]))
    for s in sorted(skills - in_pack):
        rep.err(".claude/skills/%s" % s, "not in any pack (config/packs.json)")
    core = set(cfg["packs"].get("core", {}).get("agents", []))
    core_skills = set(cfg["packs"].get("core", {}).get("skills", []))
    for a, path in agent_names().items():
        if a in core:
            for s in _as_list(frontmatter.read(path).get("skills")):
                if s not in core_skills:
                    rep.err(_rel(path), "core agent preloads non-core skill %s (it would break pack installs)" % s)


def check_skills(rep: Report) -> None:
    base = os.path.join(paths.REPO, ".claude", "skills")
    if not os.path.isdir(base):
        rep.err(".claude/skills", "missing")
        return
    for d in sorted(os.listdir(base)):
        sd = os.path.join(base, d)
        if not os.path.isdir(sd):
            continue
        f = os.path.join(sd, "SKILL.md")
        where = _rel(f)
        if not os.path.isfile(f):
            rep.err(_rel(sd), "no SKILL.md")
            continue
        try:
            text = read_text(f)
            fm = frontmatter.parse(text)
            _, body = frontmatter.split(text)
        except (OSError, frontmatter.FrontmatterError) as e:
            rep.err(where, "frontmatter: %s" % e)
            continue
        if fm.get("name") != d:
            rep.err(where, "name %r must equal directory %r" % (fm.get("name"), d))
        if not isinstance(fm.get("description"), str) or len(fm.get("description", "")) < 40:
            rep.err(where, "description missing or too short")
        for k in fm:
            if k not in SKILL_FIELDS:
                rep.err(where, "unknown frontmatter key %r" % k)
        eff = fm.get("effort")
        if eff and eff not in EFFORTS:
            rep.err(where, "bad effort %r" % eff)
        if fm.get("context") and fm.get("context") != "fork":
            rep.err(where, "context must be 'fork'")
        n_lines = text.count("\n")
        if n_lines > 500:
            rep.warn(where, "%d lines; keep SKILL.md under 500 and move detail to references/" % n_lines)
        if len(body.strip()) < 400:
            rep.err(where, "body too thin (%d chars)" % len(body.strip()))
        for link in re.findall(r"\]\(((?:references|scripts|examples|assets)/[^)#\s]+)\)", body):
            if not os.path.exists(os.path.join(sd, link)):
                rep.err(where, "broken link to %s" % link)


META_RE = re.compile(r"^\s*export\s+const\s+meta\s*=\s*(\{.*?\})\s*;?\s*$", re.S | re.M)


def check_workflows(rep: Report) -> None:
    base = os.path.join(paths.REPO, ".claude", "workflows")
    if not os.path.isdir(base):
        rep.warn(".claude/workflows", "missing")
        return
    agents = set(agent_names()) | BUILTIN_AGENTS
    skills = skill_names()
    node = shutil.which("node")
    names = set()
    for f in sorted(os.listdir(base)):
        if not f.endswith(".js"):
            continue
        p = os.path.join(base, f)
        where = _rel(p)
        src = read_text(p)
        if not src.lstrip().startswith("export const meta"):
            rep.err(where, "first statement must be `export const meta = {...}`")
        if re.search(r"\b(Date\.now|Math\.random)\s*\(|new\s+Date\s*\(\s*\)", src):
            rep.err(where, "Date.now()/Math.random()/new Date() throw inside workflows")
        if re.search(r"\bimport\s*\(|^\s*import\s", src, re.M):
            rep.err(where, "imports are not allowed in workflow scripts")
        for mdl in re.findall(r"\bmodel\s*:\s*['\"]([^'\"]+)['\"]", src):
            from . import tiers as _t
            if mdl not in set(_t.alias_models()) | set(_t.allowed_models()):
                rep.err(where, "model %r is not a tier alias (opus/sonnet/haiku) or tier model id" % mdl)
        for at in re.findall(r"agentType\s*:\s*['\"]([^'\"]+)['\"]", src):
            if at not in agents:
                rep.err(where, "agentType %r is not a known agent" % at)
        if node:
            js = r"""
const fs=require('fs');const src=fs.readFileSync(process.argv[1],'utf8');
function out(o){console.log(JSON.stringify(o));process.exit(0)}
const m=src.match(/export\s+const\s+meta\s*=\s*/);if(!m)out({err:'no export const meta'});
function extract(s,from){const i=s.indexOf('{',from);let d=0,q=null;
  for(let j=i;j<s.length;j++){const c=s[j];
    if(q){if(c==='\\'){j++;continue}if(c===q)q=null;continue}
    if(c==='"'||c==="'"||c==='`'){q=c;continue}
    if(c==='{')d++;else if(c==='}'){d--;if(!d)return s.slice(i,j+1)}}
  return null}
const lit=extract(src,m.index);if(!lit)out({err:'unterminated meta literal'});
const bare=lit.replace(/"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'/g,'""');
if(/`|\.\.\.|[A-Za-z_$][\w$]*\s*\(/.test(bare))out({err:'meta must be a pure literal (no templates, spreads or calls)'});
let meta;try{meta=(new Function('return ('+lit+')'))()}catch(e){out({err:'meta literal: '+e.message})}
const body=src.replace(/export\s+const\s+meta\s*=/,'const meta =');
try{const AF=Object.getPrototypeOf(async function(){}).constructor;
  new AF('agent','parallel','pipeline','phase','log','args','budget','workflow',body)}
catch(e){out({err:'syntax: '+e.message})}
out({meta});
"""
            try:
                out = subprocess.run([node, "-e", js, p], capture_output=True, text=True, timeout=20).stdout
                res = json.loads(out.strip().splitlines()[-1]) if out.strip() else {"err": "no output"}
            except (subprocess.SubprocessError, ValueError, IndexError) as e:
                res = {"err": "node check failed: %s" % e}
            if res.get("err"):
                rep.err(where, res["err"])
            else:
                meta = res.get("meta") or {}
                nm = meta.get("name")
                if not nm or not meta.get("description"):
                    rep.err(where, "meta needs name and description")
                elif nm in names:
                    rep.err(where, "duplicate workflow name %r" % nm)
                else:
                    names.add(nm)
                    if nm in RESERVED_WORKFLOW_NAMES:
                        rep.err(where, "workflow name %r collides with a bundled workflow" % nm)
                    if nm in skills:
                        rep.err(where, "workflow name %r collides with a skill of the same name" % nm)
                titles = [p_["title"] for p_ in meta.get("phases", []) if isinstance(p_, dict) and "title" in p_]
                for ph in re.findall(r"phase\(\s*['\"]([^'\"]+)['\"]", src):
                    if titles and ph not in titles:
                        rep.warn(where, "phase(%r) has no meta.phases entry" % ph)
        else:
            rep.warn(where, "node not found; skipped syntax check")


def check_mcp(rep: Report) -> None:
    p = os.path.join(paths.REPO, ".mcp.json")
    try:
        data = read_json(p)
    except (OSError, ValueError) as e:
        rep.err(".mcp.json", "unreadable: %s" % e)
        return
    cat = mcpcat.catalog()
    if not cat:
        rep.err("config/mcp.servers.json", "missing, unreadable or without servers")
    known = agent_names()
    for name, owner in mcpcat.shared().items():
        if name not in cat:
            rep.err("config/mcp.servers.json", "shared server %r is not in servers" % name)
        if owner not in known:
            rep.err("config/mcp.servers.json", "shared server %r has unknown owner agent %r" % (name, owner))
    for name in set(cat) & set(data.get("mcpServers", {})):
        rep.warn(".mcp.json:%s" % name, "also in config/mcp.servers.json: the .mcp.json copy connects for the whole "
                                        "session and defeats lazy loading")
    servers = [(".mcp.json:%s" % n, c) for n, c in data.get("mcpServers", {}).items()]
    servers += [("config/mcp.servers.json:%s" % n, c) for n, c in cat.items()]
    for where, cfg in servers:
        if cfg.get("alwaysLoad") is True:
            rep.warn(where, "alwaysLoad: true loads every tool schema up front (tool search cannot defer it)")
        typ = cfg.get("type", "stdio")
        if typ in ("http", "sse", "ws", "streamable-http"):
            if not cfg.get("url"):
                rep.err(where, "remote server without url")
            hh = cfg.get("headersHelper")
            if hh and "mcp-headers" in hh and not os.access(os.path.join(paths.REPO, "bin", "mcp-headers"), os.X_OK):
                rep.err(where, "bin/mcp-headers is not executable")
        elif typ == "stdio":
            if not cfg.get("command"):
                rep.err(where, "stdio server without command")
            if "mcp-run" in str(cfg.get("command")) and not os.access(os.path.join(paths.REPO, "bin", "mcp-run"), os.X_OK):
                rep.err(where, "bin/mcp-run is not executable")
            if any("mcp-run" in str(a) for a in cfg.get("args", [])) and \
                    not os.access(os.path.join(paths.REPO, "bin", "mcp-run"), os.X_OK):
                rep.err(where, "bin/mcp-run is not executable")
            for a in cfg.get("args", []):
                for rel in re.findall(r'"\$d"/(\S+)', a) if isinstance(a, str) else []:
                    if not os.path.exists(os.path.join(paths.REPO, rel)):
                        rep.err(where, "references missing path %s" % rel)
                if isinstance(a, str) and "${CLAUDE_PROJECT_DIR:-.}/" in a:
                    rel = a.split("${CLAUDE_PROJECT_DIR:-.}/", 1)[1]
                    if rel and not os.path.exists(os.path.join(paths.REPO, rel.split()[0])):
                        rep.err(where, "references missing path %s" % rel)
        else:
            rep.err(where, "unknown type %r" % typ)


def check_settings(rep: Report) -> None:
    p = os.path.join(paths.REPO, ".claude", "settings.json")
    try:
        data = read_json(p)
    except (OSError, ValueError) as e:
        rep.err(".claude/settings.json", "unreadable: %s" % e)
        return
    env = data.get("env", {})
    if str(env.get("ENABLE_TOOL_SEARCH", "")).lower() == "false":
        rep.warn(".claude/settings.json", "ENABLE_TOOL_SEARCH=false loads every MCP tool schema up front")
    if env.get("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH") != env.get("CLAUDE_STACK_MAX_DEPTH"):
        rep.warn(".claude/settings.json", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH and CLAUDE_STACK_MAX_DEPTH differ")
    if env.get("UV_PYTHON") != paths.python_version():
        rep.err(".claude/settings.json", "env.UV_PYTHON %r differs from .python-version %r"
                % (env.get("UV_PYTHON"), paths.python_version()))
    for event, groups in data.get("hooks", {}).items():
        for g in groups:
            for h in g.get("hooks", []):
                cmd = h.get("command", "")
                m = re.search(r"bin/stack\"?\s+hook\s+([a-z-]+)", cmd)
                if m:
                    from .hooks import HANDLERS
                    if m.group(1) not in HANDLERS:
                        rep.err(".claude/settings.json:%s" % event, "unknown hook handler %r" % m.group(1))
    cfg = read_json(os.path.join(paths.CONFIG_DIR, "learning.json"))
    known = set(agent_names())
    for a in cfg.get("agents", {}):
        if a not in known:
            rep.warn("config/learning.json", "bounds for unknown agent %r" % a)


def check_executables(rep: Report) -> None:
    for p in paths.script_files():
        if not os.access(p, os.X_OK):
            rep.err(_rel(p), "starts with #! but is not executable (chmod +x it, or re-run ./install.sh)")


def check_auth(rep: Report) -> None:
    """The stack runs on a Claude subscription; an API credential makes Claude Code bill the API instead."""
    from .managed import MANAGED_ONLY_KEYS
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        if os.environ.get(var):
            rep.warn("environment", "%s is set: Claude Code will bill the API instead of your subscription "
                     "(unset it to use your claude.ai login)" % var)
    for p in (os.path.join(paths.REPO, ".claude", "settings.json"),
              os.path.join(paths.REPO, ".claude", "settings.local.json"),
              os.path.expanduser("~/.claude/settings.json")):
        try:
            data = read_json(p)
        except (OSError, ValueError):
            continue
        for k in MANAGED_ONLY_KEYS:
            if k in data:
                rep.warn(p.replace(os.path.expanduser("~"), "~"), "%s is honoured only from managed settings and "
                         "is ignored here (bin/stack managed-settings --install, as admin)" % k)
        if data.get("apiKeyHelper") or (data.get("env") or {}).get("ANTHROPIC_API_KEY"):
            rep.warn(p.replace(os.path.expanduser("~"), "~"),
                     "configures an API key (apiKeyHelper or env.ANTHROPIC_API_KEY): Claude Code will bill the API "
                     "instead of your subscription")


def run() -> Report:
    rep = Report()
    for fn in (check_agents, check_tiers, check_packs, check_skills, check_workflows, check_mcp, check_settings,
               check_executables, check_auth):
        try:
            fn(rep)
        except Exception as e:  # report, don't crash
            rep.err(fn.__name__, "checker crashed: %r" % e)
    return rep
