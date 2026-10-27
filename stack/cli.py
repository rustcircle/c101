"""`bin/stack` command line.

    stack doctor [--json]                       validate agents, skills, workflows, MCP, hooks
    stack agents list [--json|--markdown]       catalog with model / effort / maxTurns / MCP
    stack agents set NAME key=value ...         edit per-agent tier, model, effort, maxTurns, mcpServers, ...
    stack agents tiers [--apply] [--reset-traits]  render ADVANCED/MEDIUM/LOW_MODEL tiers into frontmatter
    stack keys                                  which stack.env keys are set (names only)
    stack learn ingest [--transcript P | --all [--since-days N]]
    stack learn update [--agent A ...]
    stack learn apply [--dry-run] [--agent A ...]
    stack learn report [--agent A] [--json]
    stack learn run --transcript P              ingest + update + record history (SessionEnd hook)
    stack learn start                           apply pending learned values (SessionStart hook)
    stack learn history [--agent A] [--since-days N] [--by week|day|session] [--json]   trends over time
    stack hook <pre-agent|subagent-stop|session-start|session-end|post-agent|...>
    stack milestone <kind> "<text>"             log a milestone for the user (recorded by the pre-tool hook)
    stack progress [--session SID] [--all] [--follow] [--kinds k1,k2] [--json]   read / tail the milestone log
    stack depth [SESSION_ID]                    spawn statistics recorded by the depth guard
    stack mcp list | enable NAME | disable NAME  manage optional MCP servers (config/mcp.optional.json)
    stack mcp sync [--dry-run]                  re-render inline (lazy) servers in agents from config/mcp.servers.json
    stack packs list                            install packs (skills + agents per pack)
    stack managed-settings [--install]          exact tier-model allowlist for Claude Code managed settings (admin)
    stack packs apply --only a,b | --all [--dry-run]   enable packs for this project (settings.local.json)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List

from . import doctor, frontmatter, hooks, mcpcat, paths

EDITABLE = {"tier", "model", "effort", "maxTurns", "mcpServers", "skills", "color", "autoCompactWindow",
            "tools", "disallowedTools", "description", "memory", "permissionMode", "isolation", "background"}
LIST_KEYS = {"mcpServers", "skills", "tools", "disallowedTools"}


def _agents() -> List[dict]:
    rows = []
    for f in paths.all_agent_files():
        try:
            fm = frontmatter.read(f)
        except (OSError, frontmatter.FrontmatterError):
            continue
        group = os.path.relpath(os.path.dirname(f), os.path.join(paths.REPO, ".claude", "agents"))
        rows.append({
            "name": fm.get("name"), "group": "" if group == "." else group,
            "model": fm.get("model", "inherit"), "effort": fm.get("effort", "-"),
            "maxTurns": fm.get("maxTurns", "-"), "mcpServers": [mcpcat.entry_name(e) for e in doctor._as_list(fm.get("mcpServers"))],
            "skills": doctor._as_list(fm.get("skills")), "autoCompactWindow": fm.get("autoCompactWindow", ""),
            "description": fm.get("description", ""), "path": os.path.relpath(f, paths.REPO),
        })
    return sorted(rows, key=lambda r: (r["group"], r["name"] or ""))


def cmd_agents(a) -> int:
    if a.action == "list":
        rows = _agents()
        if a.json:
            print(json.dumps(rows, indent=2))
        elif a.markdown:
            print("| Group | Agent | Model | Effort | maxTurns | MCP servers | Skills |")
            print("|---|---|---|---|---|---|---|")
            for r in rows:
                print("| %s | `%s` | %s | %s | %s | %s | %s |" % (
                    r["group"], r["name"], r["model"], r["effort"], r["maxTurns"],
                    ", ".join(r["mcpServers"]) or "-", ", ".join(r["skills"]) or "-"))
        else:
            for r in rows:
                print("%-14s %-28s %-7s %-7s %5s  %s" % (r["group"], r["name"], r["model"], r["effort"],
                                                       r["maxTurns"], ",".join(r["mcpServers"])))
        return 0
    if a.action == "main-args":
        from . import tiers
        mt = tiers.main_thread(a.name)
        print("--agent %s --model %s%s" % (a.name, mt["model"], (" --effort %s" % mt["effort"]) if mt["effort"] else ""))
        return 0
    if a.action == "tiers":
        from . import tiers
        ch = tiers.sync(apply=a.apply, reset_traits=a.reset_traits)
        models = tiers.tier_models()
        print("tiers: " + ", ".join("%s=%s" % kv for kv in models.items()))
        for c in ch:
            if c.get("error"):
                print("  %-28s ERROR %s" % (c["agent"], c["error"]))
            else:
                print("  %-28s %-15s %s%s" % (c["agent"], c["tier"], " ".join("%s=%s" % kv for kv in c["updates"].items()),
                                              "" if a.apply else "   (dry run; --apply to write)"))
        if not ch:
            print("  all agents already match their tiers")
        return 1 if any(c.get("error") for c in ch) else 0
    if a.action == "set":
        path = paths.find_agent_file(a.name)
        if not path:
            print("no agent named %s" % a.name, file=sys.stderr)
            return 1
        upd = {}
        from . import tiers
        for kv in list(a.pairs):
            if kv.startswith("tier="):
                try:
                    tiers.set_tier(a.name, kv.split("=", 1)[1])
                except ValueError as e:
                    print(str(e), file=sys.stderr)
                    return 2
                print("tier of %s set to %s (config/models.json)" % (a.name, kv.split("=", 1)[1]))
                a.pairs.remove(kv)
        if not a.pairs:
            return 0
        for kv in a.pairs:
            if "=" not in kv:
                print("expected key=value, got %s" % kv, file=sys.stderr)
                return 2
            k, v = kv.split("=", 1)
            if k == "model":
                from . import tiers as _t
                if v not in _t.allowed_models():
                    print("model must be one of the tier models %s; prefer tier=ADVANCED_MODEL|MEDIUM_MODEL|LOW_MODEL"
                          % ", ".join(_t.allowed_models()), file=sys.stderr)
                    return 2
            if k not in EDITABLE:
                print("refusing to edit %r (editable: %s)" % (k, ", ".join(sorted(EDITABLE))), file=sys.stderr)
                return 2
            if v == "":
                upd[k] = None
            elif k in LIST_KEYS:
                upd[k] = [x.strip() for x in v.split(",") if x.strip()]
                if k == "mcpServers":  # catalog servers are written inline (lazy)
                    upd[k] = mcpcat.render(upd[k], mcpcat.catalog(), a.name, mcpcat.shared())
            else:
                upd[k] = v
        changed = frontmatter.update_file(path, upd)
        print("%s %s" % ("updated" if changed else "unchanged", os.path.relpath(path, paths.REPO)))
        rep = doctor.Report()
        doctor.check_agents(rep)
        mine = [e for e in rep.errors if os.path.relpath(path, paths.REPO) in e]
        for e in mine:
            print("  error: " + e, file=sys.stderr)
        return 1 if mine else 0
    return 2


def cmd_doctor(a) -> int:
    rep = doctor.run()
    if a.json:
        print(json.dumps({"errors": rep.errors, "warnings": rep.warnings}, indent=2))
    else:
        for w in rep.warnings:
            print("warn  " + w)
        for e in rep.errors:
            print("ERROR " + e)
        print("\n%d error(s), %d warning(s); %d agents, %d skills, %d workflows, %d MCP servers" % (
            len(rep.errors), len(rep.warnings), len(paths.all_agent_files()), len(doctor.skill_names()),
            len([f for f in os.listdir(os.path.join(paths.REPO, ".claude", "workflows"))
                 if f.endswith(".js")]) if os.path.isdir(os.path.join(paths.REPO, ".claude", "workflows")) else 0,
            len(doctor.mcp_names() | set(mcpcat.catalog()))), end="")
        extra = doctor.user_optional()
        print(" (+%d optional at user scope: %s)" % (len(extra), ", ".join(extra)) if extra else "")
    return 1 if rep.errors else 0


def cmd_keys(_a) -> int:
    pol = hooks._policy()
    want = pol.get("expected_keys", [])
    optional = pol.get("optional_keys", [])
    missing = set(hooks._missing_keys())
    from . import envfile
    env_path = envfile.env_path()
    print("env file: %s (%s)" % (env_path, "present" if os.path.exists(env_path) else "MISSING"))
    for k in want:
        print("  %-28s %s" % (k, "missing" if k in missing else "set"))
    if optional:
        print("optional:")
        miss2 = set(hooks._missing_keys(optional))
        for k in optional:
            print("  %-28s %s" % (k, "missing" if k in miss2 else "set"))
    return 0


def cmd_learn(a) -> int:
    from .learn import engine
    if a.action == "ingest":
        if a.transcript:
            n = engine.ingest_transcript(a.transcript)
        else:
            n = engine.ingest_all(a.since_days or 0)
        print("ingested %d agent runs" % n)
    elif a.action == "update":
        rep = engine.update(a.agent or None)
        print("updated posteriors for %d agent types" % len(rep["agents"]))
    elif a.action == "apply":
        ch = engine.apply(dry_run=a.dry_run, only=a.agent or None)
        for c in ch:
            print("%s %-28s %s  (%s)" % ("would set" if a.dry_run else "set", c["agent"],
                                         " ".join("%s=%s" % kv for kv in c["updates"].items()),
                                         "; ".join("%s: %s" % kv for kv in c["reasons"].items() if kv[1])))
        if not ch:
            print("no changes")
    elif a.action == "run":
        import fcntl
        os.makedirs(paths.data_dir(), exist_ok=True)
        with open(os.path.join(paths.data_dir(), "learn.lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)  # detached SessionEnd run: wait for any other learner run
            res = engine.run_after_session(a.transcript)
        print(json.dumps(res, indent=2))
    elif a.action == "start":
        for c in engine.start_of_session():
            print("set %-28s %s" % (c["agent"], " ".join("%s=%s" % kv for kv in c["updates"].items())))
    elif a.action == "history":
        rows = engine.history(agent=(a.agent or [None])[0], since_days=a.since_days or 0, by=a.by)
        if a.json:
            print(json.dumps(rows, indent=2))
        elif not rows:
            print("no history yet (%s)" % os.path.join(paths.data_dir(), "history.jsonl"))
        else:
            print("%-24s %-10s %4s %5s %8s %7s %8s %7s  %-14s %s" % (
                "agent", a.by, "sess", "runs", "turns50", "turnsmx", "cap_rate", "errors", "maxTurns", "effort"))
            for name, periods in rows.items():
                for b in periods:
                    mt, ef = b.get("maxTurns") or {}, b.get("effort_setting") or {}
                    print("%-24s %-10s %4d %5d %8s %7d %8.3f %7d  %-14s %s" % (
                        name, b["period"], b["sessions"], b["runs"], b["turns_median"], b["turns_max"],
                        b["cap_rate"], b["tool_errors"], "%s->%s" % (mt.get("current"), mt.get("recommended")),
                        "%s->%s" % (ef.get("current"), ef.get("recommended"))))
    elif a.action == "report":
        p = os.path.join(paths.data_dir(), "recommendations.json")
        if not os.path.exists(p):
            print("no recommendations yet; run `stack learn ingest --all && stack learn update`")
            return 1
        recs = doctor.read_json(p)["agents"]
        if a.agent:
            recs = {k: v for k, v in recs.items() if k in a.agent}
        if a.json:
            print(json.dumps(recs, indent=2))
            return 0
        print("%-26s %4s %6s  %-14s %-22s %-10s %s" % ("agent", "n", "gamma", "maxTurns", "effort", "P(fail)", "tokens out [min..max]"))
        for name, r in sorted(recs.items()):
            if r.get("status") != "ok":
                continue
            mt, ef, tk = r["maxTurns"], r["effort"], r.get("tokens", {}).get("output_tokens", {})
            print("%-26s %4d %6.2f  %-14s %-22s %-10s %s" % (
                name, r["n"], r["window"]["gamma"], "%s->%s" % (mt["current"], mt["recommended"]),
                "%s->%s" % (ef["current"], ef["recommended"]), ef["p_fail_mean"],
                "%s..%s" % (tk.get("min", "-"), tk.get("max", "-"))))
    return 0


def cmd_depth(a) -> int:
    d = os.path.join(paths.data_dir(), "sessions")
    # Spawn stats are <session>.json; budget.py keeps <session>.usage.json in the same directory.
    files = sorted((os.path.join(d, f) for f in os.listdir(d)
                    if f.endswith(".json") and not f.endswith(".usage.json")),
                   key=os.path.getmtime) if os.path.isdir(d) else []
    if a.session:
        files = [f for f in files if os.path.basename(f).startswith(a.session)]
    for f in files[-10:]:
        try:
            st = _load_json(f)
        except (OSError, ValueError):
            continue
        if "spawns" not in st:
            continue
        print("%s spawns=%d max_depth=%d by_depth=%s" % (os.path.basename(f)[:-5], st["spawns"],
                                                         st.get("max_depth_seen", 0), st.get("by_depth", {})))
    return 0


def cmd_milestone(a) -> int:
    """`bin/stack milestone <kind> "<text>"`.  Inside Claude Code the pre-tool hook has already recorded the
    event (with session, agent and depth from the hook payload), so this only validates and confirms; outside
    Claude Code (no CLAUDECODE in the environment) it appends the event itself under session `unknown`."""
    from . import progress
    if a.kind not in progress.AGENT_KINDS:
        print("unknown kind %r; use one of: %s" % (a.kind, ", ".join(progress.AGENT_KINDS)), file=sys.stderr)
        return 2
    text = " ".join(a.text)
    if not progress.sanitise(text, 1):
        print("usage: stack milestone <kind> \"<one line>\"", file=sys.stderr)
        return 2
    if not os.environ.get("CLAUDECODE"):
        try:
            cfg = progress.settings(hooks._policy())
            if cfg.enabled:
                progress.append("unknown", a.kind, text, agent_id="cli", agent_type="cli", cfg=cfg)
        except Exception as exc:  # logging must never make the command fail
            hooks._log_error("milestone-cli", exc)
    print("logged")
    return 0


def cmd_progress(a) -> int:
    from . import progress
    kinds = [k.strip() for k in (a.kinds or "").split(",") if k.strip()] or None
    bad = [k for k in kinds or [] if k not in progress.KINDS]
    if bad:
        print("unknown kind(s) %s; use: %s" % (", ".join(bad), ", ".join(progress.KINDS)), file=sys.stderr)
        return 2

    def emit(ev: dict) -> None:
        print(json.dumps(ev, ensure_ascii=False) if a.json else progress.format_event(ev, with_session=a.all), flush=True)

    if a.follow:
        try:
            progress.follow(a.session, kinds, emit)
        except KeyboardInterrupt:
            pass
        return 0
    events = progress.list_events(a.session, kinds, all_sessions=a.all)
    if not events:
        print("no milestone events yet (%s)" % progress.progress_dir(), file=sys.stderr)
        return 0
    for ev in events:
        emit(ev)
    return 0


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _save_json(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def cmd_mcp(a) -> int:
    proj = os.path.join(paths.REPO, ".mcp.json")
    opt = os.path.join(paths.CONFIG_DIR, "mcp.optional.json")
    settings = os.path.join(paths.REPO, ".claude", "settings.json")
    active = _load_json(proj).get("mcpServers", {})
    optional = _load_json(opt).get("mcpServers", {})
    from . import mcpcat
    lazy = mcpcat.catalog()
    if a.action == "sync":
        changed = mcpcat.sync(dry_run=a.dry_run)
        for f in changed:
            print("%s %s" % ("would update" if a.dry_run else "updated", os.path.relpath(f, paths.REPO)))
        print("%d agent file(s) %s" % (len(changed), "out of date" if a.dry_run else "updated"))
        return 1 if (a.dry_run and changed) else 0
    if a.action == "list":
        for name in sorted(set(active) | set(optional) | set(lazy)):
            src = "lazy" if name in lazy else "active" if name in active else "optional"
            cfg = lazy.get(name) or active.get(name) or optional.get(name)
            where = cfg.get("url") or " ".join([cfg.get("command", "")] + cfg.get("args", []))
            print("%-14s %-9s %s" % (name, src, where))
            note = (optional.get(name) or {}).get("_note")
            if note and name not in active:
                print("%-14s %-9s   %s" % ("", "", note))
        return 0
    if not a.name:
        print("usage: stack mcp enable|disable NAME", file=sys.stderr)
        return 2
    data = _load_json(proj)
    st = _load_json(settings)
    approved = st.setdefault("enabledMcpjsonServers", [])
    allow = st.setdefault("permissions", {}).setdefault("allow", [])
    if a.action == "enable":
        if a.name not in optional and a.name not in active:
            print("unknown server %s (see `stack mcp list`)" % a.name, file=sys.stderr)
            return 1
        if a.name not in active:
            data["mcpServers"][a.name] = {k: v for k, v in optional[a.name].items() if not k.startswith("_")}
        if a.name not in approved:
            approved.append(a.name)
        if "mcp__" + a.name not in allow:
            allow.append("mcp__" + a.name)
    else:
        data["mcpServers"].pop(a.name, None)
        st["enabledMcpjsonServers"] = [x for x in approved if x != a.name]
        st["permissions"]["allow"] = [x for x in allow if x != "mcp__" + a.name]
    _save_json(proj, data)
    _save_json(settings, st)
    print("%sd %s (restart Claude Code or run /mcp to reconnect)" % (a.action, a.name))
    return 0


def cmd_managed(a) -> int:
    from . import managed
    path = a.path or managed.managed_path()
    if not a.install:
        print(json.dumps(managed.allowlist(), indent=2))
        print("\n# merge into %s (needs admin): bin/stack managed-settings --install" % path, file=sys.stderr)
        return 0
    if managed.install(path):
        print("wrote %s: availableModels exact, enforceAvailableModels (other keys kept)" % path)
        return 0
    print("%s is not writable; run it as an administrator:\n  sudo %s managed-settings --install"
          % (path, os.path.join(paths.REPO, "bin", "stack")), file=sys.stderr)
    return 1


def cmd_packs(a) -> int:
    from . import packs
    cfg = packs.load()
    if a.action == "list":
        for name, p in cfg["packs"].items():
            req = ",".join(r for r in p.get("requires", []) if r != "core")
            print("%-18s %3d skills %2d agents %s- %s" % (name, len(p.get("skills", [])), len(p.get("agents", [])),
                                                       ("(+%s) " % req) if req else "", p.get("description", "")))
        return 0
    sel = ["all"] if a.all else [x.strip() for x in (a.only or "").split(",") if x.strip()]
    if not sel:
        print("use --only a,b or --all", file=sys.stderr)
        return 2
    ov = packs.apply_project(sel, dry_run=a.dry_run)
    off = sum(1 for v in ov.values() if v == "off")
    names = sum(1 for v in ov.values() if v == "name-only")
    print("%s packs %s: %d skills off, %d listed name-only (granular)%s" % (
        "would apply" if a.dry_run else "applied", ",".join(packs.resolve(sel, cfg)), off, names,
        "" if a.dry_run else " -> .claude/settings.local.json; run /reload-skills"))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["install"]:
        from . import install
        return install.main(argv[1:])
    p = argparse.ArgumentParser(prog="stack", description="Claude Code agent stack tooling")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor")
    d.add_argument("--json", action="store_true")
    d.set_defaults(fn=cmd_doctor)

    ag = sub.add_parser("agents")
    ag_sub = ag.add_subparsers(dest="action", required=True)
    al = ag_sub.add_parser("list")
    al.add_argument("--json", action="store_true")
    al.add_argument("--markdown", action="store_true")
    ama = ag_sub.add_parser("main-args")
    ama.add_argument("name")
    ati = ag_sub.add_parser("tiers")
    ati.add_argument("--apply", action="store_true")
    ati.add_argument("--reset-traits", action="store_true")
    ase = ag_sub.add_parser("set")
    ase.add_argument("name")
    ase.add_argument("pairs", nargs="+")
    ag.set_defaults(fn=cmd_agents)

    k = sub.add_parser("keys")
    k.set_defaults(fn=cmd_keys)

    le = sub.add_parser("learn")
    le.add_argument("action", choices=["ingest", "update", "apply", "report", "run", "start", "history"])
    le.add_argument("--transcript")
    le.add_argument("--all", action="store_true")
    le.add_argument("--since-days", type=float)
    le.add_argument("--agent", action="append")
    le.add_argument("--dry-run", action="store_true")
    le.add_argument("--json", action="store_true")
    le.add_argument("--by", choices=["week", "day", "session"], default="week")
    le.set_defaults(fn=cmd_learn)

    h = sub.add_parser("hook")
    h.add_argument("name")
    h.set_defaults(fn=lambda a: hooks.main(a.name))

    mi = sub.add_parser("milestone", help="log a milestone for the user (see docs/MILESTONES.md)")
    mi.add_argument("kind")
    mi.add_argument("text", nargs="*")
    mi.set_defaults(fn=cmd_milestone)

    pg = sub.add_parser("progress", help="print or follow the milestone log")
    pg.add_argument("--session", help="session id (default: the newest session)")
    pg.add_argument("--all", action="store_true", help="events of every session, oldest first")
    pg.add_argument("--follow", "-f", action="store_true", help="keep printing new events")
    pg.add_argument("--kinds", help="comma-separated kinds to show")
    pg.add_argument("--json", action="store_true")
    pg.set_defaults(fn=cmd_progress)

    sub.add_parser("install", help="wire the stack into ~/.claude (see stack/install.py)")

    dp = sub.add_parser("depth")
    dp.add_argument("session", nargs="?")
    dp.set_defaults(fn=cmd_depth)

    pk = sub.add_parser("packs")
    pk.add_argument("action", choices=["list", "apply"])
    pk.add_argument("--only")
    pk.add_argument("--all", action="store_true")
    pk.add_argument("--dry-run", action="store_true")
    pk.set_defaults(fn=cmd_packs)

    ms = sub.add_parser("managed-settings")
    ms.add_argument("--install", action="store_true")
    ms.add_argument("--path", help="managed settings file (default: the OS location)")
    ms.set_defaults(fn=cmd_managed)

    mc = sub.add_parser("mcp")
    mc.add_argument("action", choices=["list", "enable", "disable", "sync"])
    mc.add_argument("name", nargs="?")
    mc.add_argument("--dry-run", action="store_true")
    mc.set_defaults(fn=cmd_mcp)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
