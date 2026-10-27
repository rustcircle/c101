#!/usr/bin/env bash
# Install / update the agent stack. Requires uv (https://docs.astral.sh/uv/);
# everything Python runs on the uv-managed CPython pinned in .python-version (3.13).
#
#   ./install.sh                 project scope: uv env, ~/.claude/stack link, ~/.claude/stack.env template,
#                                uv's CPython 3.13 as Claude Code's default Python (and python/python3 links)
#   ./install.sh --user          + agents/skills/workflows/MCP servers/hooks in every project
#   ./install.sh --main-agent    + make `delegator` the main-thread agent for all sessions
#   ./install.sh --adobe [APPS]  + register the Adobe app MCP servers (InDesign, Illustrator, Photoshop,
#                                After Effects, Premiere Pro) at user scope and run each app's one-time setup
#   ./install.sh --dry-run ...   show what would change
set -euo pipefail
REPO="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="${HOME}/.local/bin:${HOME}/.nix-profile/bin:/etc/profiles/per-user/${USER:-nobody}/bin:/run/current-system/sw/bin:/nix/var/nix/profiles/default/bin:/opt/homebrew/bin:/usr/local/bin:${PATH}"

if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'MSG'
uv is required but was not found. Install it with one of:
  brew install uv
  curl -LsSf https://astral.sh/uv/install.sh | sh
then re-run ./install.sh
MSG
  exit 1
fi

PYV="$(tr -d '[:space:]' < "$REPO/.python-version")"
dry=0
for a in "$@"; do [[ "$a" == "--dry-run" ]] && dry=1; done

echo "uv $(uv --version | awk '{print $2}'), Python $PYV"
if [[ $dry -eq 0 ]]; then
  uv python install "$PYV"
  if [[ -f "$REPO/uv.lock" ]]; then
    uv sync --project "$REPO" --python "$PYV" --locked
  else
    uv sync --project "$REPO" --python "$PYV"
  fi
else
  echo "[dry-run] uv python install $PYV && uv sync --project $REPO --python $PYV"
fi

command -v node >/dev/null 2>&1 || echo "note: node/npx not found — the Playwright MCP server (npx @playwright/mcp) needs Node 18+." >&2

exec uv run --quiet --project "$REPO" --python "$PYV" python -m stack.install "$@"
