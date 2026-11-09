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
import shlex
import subprocess
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


_SHELL_KEYWORDS = {"then", "do", "else", "elif", "if", "while", "until", "!", "{", "("}


def _strip_shell_syntax(seg: str) -> List[str]:
    """Words of one segment without the shell syntax around the command: leading ``then``/``do``/``else``/
    ``if``/``while``, ``(`` and ``{`` groupers, and the ``)`` that closes ``(cmd)`` or ``$(cmd)``."""
    words = seg.strip().split()
    while words:
        head = words[0]
        if head in _SHELL_KEYWORDS:
            words = words[1:]
        elif head[0] in "({":
            words[0] = head.lstrip("({")
            if not words[0]:
                words = words[1:]
        else:
            break
    if words and words[-1].endswith(")") and " ".join(words).count(")") > " ".join(words).count("("):
        words[-1] = words[-1].rstrip(")")
        if not words[-1]:
            words.pop()
    return words


def _segments(cmd: str) -> List[List[str]]:
    """Command words of each pipeline/list segment; wrappers (sudo, env, timeout...), their options
    and VAR=value assignments are skipped so the head is the program that actually runs."""
    out = []
    for seg in _SEGMENT_SPLIT.split(cmd):
        words = _strip_shell_syntax(seg)
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


def risky_bash(cmd: str, project_dir: str = ".", _depth: int = 0) -> Optional[str]:
    segs = _segments(cmd)
    res = _Aliases(project_dir, os.environ, _depth)
    heads = [w[0] for w in segs]
    # pipe into a shell, or into an interpreter reading its program from stdin
    for i, w in enumerate(segs[1:], 1):
        if "|" in cmd and (w[0] in SHELLS or (w[0] in INTERPRETERS and (len(w) == 1 or w[1] == "-"))):
            return "pipe-to-shell (output of another command executed by %s)" % w[0]
    for w in segs:
        if w[0] in SHELLS and "-c" in w[1:]:
            inner = " ".join(w[w.index("-c") + 1:]).strip().strip("'\"")
            why = risky_bash(inner, project_dir, _depth) if inner and inner != cmd else None
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
        if sub == "push" or (sub == "remote" and args[:1] and args[0] in ("add", "set-url")) or remote_write(w, res):
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


# --- remote writes: git push and its look-alikes, approved by the user, never on an agent's own judgment ----------
# Global options of `git` that take a separate value, so `git -C repo push` is still seen as a push.
_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env",
                   "--attr-source"}
_GIT_PUSH_VALUE_OPTS = {"--repo", "--receive-pack", "--exec", "--push-option"}
_GIT_PUSH_DESTRUCTIVE = {"--force", "--force-with-lease", "--force-if-includes", "--delete", "--mirror", "--prune"}
# `hub` is a git wrapper: same global options, same subcommands, same push semantics.
_GIT_WRAPPERS = {"git", "hub"}
# Plumbing commands that publish refs exactly like push (they take push's flags).
_GIT_PUSH_COMMANDS = {"push", "send-pack", "http-push"}
# Built-in git subcommands (git ignores an alias with one of these names), so no alias lookup for them.
_GIT_BUILTINS = frozenset("""add am annotate apply archive bisect blame branch bundle cat-file check-attr check-ignore
    check-ref-format checkout cherry cherry-pick citool clean clone column commit commit-tree config count-objects
    credential describe diagnose diff diff-index diff-tree difftool fast-export fast-import fetch fetch-pack
    filter-branch for-each-ref format-patch fsck gc get-tar-commit-id gitk grep gui hash-object help hook init
    instaweb interpret-trailers log ls-files ls-remote ls-tree maintenance mailinfo mailsplit merge merge-base
    merge-file merge-index merge-tree mergetool multi-pack-index mv name-rev notes pack-objects pack-refs patch-id
    prune prune-packed pull range-diff read-tree rebase receive-pack reflog remote repack replace request-pull
    rerere reset restore rev-list rev-parse revert rm scalar send-email shortlog show show-branch show-ref
    sparse-checkout stash status stripspace submodule switch symbolic-ref tag unpack-file unpack-objects
    update-index update-ref upload-archive upload-pack var verify-commit verify-pack verify-tag version
    whatchanged worktree write-tree""".split()) | _GIT_PUSH_COMMANDS
_ALIAS_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_ALIAS_TIMEOUT = 1.5      # seconds per `git config` call (the pre-tool hook has 10 s in total)
_ALIAS_LOOKUPS = 4        # lookups per Bash command
_ALIAS_DEPTH = 3          # alias -> alias -> shell alias nesting
_GIT_IN_SHELL = re.compile(r"(?<![\w./-])(?:git|hub|gh)(?=\s)")


def _git_idx(w: List[str]) -> Optional[int]:
    """Index of the subcommand in a git/hub invocation, skipping the global options; None if there is none."""
    if not w or w[0] not in _GIT_WRAPPERS:
        return None
    i = 1
    while i < len(w):
        a = w[i]
        if a in _GIT_VALUE_OPTS:
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            return i
    return None


def _git_sub(w: List[str]):
    """(subcommand, its arguments) of a git (or hub) invocation, skipping git's global options; (None, []) otherwise."""
    i = _git_idx(w)
    return (None, []) if i is None else (w[i], w[i + 1:])


class _Aliases:
    """Resolves git aliases for the push check. Every failure (no git, no repo, timeout, odd value) means
    "unknown", which never blocks; lookups and nesting are bounded so a hook cannot hang or recurse."""

    def __init__(self, cwd: str, env: Dict[str, str], depth: int = 0, budget: Optional[List[int]] = None):
        self.cwd, self.env, self.depth = cwd, env, depth
        self.budget = [_ALIAS_LOOKUPS] if budget is None else budget

    def nested(self) -> "_Aliases":
        return _Aliases(self.cwd, self.env, self.depth + 1, self.budget)

    def lookup(self, w: List[str], idx: int) -> Optional[str]:
        """Value of alias ``w[idx]``: an inline ``-c alias.x=...`` first, else ``git config --get alias.x`` run with
        the command's own -C / --git-dir / --work-tree so the repository it would run in is the one asked."""
        name = w[idx]
        if self.depth >= _ALIAS_DEPTH or not _ALIAS_NAME.match(name):
            return None
        scope: List[str] = []
        inline = None
        i = 1
        while i < idx:
            a = w[i]
            if a in ("-C", "--git-dir", "--work-tree") and i + 1 < idx:
                scope += [a, w[i + 1]]
            elif a == "-c" and i + 1 < idx and w[i + 1].lower().startswith("alias.%s=" % name.lower()):
                inline = w[i + 1].split("=", 1)[1]
            elif a.startswith(("--git-dir=", "--work-tree=")):
                scope.append(a)
            i += 2 if a in _GIT_VALUE_OPTS else 1
        if inline is not None:
            return inline or None
        if self.budget[0] <= 0:
            return None
        self.budget[0] -= 1
        try:
            done = subprocess.run(["git", *scope, "config", "--get", "alias." + name], cwd=self.cwd,
                                  env={**os.environ, **self.env}, stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, errors="replace", timeout=_ALIAS_TIMEOUT, check=False)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        return done.stdout.strip() or None if done.returncode == 0 else None


def _alias_remote_write(w: List[str], idx: int, res: "_Aliases") -> Optional[str]:
    """Reason when git alias ``w[idx]`` expands to a push (``push ...``, an alias of one, or a ``!`` shell command)."""
    val = res.lookup(w, idx)
    if not val:
        return None
    if val.startswith("!"):
        shell = val[1:].strip()
        found = outward_bash(shell, res.cwd, res.env, _depth=res.depth + 1)
        for m in _GIT_IN_SHELL.finditer(shell):  # function bodies: f() { git push "$@"; }; f
            found = found or outward_bash(shell[m.start():], res.cwd, res.env, _depth=res.depth + 1)
        why = found
    else:
        try:
            expanded = shlex.split(val)
        except ValueError:
            return None
        why = remote_write(w[:idx] + expanded + w[idx + 1:], res.nested()) if expanded else None
    return "%s [git alias '%s' = '%s']" % (why, w[idx], val) if why else None


def git_push(w: List[str], res: Optional["_Aliases"] = None) -> Optional[str]:
    """Why this command word list is a git push that needs the user's approval, or None. Dry runs change nothing
    and pass; force, delete, mirror and prune pushes are named as destructive. With ``res``, an unknown subcommand
    is resolved as a git alias and judged by what it expands to."""
    idx = _git_idx(w)
    if idx is None:
        return None
    sub, args = w[idx], w[idx + 1:]
    if sub not in _GIT_PUSH_COMMANDS:
        return None if res is None or sub in _GIT_BUILTINS else _alias_remote_write(w, idx, res)
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


_GH_VALUE_FLAGS = {"-R", "--repo", "-b", "--branch", "-s", "--source", "-t", "--title", "-n", "--notes", "-F",
                   "--notes-file", "-d", "--discussion-category", "--target", "--hostname", "-q", "--jq", "-H",
                   "--header", "-X", "--method", "-f", "--raw-field", "--field", "--input", "--template", "-T"}
_GH_BODY_FLAGS = {"-f", "-F", "--raw-field", "--field", "--input"}  # gh api switches to POST when any is given
_GH_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _gh_positional(words: List[str]) -> List[str]:
    out, i = [], 0
    while i < len(words):
        a = words[i]
        if a.startswith("-"):
            i += 2 if (a in _GH_VALUE_FLAGS and "=" not in a) else 1
        else:
            out.append(a)
            i += 1
    return out


def _gh_api_method(words: List[str]) -> str:
    method, has_body = None, False
    for i, a in enumerate(words):
        if a in ("-X", "--method") and i + 1 < len(words):
            method = words[i + 1]
        elif a.startswith("--method="):
            method = a.split("=", 1)[1]
        elif a.startswith("-X") and len(a) > 2:
            method = a[2:]
        elif a.split("=", 1)[0] in _GH_BODY_FLAGS or (a[:2] in ("-f", "-F") and len(a) > 2 and not a.startswith("--")):
            has_body = True
    return (method or ("POST" if has_body else "GET")).upper()


def gh_remote_write(w: List[str]) -> Optional[str]:
    """Why this gh invocation changes a GitHub remote (publishes a branch, release or API write), or None.
    Read-only commands (pr view/list/status/diff/checks, run view, api GET ...) pass.
    ``gh pr create --dry-run`` is still flagged: gh documents that it "may still push git changes"."""
    if not w or w[0] != "gh":
        return None
    words = w[1:]
    pos = _gh_positional(words)
    group, verb = (pos + ["", ""])[:2]
    if group == "api":
        if any(a == "graphql" or a.endswith("/graphql") for a in words):  # POSTs even for reads: only mutations count
            return ("gh api graphql mutation (writes to GitHub)"
                    if re.search(r"\bmutation\b", " ".join(words), re.I) else None)
        method = _gh_api_method(words)
        if method == "DELETE":
            return "DESTRUCTIVE gh api DELETE: it deletes the resource on GitHub for good"
        return "gh api %s (writes to GitHub)" % method if method in _GH_WRITE_METHODS else None
    if (group, verb) == ("pr", "create"):
        return "gh pr create (pushes the current branch if needed and publishes a pull request)"
    if (group, verb) == ("repo", "sync"):
        if "--force" in words:
            return ("DESTRUCTIVE gh repo sync --force: it hard-resets the branch to the source repository and "
                    "discards commits that are not in it")
        # without a destination argument gh syncs the local checkout, which publishes nothing
        return "gh repo sync (updates a branch of a remote repository)" if len(pos) > 2 else None
    if (group, verb) == ("repo", "delete"):
        return "DESTRUCTIVE gh repo delete: it deletes the repository on GitHub for good"
    if (group, verb) == ("repo", "create") and "--push" in words:
        return "gh repo create --push (publishes the local commits to a new remote repository)"
    if group == "release":
        if verb in ("delete", "delete-asset"):
            return "DESTRUCTIVE gh release %s: it deletes release data (and with --cleanup-tag the tag) on GitHub" % verb
        if verb in ("create", "upload", "edit"):
            return "gh release %s (publishes to GitHub; create also pushes the tag)" % verb
    return None


def hub_remote_write(w: List[str]) -> Optional[str]:
    """hub's own publishing commands (hub push is judged by git_push, hub being a git wrapper)."""
    sub, args = _git_sub(w) if w and w[0] == "hub" else (None, [])
    if sub == "pull-request":
        return "hub pull-request (pushes the current branch if needed and publishes a pull request)"
    if sub == "release" and args[:1] in (["create"], ["edit"]):
        return "hub release %s (publishes to GitHub)" % args[0]
    if sub == "release" and args[:1] == ["delete"]:
        return "DESTRUCTIVE hub release delete: it deletes the release on GitHub for good"
    return None


def remote_write(w: List[str], res: Optional["_Aliases"] = None) -> Optional[str]:
    """Why this command changes a git/GitHub remote (git or hub push, gh/hub publishing, push aliases), or None."""
    return git_push(w, res) or gh_remote_write(w) or hub_remote_write(w)


def outward_bash(cmd: str, project_dir: str = ".", env: Optional[Dict[str, str]] = None,
                 local_contexts=LOCAL_KUBE_CONTEXTS, _depth: int = 0) -> Optional[str]:
    """Why this Bash command pushes to a git remote, writes to a registry or changes a non-local cluster, or None."""
    env = os.environ if env is None else env
    res = _Aliases(project_dir, env, _depth)
    for w in _segments(cmd):
        if w[0] in SHELLS and "-c" in w[1:]:
            inner = " ".join(w[w.index("-c") + 1:]).strip().strip("'\"")
            why = outward_bash(inner, project_dir, env, local_contexts, _depth) if inner and inner != cmd else None
            if why:
                return why
        why = _registry_write(w) or remote_write(w, res)
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
        return risky_bash(str(tool_input.get("command") or ""), project_dir)
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
