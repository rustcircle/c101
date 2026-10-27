# shellcheck shell=bash
# Sourced by bin/stack and bin/image-router: resolve the repo and a Python 3.13
# interpreter managed by uv. Sets REPO and the array PY (command prefix).
#
# Order: $CLAUDE_STACK_PYTHON > $REPO/.venv/bin/python (fast path; created by
# `uv sync`) > `uv run --python 3.13` > system python3 (warns; tooling is
# 3.9-compatible so hooks never break, but MCP servers need the uv env).
_src="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
while [[ -L "$_src" ]]; do
  _dir="$(cd -P "$(dirname "$_src")" && pwd)"
  _src="$(readlink "$_src")"
  [[ "$_src" != /* ]] && _src="$_dir/$_src"
done
REPO="$(cd -P "$(dirname "$_src")/.." && pwd)"
export PATH="${HOME:-/nonexistent}/.local/bin:/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin}"

if [[ -n "${CLAUDE_STACK_PYTHON:-}" ]]; then
  PY=("$CLAUDE_STACK_PYTHON")
elif [[ -x "$REPO/.venv/bin/python" ]]; then
  PY=("$REPO/.venv/bin/python")
elif command -v uv >/dev/null 2>&1; then
  PY=(uv run --quiet --project "$REPO" --python 3.13 python)
else
  echo "stack: uv not found and $REPO/.venv missing; run ./install.sh (falling back to system python3)" >&2
  PY=(python3)
fi
