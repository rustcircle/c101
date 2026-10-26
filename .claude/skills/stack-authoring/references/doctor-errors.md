# bin/stack doctor messages: cause and fix

Source: `stack/doctor.py`. Run `bin/stack doctor 2>&1 | grep -F '<path>'` to see only your files;
`bin/stack doctor --json` for machine-readable output. Exit code 1 when any ERROR exists.
Checkers run in order: agents, tiers, packs, skills, workflows, MCP, settings, executables, auth. A crashing checker is
reported as `<checker>: checker crashed: ...` and the others still run.

## Agents (`.claude/agents/**.md`)

| Message | Cause | Fix |
|---|---|---|
| `no agent files found` | Wrong repo or empty agents dir | Run from the repo root |
| `frontmatter: file does not start with a '---' frontmatter fence` | BOM, blank line or text before `---` | First line exactly `---` |
| `frontmatter: unterminated frontmatter (no closing '---')` | Missing closing fence | Add `---` after the last key |
| `missing name` | No `name:` key | Add `name: <file stem>` |
| `invalid name '...'` | Contains `:`, starts with `-`, or > 256 chars | kebab-case name |
| `duplicate agent name '...' (also ...)` | Two files declare the same name | Rename or delete one; update callers |
| warn `file stem differs from name` | `name` differs from the file name | Make them equal (paths.find_agent_file looks up by stem) |
| `description missing or too short (it drives automatic delegation)` | < 40 chars, or the parser lost it (multi-line block scalar, inner unescaped quotes) | One physical line in double quotes, 300-600 chars |
| `unknown frontmatter key '...' (Claude Code would ignore it)` | Typo (`maxturns`, `mcp_servers`) or a key Claude Code does not support | Use only: name, description, tools, disallowedTools, model, effort, maxTurns, mcpServers, skills, memory, hooks, permissionMode, isolation, background, color, initialPrompt, omitClaudeMd, autoCompactWindow, experimental |
| `unknown model '...'` | Not an alias (opus, sonnet, haiku, fable, inherit, default, best, opusplan, opus[1m], sonnet[1m]) and not a `claude-*` id | Let the tier render it: `bin/stack agents set <name> tier=<TIER>` |
| `effort must be one of [...]` | Typo or unsupported level | low, medium, high, xhigh, max |
| `maxTurns must be an integer 1..3000, got ...` | Quoted number, float, or out of range | Bare integer |
| `autoCompactWindow must be an integer 100000..1000000` | Out of range | Remove it or use a valid window |
| `color must be one of [...]` | e.g. `gray` | red, blue, green, yellow, purple, orange, pink, cyan |
| `mcpServers references unknown server '...'` | Name not in `config/mcp.servers.json`, `.mcp.json` or the built-ins (optional servers are not active) | Use a catalog server (`bin/stack agents set <name> mcpServers=a,b`), or `bin/stack mcp enable <name>` first; built-in `computer-use` only with a playwright/peekaboo fallback (it is absent under the SDK/-p); do not use `claude-in-chrome` (absent under the SDK/-p) |
| `inline mcpServers entry '...' is not in config/mcp.servers.json` | Hand-written inline definition for a server the catalog lacks | Add the server to the catalog and run `bin/stack mcp sync`, or reference an existing one |
| `inline definition of MCP server '...' is missing or differs from config/mcp.servers.json (run bin/stack mcp sync)` | Catalog server referenced by plain name, or the inline copy drifted after a catalog edit | `bin/stack mcp sync` (never hand-edit inline copies) |
| `skills references missing skill '...'` | Skill dir or its SKILL.md absent | Create the skill first, or fix the name |
| warn `unrecognised tool '...'` | Unknown built-in tool name in tools/disallowedTools | Check spelling; MCP tools must start with `mcp__` |
| `body too thin (N chars); agents need a real operating procedure` | Body under 600 chars | Write the full body per CONVENTIONS section 3 |
| warn `no '## Output' section (output contract)` | Section missing or renamed | Add `## Output` |

## Tiers (`config/models.json`)

| Message | Cause | Fix |
|---|---|---|
| `config/models.json: unreadable: ...` | Invalid JSON | `python3 -m json.tool config/models.json` and fix |
| `config/models.json: missing tier ...` | One of ADVANCED_MODEL, MEDIUM_MODEL, LOW_MODEL deleted | Restore the tier block `{model, alias}` |
| `<agent path>: no tier in config/models.json (...)` | New agent without an entry | Add `agents.<name> = {tier, effort, maxTurns, why}`, then `bin/stack agents set <name> tier=<TIER>` (renders `model` for that agent only) |
| `config/models.json: <name> has unknown tier '...'` | Typo in the tier name | One of the three tier names |
| warn `model '...' differs from its tier T=<id> (bin/stack agents tiers --apply)` | Frontmatter `model` hand-edited or written as an alias | `bin/stack agents set <name> tier=<T>` for one agent; `bin/stack agents tiers --apply` re-renders all agents (review its dry run first) |
| warn `config/models.json: tier entry for unknown agent '...'` | Entry left after a rename or removal | Delete the entry or fix the name |

## Skills (`.claude/skills/<name>/SKILL.md`)

| Message | Cause | Fix |
|---|---|---|
| `.claude/skills: missing` | No skills dir | Run from the repo root |
| `<dir>: no SKILL.md` | Directory without SKILL.md (often a half-created skill) | Add the file or remove the dir |
| `frontmatter: ...` | As for agents | As for agents |
| `name '...' must equal directory '...'` | Mismatch | Make them equal |
| `description missing or too short` | < 40 chars or lost by the parser | One line, double-quoted |
| `unknown frontmatter key '...'` | Key outside: name, description, when_to_use, argument-hint, arguments, disable-model-invocation, user-invocable, allowed-tools, disallowed-tools, model, effort, context, agent, background, hooks, paths, shell, metadata, license, compatibility | Remove or rename |
| `bad effort '...'` | Invalid level | low..max |
| `context must be 'fork'` | Any other value | `context: fork` or remove |
| warn `N lines; keep SKILL.md under 500 and move detail to references/` | Too long | Move catalogs and long examples to `references/` |
| `body too thin (N chars)` | Under 400 chars | Write the procedure |
| `broken link to references/...` | A markdown link `](references/x.md)`, `](scripts/...)`, `](examples/...)` or `](assets/...)` whose target does not exist; placeholders like `<topic>` inside such a link count too | Create the file or fix the path; write placeholders in code spans without link syntax |

## Workflows (`.claude/workflows/*.js`)

| Message | Cause | Fix |
|---|---|---|
| warn `.claude/workflows: missing` | No workflows dir | Create it when adding the first workflow |
| `first statement must be export const meta = {...}` | Comment, constant or blank code before meta | Move meta to the top (leading whitespace is fine) |
| `Date.now()/Math.random()/new Date() throw inside workflows` | Non-deterministic calls (they break resume) | Pass timestamps via args; vary prompts by index instead of randomness |
| `imports are not allowed in workflow scripts` | `import` statement or dynamic `import()` | Inline the helper code |
| `agentType '...' is not a known agent` | Literal agentType not in the stack or built-ins (general-purpose, Explore, Plan, ...) | Use an existing agent name |
| `no export const meta` / `unterminated meta literal` | Malformed meta | Fix braces and quotes |
| `meta must be a pure literal (no templates, spreads or calls)` | Template string, `...spread`, or an identifier followed by `(` outside strings | Plain strings, arrays, objects only |
| `meta literal: ...` | Literal does not evaluate | Fix the syntax error named |
| `syntax: ...` | Script body fails to parse as an async function body | Fix the syntax error; TypeScript annotations are a common cause |
| `meta needs name and description` | Missing fields | Add both |
| `duplicate workflow name '...'` | Two files with the same `meta.name` | Rename one |
| `workflow name '...' collides with a bundled workflow` | `deep-research` | Pick another name |
| `workflow name '...' collides with a skill of the same name` | Same name as a skill dir | Rename the workflow |
| warn `phase('X') has no meta.phases entry` | `phase()` title not declared | Add `{title: 'X', detail}` to meta.phases (titles match exactly) |
| warn `node not found; skipped syntax check` | No node on PATH | Install node or run doctor where it exists |

## MCP (`.mcp.json`, `config/mcp.servers.json`)

| Message | Cause | Fix |
|---|---|---|
| `.mcp.json: unreadable` | Invalid JSON | Fix JSON |
| `config/mcp.servers.json: missing, unreadable or without servers` | Catalog deleted, invalid JSON or empty `servers` | Restore it from version control |
| warn `also in config/mcp.servers.json: the .mcp.json copy connects for the whole session and defeats lazy loading` | A stack server was added to `.mcp.json` | Remove it from `.mcp.json` (and `enabledMcpjsonServers`) |
| warn `alwaysLoad: true loads every tool schema up front (tool search cannot defer it)` | `alwaysLoad` set on a server | Remove it |
| `remote server without url` | http/sse entry lacks `url` | Add it |
| `bin/mcp-headers is not executable` / `bin/mcp-run is not executable` | Lost exec bit | `chmod +x bin/mcp-headers bin/mcp-run` |
| `stdio server without command` | Missing `command` | Add it |
| `references missing path ...` | An arg under `${CLAUDE_PROJECT_DIR:-.}/` or `"$d"/` points to a missing file | Fix the path or create the launcher |
| `unknown type '...'` | Not stdio, http, sse, ws or streamable-http | Fix `type` |

## Settings and learning

| Message | Cause | Fix |
|---|---|---|
| `.claude/settings.json: unreadable` | Invalid JSON | Fix JSON |
| warn `ENABLE_TOOL_SEARCH=false loads every MCP tool schema up front` | Tool search disabled in settings `env` | Remove the key (tool search is on by default) |
| warn `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH and CLAUDE_STACK_MAX_DEPTH differ` | Depth env vars out of sync | Set both to the same value |
| `env.UV_PYTHON '...' differs from .python-version '...'` | The interpreter version was changed in one place only | Set `env.UV_PYTHON` in `.claude/settings.json` to the `.python-version` value (then rerun `./install.sh` for the user-scope copy) |
| `unknown hook handler '...'` | A `bin/stack hook <name>` command for a handler that does not exist | Use one of pre-agent, subagent-stop, session-start, session-end, prompt-submit, model-switch (`stack/hooks.py` HANDLERS) |
| warn `config/learning.json: bounds for unknown agent '...'` | Bounds for a renamed or removed agent | Remove or rename the entry |
| `<path>: starts with #! but is not executable (chmod +x it, or re-run ./install.sh)` | A script lost its exec bit (zip download, copy) or was committed without it | `chmod +x <path>`, and `git update-index --chmod=+x <path>` so the mode is committed |
| warn `environment: ANTHROPIC_API_KEY is set: ...` (or `ANTHROPIC_AUTH_TOKEN`) | An API credential in the shell overrides the claude.ai subscription login | `unset ANTHROPIC_API_KEY` (and remove it from shell profiles) |
| warn `<settings file>: configures an API key ...` | `apiKeyHelper` or `env.ANTHROPIC_API_KEY` in a settings file | Remove it so Claude Code uses the subscription login |
| warn `<settings file>: availableModelsMatch is honoured only from managed settings ...` (or `deniedModels`) | A managed-only key in project, local or user settings; Claude Code ignores it there | Remove it; for exact model matching run `sudo bin/stack managed-settings --install` |
