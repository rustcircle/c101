"""One-time app-side setup for the Adobe desktop-app MCP servers (`./install.sh --adobe`).

Everything lands under ~/.claude/stack-data/adobe/ (the paths the config/mcp.optional.json entries point at):

  photoshop      clone mikechambers/adb-mcp at a pinned commit, `npm install` its socket proxy, run the proxy
                 (ws://localhost:3001) as the LaunchAgent com.c101.adb-proxy, pre-fetch the server's uv deps
  after-effects  clone Dakkshin/after-effects-mcp at a pinned commit, npm install + build, copy its
                 mcp-bridge-auto.jsx into <After Effects>/Scripts/ScriptUI Panels (direct copy, sudo cp fallback)
  indesign       reuse the adb-mcp clone and proxy (as photoshop), pre-fetch the server's uv deps, and remove the
                 old com.c101.indesign-bridge LaunchAgent if an earlier install left one
  premiere-pro   npm-install premiere-pro-mcp (pinned) and install its signed CEP panel
                 (artifacts/MCPBridgeCEP.zxp) with Adobe's UnifiedPluginInstallerAgent
  illustrator    reuse the adb-mcp clone and proxy, link its CEP panel (cep/com.mikechambers.ai) into
                 ~/Library/Application Support/Adobe/CEP/extensions and set PlayerDebugMode for CSXS 12

Steps are idempotent and honour --dry-run. What cannot be scripted (loading a UXP plugin in UXP Developer Tools,
an After Effects preference, clicking Connect, macOS automation prompts) is printed at the end. `--no-adobe` unloads
and removes the LaunchAgents and the user-scope registrations; the checkouts stay (delete the folder yourself).
Stdlib only.
"""
from __future__ import annotations

import glob
import json
import os
import plistlib
import shutil
import subprocess
import sys
from typing import Callable, Dict, List, Optional

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".claude", "stack-data", "adobe")
AGENTS_DIR = os.path.join(HOME, "Library", "LaunchAgents")
LOGS = os.path.join(ROOT, "logs")
UPIA = ("/Library/Application Support/Adobe/Adobe Desktop Common/RemoteComponents/UPI/UnifiedPluginInstallerAgent/"
        "UnifiedPluginInstallerAgent.app/Contents/macOS/UnifiedPluginInstallerAgent")

# Pinned sources: bump only after reading the diff, these run code inside your apps.
REPOS = {
    "adb-mcp": ("https://github.com/mikechambers/adb-mcp", "afe5d09cdbdd4cc60434dce6b3f46fdafe15a21c"),
    "after-effects-mcp": ("https://github.com/Dakkshin/after-effects-mcp", "88d5fbf08b7ae9f015ee98e5f8c4904095cf8202"),
}
PACKAGES = {"premiere-pro": ("premiere-pro-mcp", "1.25.0")}
PS_DEPS = ["mcp[cli]", "fonttools", "python-socketio", "requests", "websocket-client>=1.8.0", "pillow>=11.2.1",
           "numpy>=2.2.6"]
PY = "3.13"  # the stack's uv-managed CPython (.python-version); the photoshop entry pins the same
LABELS = {"photoshop": "com.c101.adb-proxy"}
LEGACY_LABELS = ["com.c101.indesign-bridge"]  # the old indesign-nutria-mcp JXA bridge; removed on sight
CEP_DIR = os.path.join(HOME, "Library", "Application Support", "Adobe", "CEP", "extensions")
CSXS = "12"  # CEP runtime of Illustrator 2024+ (cep/com.mikechambers.ai/CSXS/manifest.xml)

# Package managers' bin directories that a GUI-launched Claude Code may not have on PATH (nix first).
EXTRA_PATH = [
    os.path.join(HOME, ".nix-profile", "bin"),
    "/etc/profiles/per-user/%s/bin" % os.environ.get("USER", ""),
    "/run/current-system/sw/bin",
    "/nix/var/nix/profiles/default/bin",
    os.path.join(HOME, ".local", "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
]

MANUAL = {
    "photoshop": [
        "Photoshop > Settings > Plugins: tick Enable Developer Mode, restart Photoshop",
        "UXP Developer Tools (Creative Cloud > Apps) > Add Plugin > %s > Load; then click Connect in the "
        "plugin panel (Load again after each Photoshop restart)" % os.path.join(ROOT, "adb-mcp", "uxp", "ps",
                                                                                 "manifest.json"),
    ],
    "after-effects": [
        "After Effects > Settings > Scripting & Expressions: tick Allow Scripts to Write Files and Access Network",
        "Window > mcp-bridge-auto.jsx, tick Auto-run commands, keep the panel open",
    ],
    "indesign": [
        "UXP Developer Tools > Add Plugin > %s > Load, then Plugins > InDesign MCP Agent in InDesign "
        "(Load again after each InDesign restart)" % os.path.join(ROOT, "adb-mcp", "uxp", "id", "manifest.json"),
    ],
    "premiere-pro": ["restart Premiere Pro, then Window > Extensions > MCP for Adobe Premiere Pro"],
    "illustrator": ["restart Illustrator, then Window > Extensions > Illustrator MCP Agent (keep the panel open)"],
}


def tool_env() -> Dict[str, str]:
    env = dict(os.environ)
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    env["PATH"] = os.pathsep.join([p for p in EXTRA_PATH if p not in parts] + parts)
    return env


def which(name: str) -> Optional[str]:
    """Stable (non store-resolved) path, so a nix upgrade does not break a LaunchAgent."""
    return shutil.which(name, path=tool_env()["PATH"])


def _run(cmd: List[str], cwd: Optional[str] = None, interactive: bool = False) -> None:
    kw = {} if interactive else {"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT, "text": True}
    r = subprocess.run(cmd, cwd=cwd, env=tool_env(), **kw)
    if r.returncode != 0:
        tail = "" if interactive else "\n".join((r.stdout or "").strip().splitlines()[-8:])
        raise RuntimeError("%s failed (exit %d)%s" % (" ".join(cmd[:4]), r.returncode, ":\n" + tail if tail else ""))


def _git_head(d: str) -> str:
    r = subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True, env=tool_env())
    return r.stdout.strip() if r.returncode == 0 else ""


def checkout(ctx, name: str) -> str:
    url, sha = REPOS[name]
    d = os.path.join(ROOT, name)
    if _git_head(d) == sha:
        return d

    def fetch():
        if not os.path.isdir(os.path.join(d, ".git")):
            os.makedirs(d, exist_ok=True)
            _run(["git", "init", "-q", d])
            _run(["git", "-C", d, "remote", "add", "origin", url])
        _run(["git", "-C", d, "fetch", "-q", "--depth", "1", "origin", sha])
        _run(["git", "-C", d, "checkout", "-q", "--detach", "FETCH_HEAD"])
    ctx.do("fetch %s at %s into %s" % (url, sha[:12], d), fetch)
    return d


def npm_package(ctx, server: str) -> str:
    pkg, ver = PACKAGES[server]
    prefix = os.path.join(ROOT, server)
    d = os.path.join(prefix, "node_modules", pkg)
    try:
        with open(os.path.join(d, "package.json"), encoding="utf-8") as fh:
            if json.load(fh).get("version") == ver:
                return d
    except (OSError, ValueError):
        pass
    ctx.do("npm install %s@%s into %s" % (pkg, ver, prefix),
           lambda: (os.makedirs(prefix, exist_ok=True),
                    _run(["npm", "install", "--prefix", prefix, "--omit=dev", "--no-fund", "--no-audit",
                          "%s@%s" % (pkg, ver)])))
    return d


def launch_agent(ctx, label: str, args: List[str], cwd: str, env: Optional[Dict[str, str]] = None) -> None:
    """Write ~/Library/LaunchAgents/<label>.plist (KeepAlive) and (re)load it when it changed or is not loaded."""
    path = os.path.join(AGENTS_DIR, label + ".plist")
    spec = {"Label": label, "ProgramArguments": args, "WorkingDirectory": cwd, "RunAtLoad": True,
            "KeepAlive": True, "ThrottleInterval": 30,
            "StandardOutPath": os.path.join(LOGS, label + ".log"),
            "StandardErrorPath": os.path.join(LOGS, label + ".log"),
            "EnvironmentVariables": dict({"PATH": tool_env()["PATH"]}, **(env or {}))}
    data = plistlib.dumps(spec)
    try:
        with open(path, "rb") as fh:
            same = fh.read() == data
    except OSError:
        same = False
    domain = "gui/%d" % os.getuid()
    loaded = subprocess.run(["launchctl", "print", "%s/%s" % (domain, label)],
                            capture_output=True).returncode == 0
    if same and loaded:
        return

    def write_and_load():
        os.makedirs(AGENTS_DIR, exist_ok=True)
        os.makedirs(LOGS, exist_ok=True)
        with open(path + ".tmp", "wb") as fh:
            fh.write(data)
        os.replace(path + ".tmp", path)
        subprocess.run(["launchctl", "bootout", "%s/%s" % (domain, label)], capture_output=True)
        _run(["launchctl", "bootstrap", domain, path])
    ctx.do("%s LaunchAgent %s (%s)" % ("reload" if os.path.exists(path) else "install", label, " ".join(args[-1:])),
           write_and_load)


def remove_agents(ctx, labels: Optional[List[str]] = None) -> None:
    domain = "gui/%d" % os.getuid()
    for label in labels if labels is not None else list(LABELS.values()) + LEGACY_LABELS:
        path = os.path.join(AGENTS_DIR, label + ".plist")
        if os.path.exists(path):
            ctx.do("unload and remove LaunchAgent %s" % label,
                   lambda label=label, path=path: (
                       subprocess.run(["launchctl", "bootout", "%s/%s" % (domain, label)], capture_output=True),
                       os.unlink(path)))


def _same_file(a: str, b: str) -> bool:
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def newest_app(prefix: str) -> Optional[str]:
    apps = sorted(glob.glob("/Applications/%s *" % prefix))
    return os.path.basename(apps[-1]) if apps else None


# ---- per-app setup ------------------------------------------------------------------------------------------

def adb_mcp(ctx) -> str:
    """Clone adb-mcp, run its socket proxy (one LaunchAgent shared by photoshop, indesign and illustrator) and
    pre-fetch the servers' uv deps. Returns the checkout."""
    d = checkout(ctx, "adb-mcp")
    proxy = os.path.join(d, "adb-proxy-socket")
    if ctx.dry or not os.path.isdir(os.path.join(proxy, "node_modules")):
        ctx.do("npm install in %s" % proxy, lambda: _run(["npm", "install", "--no-fund", "--no-audit"], cwd=proxy))
    launch_agent(ctx, LABELS["photoshop"], [which("node") or "node", "proxy.js"], proxy)
    cmd = ["uv", "run", "--quiet", "--python", PY, "--directory", os.path.join(d, "mcp")]
    for dep in PS_DEPS:
        cmd += ["--with", dep]
    mark = os.path.join(ROOT, ".photoshop-deps-%s-py%s" % (REPOS["adb-mcp"][1][:12], PY))
    if ctx.dry or not os.path.exists(mark):
        ctx.do("pre-fetch the adb-mcp servers' Python deps (first MCP start stays under the connect timeout)",
               lambda: (_run(cmd + ["python", "-c", "import mcp, socketio, numpy, PIL"]), open(mark, "w").close()))
    return d


def setup_photoshop(ctx) -> None:
    adb_mcp(ctx)


def setup_after_effects(ctx) -> None:
    if not newest_app("Adobe After Effects"):
        raise RuntimeError("no /Applications/Adobe After Effects * found")
    d = checkout(ctx, "after-effects-mcp")
    if ctx.dry or not os.path.exists(os.path.join(d, "build", "index.js")):
        ctx.do("npm install && npm run build in %s" % d,
               lambda: (_run(["npm", "install", "--no-fund", "--no-audit"], cwd=d),
                        _run(["npm", "run", "build"], cwd=d)))
    src = os.path.join(d, "build", "scripts", "mcp-bridge-auto.jsx")
    dst = os.path.join("/Applications", newest_app("Adobe After Effects"), "Scripts", "ScriptUI Panels",
                       "mcp-bridge-auto.jsx")
    if not ctx.dry and _same_file(src, dst):
        return
    # Copy it ourselves: upstream install-bridge.js only knows a hardcoded list of AE years (2021-2026) and fails
    # on newer installs. The folder is usually root-owned, so fall back to an interactive `sudo cp`.
    ctx.do("copy mcp-bridge-auto.jsx into %s (may ask for your password)" % os.path.dirname(dst),
           lambda: _copy_privileged(src, dst))


def _copy_privileged(src: str, dst: str) -> None:
    try:
        shutil.copyfile(src, dst)
    except PermissionError:
        _run(["sudo", "cp", src, dst], interactive=True)


def setup_indesign(ctx) -> None:
    if not newest_app("Adobe InDesign"):
        raise RuntimeError("no /Applications/Adobe InDesign * found")
    adb_mcp(ctx)
    remove_agents(ctx, LEGACY_LABELS)


def setup_premiere(ctx) -> None:
    d = npm_package(ctx, "premiere-pro")
    zxp = os.path.join(d, "artifacts", "MCPBridgeCEP.zxp")
    if not os.access(UPIA, os.X_OK):
        raise RuntimeError("Adobe UnifiedPluginInstallerAgent not found (install Creative Cloud); then install %s "
                           "by hand, or run `npx premiere-pro-mcp@%s --install-cep`" % (zxp, PACKAGES["premiere-pro"][1]))
    mark = os.path.join(ROOT, "premiere-pro", ".cep-installed-" + PACKAGES["premiere-pro"][1])
    if not ctx.dry and os.path.exists(mark):
        return
    ctx.do("install the Premiere CEP panel %s with Adobe UPIA" % os.path.basename(zxp),
           lambda: (_run([UPIA, "--install", zxp], interactive=True), open(mark, "w").close()))


def setup_illustrator(ctx) -> None:
    if not newest_app("Adobe Illustrator"):
        raise RuntimeError("no /Applications/Adobe Illustrator * found")
    d = adb_mcp(ctx)
    src = os.path.join(d, "cep", "com.mikechambers.ai")
    link = os.path.join(CEP_DIR, "com.mikechambers.ai")
    if ctx.dry or os.path.realpath(link) != os.path.realpath(src):
        def do_link():
            os.makedirs(CEP_DIR, exist_ok=True)
            if os.path.islink(link):
                os.unlink(link)
            elif os.path.exists(link):
                raise RuntimeError("%s exists and is not a link; move it aside and re-run" % link)
            os.symlink(src, link)
        ctx.do("link the Illustrator CEP panel into %s" % CEP_DIR, do_link)
    dbg = subprocess.run(["defaults", "read", "com.adobe.CSXS." + CSXS, "PlayerDebugMode"],
                         capture_output=True, text=True).stdout.strip()
    if ctx.dry or dbg != "1":
        ctx.do("allow unsigned CEP panels (defaults write com.adobe.CSXS.%s PlayerDebugMode 1)" % CSXS,
               lambda: _run(["defaults", "write", "com.adobe.CSXS." + CSXS, "PlayerDebugMode", "1"]))


SETUP: Dict[str, Callable] = {"photoshop": setup_photoshop, "after-effects": setup_after_effects,
                              "indesign": setup_indesign, "premiere-pro": setup_premiere,
                              "illustrator": setup_illustrator}
NEEDS = {"photoshop": ["git", "node", "npm", "uv"], "after-effects": ["git", "node", "npm"],
         "indesign": ["git", "node", "npm", "uv"], "premiere-pro": ["node", "npm"],
         "illustrator": ["git", "node", "npm", "uv"]}


def setup(ctx, names: List[str]) -> List[str]:
    """Run the setup for each server; returns the names that failed. Prints the remaining manual steps."""
    if sys.platform != "darwin":
        print("Adobe setup skipped: macOS only (servers are registered; see docs/reference/mcp.md)")
        return []
    failed = []
    for name in names:
        if name not in SETUP:
            continue
        missing = [t for t in NEEDS[name] if not which(t)]
        try:
            if missing:
                raise RuntimeError("missing %s on PATH (nix: add them to your profile)" % ", ".join(missing))
            SETUP[name](ctx)
        except Exception as e:  # keep going: one app's failure must not block the others
            failed.append(name)
            print("  %s setup FAILED: %s" % (name, e))
    steps = [(n, s) for n in names if n in MANUAL and n not in failed for s in MANUAL[n]]
    if steps:
        print("\nAdobe: finish in the apps (one time):")
        for n, s in steps:
            print("  %-13s %s" % (n, s))
        print("then restart Claude Code (or /mcp) so the servers reconnect; `bin/stack doctor` checks the files.")
    return failed
