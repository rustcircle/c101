"""Prompt-injection tripwire for untrusted web content, and the risky-action classifier.

Stdlib only: it runs inside hooks on every web-tool result and every risky tool call.

* ``scan(text)`` scores tool output against heuristic rules: text addressed to an AI agent,
  instruction overrides, fake role or tool-call markup, requests to send secrets, secret
  paths, exfiltration-shaped URLs, hidden or smuggled characters, pipe-to-shell commands,
  persona switches and secrecy demands. Levels: ``low`` (< medium), ``medium``, ``high``.
* ``risky_action(tool, tool_input, project_dir)`` names what a tool call would do that an
  injected instruction could abuse (network egress or pipe-to-shell in Bash, secret reads,
  git push, registry pushes, writes outside ``.stack/``, typing into web forms), or returns None.
* ``outward_bash(cmd, ...)`` names a git push (force/delete pushes flagged as destructive), a registry write
  or a change to a non-local Kubernetes cluster; the pre-tool hook asks the user before any agent runs one
  (``config/policy.json`` ``outward_actions``).
* Taint state (``mark`` / ``taint_of``): which agents in a session have ingested flagged
  content, kept in ``<data>/sessions/<session>.taint.json``.

These are tripwires, not a guarantee: paraphrases, other languages and text inside images get
through. The containment comes from the tool limits on web-reading agents (see
``config/policy.json`` ``web_content``), which this module helps enforce.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import time
import unicodedata
from typing import Any, Dict, List, NamedTuple, Optional

from . import paths

MAX_SCAN_CHARS = 400_000

# (rule, weight, compiled regex). A rule counts once per scan; weights add up.
_I = re.I | re.M
RULES = [
    ("instruction-override", 4, re.compile(
        r"\b(ignore|disregard|forget|override|bypass)\b(?:[^.\n]|\.(?=\S)){0,40}\b(previous|prior|above|earlier|all|any|your|the|these)\b"
        r"(?:[^.\n]|\.(?=\S)){0,30}\b(instructions?|prompts?|rules|directions|guidelines|guardrails|context)\b", _I)),
    ("addressed-to-ai", 3, re.compile(
        r"\b(if you are an? (ai|llm|language model|assistant|agent|bot)|(attention|note|message|instructions?) (to|for) "
        r"(the )?(ai|llm|assistant|agent|model|claude|chatgpt|gpt)s?|(dear|hey|hello) (ai|assistant|agent|llm|claude|model)|"
        r"(ai|llm) (agents?|assistants?|models?|crawlers?)[ ,]+(must|should|are (required|instructed)|please))\b", _I)),
    ("new-instructions", 3, re.compile(
        r"\b(new|updated|real|actual|hidden|secret|true|system|developer)\s+(instructions?|directives?|task|objective|"
        r"orders|prompt)\s*[:\-]", _I)),
    # chat-template tokens and role tags also appear in AI documentation, so alone they stay below medium
    ("role-markup", 2, re.compile(
        r"(<\|?(system|im_start|im_end|assistant|user)\|?>|\[/?INST\]|</?(system|system-reminder|assistant|tool_call|"
        r"tool_use|instructions?)>)", _I)),
    ("tool-call-markup", 4, re.compile(r"(<invoke\s+name=|<function_calls>|<parameter\s+name=|\"tool_use\"\s*:)", _I)),
    ("send-secrets", 4, re.compile(
        r"\b(send|post|upload|exfiltrate|forward|leak|transmit|email|include|append|embed|paste|share)\b(?:[^.\n]|\.(?=\S)){0,60}"
        r"\b(api[_ -]?keys?|access tokens?|tokens|credentials?|passwords?|secrets?|env(ironment)? (vars?|variables)|"
        r"stack\.env|ssh keys?|private keys?|cookies|session ids?|system prompt|conversation|chat history)\b", _I)),
    ("secret-paths", 2, re.compile(
        r"(\.ssh/|\.aws/|\.gnupg/|\.claude/stack\.env|\bstack\.env\b|\bid_(rsa|ed25519|ecdsa)\b|\.netrc\b|\.npmrc\b|"
        r"\bkeychain\b|security find-(generic|internet)-password)", _I)),
    ("pipe-to-shell", 2, re.compile(
        r"((curl|wget)\b[^\n|]{0,200}\|\s*(sudo\s+)?(ba|z|da)?sh\b|\bbase64\s+(-d|--decode)\b[^\n]{0,80}\|\s*(ba|z)?sh\b|"
        r"\beval\s*\$\(\s*(curl|wget)\b)", _I)),
    ("exfil-url", 3, re.compile(
        r"(https?://[^\s)\"'<>]*(\{\{|\$\{|%7B%7B|%24%7B)[^\s)\"'<>]*|"
        r"!\[[^\]]*\]\(https?://[^)\s]*\?[^)\s]*=(\{|\$|%7B|[A-Za-z0-9+/_-]{32,})[^)\s]*\))", _I)),
    ("persona-switch", 3, re.compile(
        r"(\byou are now (a|an|in|the)\b|\bfrom now on,? you (are|will|must)\b|\b(developer|god|jailbreak|dan) mode\b|"
        r"\bact as an? (unrestricted|unfiltered|jailbroken)\b)", _I)),
    ("secrecy-demand", 3, re.compile(
        r"\b(do not|don't|never) (tell|inform|mention|reveal|show|alert|notify)\b(?:[^.\n]|\.(?=\S)){0,30}\b(the )?(user|human|"
        r"operator|owner|anyone)\b", _I)),
    ("ascii-smuggling", 4, re.compile("[\U000E0000-\U000E007F]")),
    ("zero-width-run", 2, re.compile("[​‌‍⁠﻿]{3,}")),
]


class Scan(NamedTuple):
    score: int
    level: str  # "low" | "medium" | "high"
    hits: List[str]  # rule names, in rule order
    digest: str  # sha256 of the scanned text (for logs; the text itself is never stored)


def thresholds(pol: Optional[dict] = None) -> Dict[str, int]:
    wc = (pol or {}).get("web_content") or {}
    return {"medium": int(wc.get("medium", 3)), "high": int(wc.get("high", 6))}


_B64 = re.compile(r"^[A-Za-z0-9+/\s]{256,}={0,2}$")


def _is_media(block: dict, value: Any) -> bool:
    """A real image/audio content block (screenshot bytes): skipped, everything else is scanned."""
    mime = str(block.get("mimeType") or block.get("mime_type") or "")
    return (block.get("type") in ("image", "audio") and mime.startswith(("image/", "audio/"))
            and isinstance(value, str) and bool(_B64.match(value[:4096])))


def flatten(obj: Any, limit: int = MAX_SCAN_CHARS) -> str:
    """Every string leaf of a tool response (MCP content blocks, dicts, lists), up to ``limit`` chars."""
    out: List[str] = []
    size = 0

    def walk(o: Any) -> None:
        nonlocal size
        if size >= limit:
            return
        if isinstance(o, str):
            out.append(o[: limit - size])
            size += len(out[-1])
        elif isinstance(o, dict):
            for k, v in o.items():
                if not (k == "data" and _is_media(o, v)):
                    walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)

    walk(obj)
    return "\n".join(out)


def scan(text: str, pol: Optional[dict] = None) -> Scan:
    text = text[:MAX_SCAN_CHARS]
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
    raw_hits = {name for name, _, rx in RULES if name in ("ascii-smuggling", "zero-width-run") and rx.search(text)}
    # NFKC folds full-width and compatibility forms; dropping zero-width characters defeats w​o​r​d splitting
    norm = unicodedata.normalize("NFKC", text)
    norm = re.sub("[​‌‍⁠﻿\U000E0000-\U000E007F]", "", norm)
    hits = [name for name, _, rx in RULES if name in raw_hits or (name not in ("ascii-smuggling", "zero-width-run") and rx.search(norm))]
    weights = {name: w for name, w, _ in RULES}
    score = sum(weights[h] for h in hits)
    th = thresholds(pol)
    level = "high" if score >= th["high"] else "medium" if score >= th["medium"] else "low"
    return Scan(score, level, hits, digest)


# --- risky actions ------------------------------------------------------------------------------

EGRESS_CMDS = {"curl", "wget", "nc", "ncat", "netcat", "socat", "telnet", "ssh", "scp", "sftp", "ftp", "rsync",
               "aria2c", "httpie", "xh", "lynx", "w3m"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
INTERPRETERS = {"python", "python3", "node", "perl", "ruby", "php", "deno", "bun"}
WRAPPERS = {"sudo", "env", "time", "nohup", "exec", "command", "builtin", "nice", "timeout", "xargs", "stdbuf"}
_SEGMENT_SPLIT = re.compile(r"\|\||&&|[;|&\n]|\$\(|`")
_INLINE_NET = re.compile(r"\b(urllib|requests|httpx|aiohttp|socket|http\.client|fetch\s*\(|net/http|LWP::|fsockopen|"
                         r"URLSession|Net::HTTP|Deno\.connect)", re.I)
_SECRET_PATH = re.compile(r"((^|[\s/'\"=~])\.(ssh|aws|gnupg|netrc|npmrc|pypirc|git-credentials)\b|\bstack\.env\b|"
                          r"(^|[\s/'\"=])\.env(\.[A-Za-z0-9_-]+)?(\s|$|['\"])|\bid_(rsa|ed25519|ecdsa)\b|"
                          r"\bcredentials\.json\b|\bsecurity\s+find-(generic|internet)-password\b)", re.I)


_ARG_FLAGS = {"-u", "-g", "-C", "-p", "-n", "-s", "-k", "-o", "-e", "--user", "--group", "--signal", "--kill-after"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_DURATION = re.compile(r"^\d+(\.\d+)?[smhd]?$")


def _segments(cmd: str) -> List[List[str]]:
    """Command words of each pipeline/list segment; wrappers (sudo, env, timeout...), their options
    and VAR=value assignments are skipped so the head is the program that actually runs."""
    out = []
    for seg in _SEGMENT_SPLIT.split(cmd):
        words = seg.strip().split()
        i = 0
        while i < len(words):
            w = words[i]
            if _ASSIGN.match(w):
                i += 1
                continue
            if os.path.basename(w) in WRAPPERS and i + 1 < len(words):
                i += 1
                while i < len(words) and (words[i].startswith("-") or _DURATION.match(words[i]) or _ASSIGN.match(words[i])):
                    i += 2 if words[i] in _ARG_FLAGS else 1
                continue
            break
        words = words[i:]
        if words:
            out.append([os.path.basename(words[0])] + words[1:])
    return out


def risky_bash(cmd: str) -> Optional[str]:
    segs = _segments(cmd)
    heads = [w[0] for w in segs]
    # pipe into a shell, or into an interpreter reading its program from stdin
    for i, w in enumerate(segs[1:], 1):
        if "|" in cmd and (w[0] in SHELLS or (w[0] in INTERPRETERS and (len(w) == 1 or w[1] == "-"))):
            return "pipe-to-shell (output of another command executed by %s)" % w[0]
    for w in segs:
        if w[0] in SHELLS and "-c" in w[1:]:
            inner = " ".join(w[w.index("-c") + 1:]).strip().strip("'\"")
            why = risky_bash(inner) if inner and inner != cmd else None
            if why:
                return why + " (inside %s -c)" % w[0]
        if w[0] == "eval":
            return "eval of constructed commands"
    if any(h in EGRESS_CMDS for h in heads):
        return "network egress from Bash (%s)" % next(h for h in heads if h in EGRESS_CMDS)
    if any(w[0] in INTERPRETERS for w in segs) and _INLINE_NET.search(cmd):
        return "network access from an inline interpreter"
    for w in segs:
        sub, args = _git_sub(w)
        if sub == "push" or (sub == "remote" and args[:1] and args[0] in ("add", "set-url")):
            return "git push / remote change"
    if _SECRET_PATH.search(cmd) or any(w[0] in ("printenv",) or (w[0] in ("env", "set", "export") and len(w) == 1)
                                       for w in segs):
        return "reading credentials or environment secrets"
    for w in segs:
        if w[0] == "rm" and any(a.startswith("-") and ("r" in a or "R" in a) for a in w[1:]):
            targets = [a for a in w[1:] if not a.startswith("-")]
            if any(".stack/" not in t and not t.startswith(".stack") for t in targets):
                return "recursive delete outside .stack/"
    for w in segs:
        why = _registry_write(w)
        if why:
            return why
    return None


# --- outward container actions: registry writes and changes to non-local clusters -----------------
# These leave the machine for good (an image in a registry, a keyless signature in a public transparency log,
# a change to a shared cluster), so the pre-tool hook asks the user before any agent runs them. Mirrors the
# container-craft skill's safety model (section 2); the agent's prompt is the first line, this is the backstop.

LOCAL_KUBE_CONTEXTS = ("kind-*", "k3d-*", "minikube", "docker-desktop", "rancher-desktop", "orbstack")
_ENGINES = {"docker", "podman", "nerdctl", "finch"}
_KUBE_CLIS = {"kubectl", "oc", "kubecolor"}
_KUBE_READ = {"get", "describe", "logs", "events", "top", "explain", "api-resources", "api-versions", "version",
              "diff", "wait", "completion", "kustomize", "cluster-info", "options", "help"}
_KUBE_CONFIG_READ = {"view", "get-contexts", "current-context", "get-clusters", "get-users"}
_HELM_CLUSTER_WRITE = {"install", "upgrade", "uninstall", "delete", "del", "un", "rollback", "test"}
# Global flags that take a separate value, so the verb is found after them.
_VALUE_FLAGS = {"--context", "--kube-context", "--kubeconfig", "-n", "--namespace", "--cluster", "--user", "-s",
                "--server", "--token", "--as", "--as-group", "--request-timeout", "--log-level", "-H", "--host",
                "-c", "--connection", "--url", "--registry-config", "--repository-config", "--repository-cache"}
_LOCAL_REF = ("oci:", "oci-archive:", "dir:", "docker-archive:", "docker-daemon:", "containers-storage:")
_KUBECONFIG_ASSIGN = re.compile(r"(?:^|[\s;&|(])KUBECONFIG=(['\"]?)([^\s'\";&|]+)\1")
_CURRENT_CONTEXT = re.compile(r"^current-context:\s*['\"]?([^'\"\s#]+)", re.M)


def _flag(w: List[str], *names: str) -> Optional[str]:
    """Value of the last occurrence of any of the flags (kubectl and helm let a later flag win)."""
    val = None
    for i, a in enumerate(w):
        for n in names:
            if a == n and i + 1 < len(w):
                val = w[i + 1]
            elif a.startswith(n + "="):
                val = a[len(n) + 1:]
    return val


def _positional(w: List[str]) -> List[str]:
    """Words after the program that are not flags or flag values."""
    out, i = [], 1
    while i < len(w):
        a = w[i]
        if a.startswith("-"):
            i += 2 if a in _VALUE_FLAGS else 1
            continue
        out.append(a)
        i += 1
    return out


def _registry_write(w: List[str]) -> Optional[str]:
    h, sub = w[0], _positional(w)
    pushes = any(a == "--push" or a == "--push=true" or "type=registry" in a or "push=true" in a for a in w[1:])
    if "login" in sub[:2] and h in _ENGINES | {"buildah", "helm", "oras", "crane", "skopeo", "cosign", "regctl"}:
        return "registry login (%s)" % h
    if h in _ENGINES | {"buildah", "helm", "oras", "crane"} and sub[:1] == ["push"]:
        return "push to a registry (%s push)" % h
    if h in _ENGINES and (sub[:2] in (["manifest", "push"], ["image", "push"], ["compose", "push"])
                          or sub[:3] == ["buildx", "imagetools", "create"]):
        return "push to a registry (%s %s)" % (h, " ".join(sub[:2]))
    if h in {"docker-compose", "podman-compose"} and sub[:1] == ["push"]:
        return "push to a registry (%s push)" % h
    if pushes and (h in _ENGINES | {"buildah", "docker-buildx", "ko", "depot"}):
        return "build that pushes to a registry (%s --push / type=registry)" % h
    if h == "skopeo" and sub[:1] in (["copy"], ["sync"], ["delete"]):
        dest = sub[-1] if len(sub) > 2 else ""
        if sub[0] == "delete" or not dest.startswith(_LOCAL_REF):
            return "registry write (skopeo %s)" % sub[0]
    if h == "crane" and sub[:1] and sub[0] in {"copy", "cp", "mutate", "append", "tag", "delete", "rebase",
                                                 "flatten", "index"}:
        return "registry write (crane %s)" % sub[0]
    if h == "oras" and sub[:1] and sub[0] in {"push", "attach", "copy", "cp", "tag", "manifest"}:
        return "registry write (oras %s)" % sub[0]
    if h == "cosign" and sub[:1] and sub[0] in {"sign", "attest", "sign-blob", "attest-blob", "upload", "copy",
                                                  "attach", "clean"}:
        return "signing or registry write (cosign %s; keyless signing adds a permanent public log entry)" % sub[0]
    if h == "ko" and sub[:1] and sub[0] in {"build", "publish", "resolve", "apply", "create", "run"} \
            and not any(a in ("--local", "-L", "--push=false") for a in w[1:]):
        return "ko %s pushes to a registry (no --local)" % sub[0]
    return None


def _kube_write(w: List[str]) -> Optional[str]:
    h, sub = w[0], _positional(w)
    if h in _KUBE_CLIS:
        if not sub or sub[0] in _KUBE_READ:
            return None
        if sub[0] == "auth" and sub[1:2] != ["reconcile"]:
            return None
        if sub[0] == "rollout" and sub[1:2] in (["status"], ["history"]):
            return None
        if sub[0] == "config":
            return None if sub[1:2] and sub[1] in _KUBE_CONFIG_READ else "%s config %s" % (h, " ".join(sub[1:2]))
        if any(a in ("--dry-run=client", "--dry-run=none") for a in w[1:]) and sub[0] in {"apply", "create",
                                                                                          "run", "expose", "set"}:
            return None
        return "%s %s" % (h, sub[0])
    if h == "helm" and sub[:1] and sub[0] in _HELM_CLUSTER_WRITE:
        if any(a == "--dry-run" or a in ("--dry-run=client", "--dry-run=true") for a in w[1:]):
            return None
        return "helm %s" % sub[0]
    if h in {"argocd", "flux"} and sub[:1] and sub[0] not in {"version", "get", "list", "logs", "check", "tree",
                                                               "diff", "stats", "export", "completion", "help"}:
        if not (h == "argocd" and sub[:2] in (["app", "get"], ["app", "list"], ["app", "diff"], ["app", "history"])):
            return "%s %s" % (h, " ".join(sub[:2]))
    return None


def _glob(name: str, pattern: str) -> bool:
    return name.startswith(pattern[:-1]) if pattern.endswith("*") else name == pattern


def _kube_context(w: List[str], cmd: str, project_dir: str, env: Dict[str, str]) -> Optional[str]:
    """The context a kubectl/helm call will use, '' when its kubeconfig is run-owned under .stack/ (local by
    construction), or None when no kubeconfig exists (the call cannot reach any cluster)."""
    explicit = _flag(w, "--context", "--kube-context")
    m = _KUBECONFIG_ASSIGN.search(cmd)
    kc = _flag(w, "--kubeconfig") or (m.group(2) if m else None) or env.get("KUBECONFIG") \
        or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".kube", "config")
    files = [f for f in kc.split(os.pathsep) if f]
    if files and all(under_root(f, project_dir) for f in files):
        return ""
    if explicit:
        return explicit
    for f in files:
        try:
            with open(os.path.join(project_dir, os.path.expanduser(f)), encoding="utf-8") as fh:
                found = _CURRENT_CONTEXT.search(fh.read(1 << 20))
        except OSError:
            continue
        if found:
            return found.group(1)
    return None if not any(os.path.exists(os.path.join(project_dir, os.path.expanduser(f))) for f in files) \
        else "(no current-context)"


# --- git push: approved by the user, never on an agent's own judgment ---------------------------------
# Global options of `git` that take a separate value, so `git -C repo push` is still seen as a push.
_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env",
                   "--attr-source"}
_GIT_PUSH_VALUE_OPTS = {"--repo", "--receive-pack", "--exec", "--push-option"}
_GIT_PUSH_DESTRUCTIVE = {"--force", "--force-with-lease", "--force-if-includes", "--delete", "--mirror", "--prune"}


def _git_sub(w: List[str]):
    """(subcommand, its arguments) of a git invocation, skipping git's global options; (None, []) otherwise."""
    if not w or w[0] != "git":
        return None, []
    i = 1
    while i < len(w):
        a = w[i]
        if a in _GIT_VALUE_OPTS:
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            return a, w[i + 1:]
    return None, []


def git_push(w: List[str]) -> Optional[str]:
    """Why this command word list is a git push that needs the user's approval, or None.
    Dry runs change nothing and pass; force, delete, mirror and prune pushes are named as destructive."""
    sub, args = _git_sub(w)
    if sub != "push":
        return None
    bad, pos, dry, i = [], [], False, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += args[i + 1:]
            break
        if a.startswith("--"):
            name = a.split("=", 1)[0]
            if name in _GIT_PUSH_DESTRUCTIVE:
                bad.append(name)
            elif name == "--dry-run":
                dry = True
            i += 2 if (name in _GIT_PUSH_VALUE_OPTS and "=" not in a) else 1
            continue
        if a.startswith("-") and len(a) > 1:
            step = 1
            for j, ch in enumerate(a[1:]):
                if ch == "f":
                    bad.append("-f")
                elif ch == "d":
                    bad.append("-d")
                elif ch == "n":
                    dry = True
                elif ch == "o":  # -o <push-option>, or -ovalue
                    step = 2 if j == len(a) - 2 else 1
                    break
            i += step
            continue
        pos.append(a)
        i += 1
    for ref in pos[1:]:  # pos[0] is the remote
        if ref.startswith("+"):
            bad.append("+%s (forced refspec)" % ref[1:])
        elif ref.startswith(":") and len(ref) > 1:
            bad.append("%s (deletes the remote ref)" % ref)
    if dry:
        return None
    if bad:
        return ("DESTRUCTIVE git push (%s): it can overwrite or delete commits, branches or tags on the remote "
                "for good" % ", ".join(dict.fromkeys(bad)))
    return "git push (publishes commits to a remote)"


def outward_bash(cmd: str, project_dir: str = ".", env: Optional[Dict[str, str]] = None,
                 local_contexts=LOCAL_KUBE_CONTEXTS) -> Optional[str]:
    """Why this Bash command pushes to a git remote, writes to a registry or changes a non-local cluster, or None."""
    env = os.environ if env is None else env
    for w in _segments(cmd):
        if w[0] in SHELLS and "-c" in w[1:]:
            inner = " ".join(w[w.index("-c") + 1:]).strip().strip("'\"")
            why = outward_bash(inner, project_dir, env, local_contexts) if inner and inner != cmd else None
            if why:
                return why
        why = _registry_write(w) or git_push(w)
        if why:
            return why
        verb = _kube_write(w)
        if verb:
            ctx = _kube_context(w, cmd, project_dir, env)
            if ctx is None or ctx == "" or any(_glob(ctx, p) for p in local_contexts):
                continue
            return "cluster change on non-local context %s (%s)" % (ctx, verb)
    return None


WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
FORM_TOOLS = ("mcp__playwright__browser_type", "mcp__playwright__browser_fill_form",
              "mcp__playwright__browser_file_upload", "mcp__playwright__browser_press_key")
# Input into the disposable desktop sandbox (stack_mcp/desktop_sandbox): allowed for its agents, denied once
# an agent is tainted, since flagged content may be steering what gets typed, run or copied in.
SANDBOX_INPUT_TOOLS = tuple("mcp__desktop-sandbox__" + t for t in (
    "type_text", "key", "launch", "put_file", "click", "drag", "scroll", "move"))


MEMORY_PREFIX = "mcp__neural-memory__"
# Read-only NeuralMemory tools; every other tool of that server can write persistent memory.
MEMORY_READ_TOOLS = ("nmem_recall", "nmem_context", "nmem_recap", "nmem_situation", "nmem_health", "nmem_stats")


def under_root(path: str, project_dir: str, root: str = ".stack") -> bool:
    if not path:
        return False
    p = os.path.realpath(os.path.join(project_dir, os.path.expanduser(path)))
    base = os.path.realpath(os.path.join(project_dir, root))
    return p == base or p.startswith(base + os.sep)


def risky_action(tool: str, tool_input: dict, project_dir: str, write_root: str = ".stack") -> Optional[str]:
    tool_input = tool_input or {}
    if tool == "Bash":
        return risky_bash(str(tool_input.get("command") or ""))
    if tool in WRITE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if not under_root(str(path), project_dir, write_root):
            return "writing outside %s/ (%s)" % (write_root, path or "?")
        return None
    if tool in FORM_TOOLS:
        return "typing into or uploading to a web page"
    if tool in SANDBOX_INPUT_TOOLS:
        return "typing into, running programs in or copying files into the desktop sandbox"
    if tool.startswith(MEMORY_PREFIX) and tool[len(MEMORY_PREFIX):] not in MEMORY_READ_TOOLS:
        return "writing persistent memory (%s)" % tool[len(MEMORY_PREFIX):]
    return None


# --- taint state --------------------------------------------------------------------------------

def _taint_path(session_id: str) -> str:
    d = os.path.join(paths.data_dir(), "sessions")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "%s.taint.json" % re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "unknown"))


def mark(session_id: str, agent_key: str, tool: str, url: str, res: Scan) -> dict:
    """Record that ``agent_key`` ingested flagged content; returns the agent's taint record."""
    path = _taint_path(session_id)
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            with open(path, encoding="utf-8") as fh:
                st = json.load(fh)
        except (OSError, ValueError):
            st = {}
        rec = st.setdefault(agent_key, {"first": time.time(), "events": 0, "score": 0, "level": "low",
                                        "urls": [], "rules": []})
        rec["events"] += 1
        if res.score > rec["score"]:
            rec["score"], rec["level"] = res.score, res.level
        if url and url not in rec["urls"]:
            rec["urls"] = (rec["urls"] + [url])[-5:]
        rec["rules"] = sorted(set(rec["rules"]) | set(res.hits))
        rec["last_tool"] = tool
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(st, fh)
        os.replace(path + ".tmp", path)
    return rec


def taint_of(session_id: str, agent_key: str) -> Optional[dict]:
    try:
        with open(_taint_path(session_id), encoding="utf-8") as fh:
            return json.load(fh).get(agent_key)
    except (OSError, ValueError):
        return None


def log_event(event: dict) -> None:
    """Append to <data>/injection.jsonl (rule names, score, URL, digest; never the content)."""
    try:
        with open(os.path.join(paths.data_dir(), "injection.jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")
    except OSError:
        pass


def url_of(tool_input: dict) -> str:
    ti = tool_input or {}
    for k in ("url", "urls", "uri", "link"):
        v = ti.get(k)
        if isinstance(v, list) and v:
            v = v[0]
        if isinstance(v, str) and v:
            return v[:300]
    return ""
