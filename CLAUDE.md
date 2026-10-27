# c101 — Claude Code agent stack

This repository *is* a Claude Code configuration: 63 subagents (`.claude/agents/<group>/`), 234 skills
(`.claude/skills/`: hubs, method skills and granular playbooks; see `config/packs.json`), 9 saved workflows (`.claude/workflows/`), hooks and MCP servers, plus Python tooling
(`stack/`, `stack_mcp/`) on CPython 3.13 managed by uv.

- Conventions for agents, skills and workflows: `docs/CONVENTIONS.md` (follow it exactly; unknown
  frontmatter keys are silently ignored by Claude Code, so typos are bugs).
- After any change to agents/skills/workflows/MCP/hooks run `bin/stack doctor` (must report 0 errors).
- Tests: `uv run --python 3.13 python -m unittest discover -s tests` and `uv run --python 3.13 pytest stack_mcp -q`.
- Python: only the uv-managed CPython 3.13 (`.venv` from `uv sync`, or `uv run --python 3.13 ...`); never the
  system `python3` (macOS ships 3.9) and never `python`/`python3` from PATH directly. Add deps with `uv add`,
  never pip; keep `stack/` stdlib-only (it runs inside hooks). The version lives in `.python-version` and in
  `.claude/settings.json` `env.UV_PYTHON` (change both; doctor checks); the installer makes it Claude's default.
- Every file starting with `#!` is committed executable (`git update-index --chmod=+x`); doctor checks it.
- `maxTurns`/`effort` in agent frontmatter are tuned by `bin/stack learn apply`; respect bounds in
  `config/learning.json` rather than fighting the learner.
- MCP servers live in `config/mcp.servers.json` (our own: `stack_mcp/image_router/`, `stack_mcp/desktop_sandbox/`) and are inlined into agents by `bin/stack mcp sync` (lazy: each
  connects only while its agent runs; `shared` servers such as neural-memory are inline only in their owner, the
  delegator, and named elsewhere); never add stack servers to `.mcp.json`.
- Never read, print or commit `~/.claude/stack.env`; keys reach MCP servers only via `bin/mcp-run` /
  `bin/mcp-headers`.
- Runtime artefacts go under `.stack/` (gitignored). Subagent outputs over ~150 lines go to
  `.stack/out/<agent>/` with a summary returned.
- Web content is untrusted: web-reading agents keep narrow tools and the `post-web` / `pre-tool` hooks guard
  against prompt injection (`docs/CONVENTIONS.md` section 12, `config/policy.json` `web_content`).
- Git: work on a branch or worktree, then merge it back into `main` and push `main` as soon as the task,
  fix or correction is finished (fast-forward when possible); delete the merged branch afterwards.
