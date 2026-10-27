# MCP servers

Keys live only in `~/.claude/stack.env` (template: `config/stack.env.example`, or `config/stack.env.fal.example` when every image operation runs on fal; mode 600). Nothing
secret is in `config/mcp.servers.json`, `.mcp.json` or settings. Two mechanisms deliver them:

* **stdio servers** start through `bin/mcp-run`, which *parses* (never sources) the env file and
  execs the server with the keys in its environment.
* **remote (http) servers** get auth headers from `bin/mcp-headers <service>` via `headersHelper`.
  Claude Code runs it on every connection and strips credential-like env vars first, so the helper
  reads the env file itself. A missing key yields `{}` (anonymous/free tier where the service has one).

`bin/stack keys` shows which keys are set (names only).

## Stack servers (`config/mcp.servers.json`)

The stack's servers live in the catalog `config/mcp.servers.json`, not in `.mcp.json` (which stays
`{"mcpServers": {}}`). `bin/stack mcp sync` copies each one inline into the `mcpServers` frontmatter of the
agents that use it, so it connects only while such an agent runs and the main thread loads no MCP tools
(details: [Lazy loading](reference/mcp.md#lazy-loading)). Never add a stack server to `.mcp.json`. Inline servers
in a project's `.claude/agents/` load once the folder is trusted.

| server | transport | key | used by | tools (prefix `mcp__<server>__`) |
|---|---|---|---|---|
| `playwright` | stdio `npx @playwright/mcp@latest --headless --isolated --caps=vision,pdf,devtools` | — | browser-operator, tester | `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_type`, `browser_fill_form`, `browser_take_screenshot`, `browser_pdf_save`, `browser_network_requests`, tracing/video … |
| `exa` | http `mcp.exa.ai/mcp?tools=…` | `EXA_API_KEY` (x-api-key) | researchers | `web_search_exa`, `web_fetch_exa`, `web_search_advanced_exa`, `agent_run` |
| `jina` | http `mcp.jina.ai/v1` | `JINA_API_KEY` (Bearer) | researchers, summarizers | `read_url`, `search_web`, `search_arxiv`, `search_ssrn`, `extract_pdf`, `sort_by_relevance`, `deduplicate_strings`, `capture_screenshot_url` |
| `spider` | http `mcp.spider.cloud/mcp` | `SPIDER_API_KEY` (Bearer) | web-scraper, web-crawler | `spider_crawl`, `spider_scrape`, `spider_search`, `spider_links`, `spider_screenshot`, `spider_transform`, `spider_browser_*` |
| `context7` | http `mcp.context7.com/mcp` | `CONTEXT7_API_KEY` (optional) | language/domain experts, architect | `resolve-library-id`, `query-docs` |
| `fetch` | stdio `sh -c … bin/mcp-run uvx --python 3.13 mcp-server-fetch` | none (free) | the eight research agents | `fetch` (url to markdown; `max_length`, `start_index`, `raw`); first choice for any known URL, before the metered readers |
| `neural-memory` | stdio `sh -c … bin/neural-memory-mcp` (pinned `neural-memory==4.62.0`, data in `~/.claude/stack-data/neural-memory`) | — | delegator (main thread, inline); orchestrator, planner, architect, debugger, reviewer share it by name | minimal tier only: `nmem_recall`, `nmem_context`, `nmem_recap`, `nmem_remember`; the launcher initialises the data dir itself so the package never edits `~/.claude/settings.json`; memory writes by a tainted agent are denied; web-reading agents do not get it |
| `desktop-sandbox` | stdio `sh -c … bin/mcp-run --only DESKTOP_SANDBOX_ bin/desktop-sandbox` | none (receives no keys; optional `DESKTOP_SANDBOX_*` settings) | computer-operator, tester | `sandbox_status`, `sandbox_start`, `sandbox_stop`, `screenshot`, `zoom`, `window_list`, `click`, `move`, `drag`, `scroll`, `type_text`, `key`, `wait`, `launch`, `put_file`; needs Docker or podman and the image from `bin/desktop-sandbox --build` |
| `image` | stdio `sh -c … bin/mcp-run bin/image-router` | per-operation `IMAGE_<OP>_URL` / `_KEY` / `_MODEL` | image-generator, image-editor, vector-artist, visual-reviewer, graphic-design-expert | always: `image_ops_status`, `image_info`, `mask_convert`, `svg_optimize`, `svg_inspect`, `svg_render`, `svg_layers`, `svg_layerize`, `layers_compose`, `export_pdf`; when configured: `image_generate`, `image_generate_with_references`, `image_edit`, `image_generate_transparent`, `image_segment`, `image_remove_background`, `image_upscale`, `vector_generate`, `image_vectorize`, `svg_transform` |

Computer use has two routes. The built-in `computer-use` server (macOS, interactive sessions, Pro/Max) drives the
user's real apps: enable it once with `/mcp` → computer-use → Enable. `computer-operator` references it by name. The
stack's own `desktop-sandbox` server (`stack_mcp/desktop_sandbox/`) drives a disposable, network-less Linux desktop
in a hardened container and works in both runtimes. It is the default for GUI work that needs no personal state
and the only unattended route (skill `sandboxed-computer-use`; build the image once with
`bin/desktop-sandbox --build --profile recommended`). The optional `peekaboo` server drives the real desktop headless and is used only
with the user's quoted approval.

## Image server (`image`)

`stack_mcp/image_router/` is our own MCP stdio server (Python 3.13 via uv; mcp 2.x SDK, httpx, Pillow,
resvg-py, pikepdf, svglib/reportlab, vtracer), launched by `bin/mcp-run bin/image-router` so keys come from
`~/.claude/stack.env` and never from the server config. Full reference: `stack_mcp/image_router/README.md`;
operation table: `config/image-ops.json`.

* **One endpoint per operation, bring your own key, no fallbacks.** Each operation reads exactly
  `IMAGE_<OP>_URL`, `IMAGE_<OP>_KEY` and `IMAGE_<OP>_MODEL` (optional `_API` to force the adapter, `_PARAMS`
  for fixed request parameters). Operations: GEN, REF, EDIT, TRANSPARENT, SEGMENT, BG_REMOVAL, UPSCALE,
  VECTOR, TRACE, VECTOR_MANIPULATION (default `claude`: the agent edits SVG text itself). `IMAGE_MASK_*` and
  `IMAGE_RGBA_*` still work as deprecated aliases.
* **Tools follow the configuration.** An operation's tool is listed only while its URL, KEY and MODEL are set
  (or `IMAGE_TRACE_API=local` / `IMAGE_UPSCALE_API=local`); `image_ops_status` and the local tools are always
  listed. The env file is read at call time and watched: when the set changes the server sends
  `tools/list_changed`; clients that ignore it pick the change up after `/mcp` reconnect.
* **Adapters**, chosen from the URL host or `_API`: `openrouter` (`https://openrouter.ai/api/v1`), `opper`
  (`https://api.opper.ai`), `fal` (`https://queue.fal.run`, model = fal endpoint id, queue API, inputs mapped
  from the endpoint's OpenAPI schema), `openai` (any OpenAI-compatible endpoint) and `local` (vtracer tracing,
  Lanczos upscaling). Where a router only approximates an operation (masks, cut-outs, segmentation on
  OpenRouter/Opper) the result's `notes` say so; fal runs dedicated models for those operations.
* **Fidelity post-processing**, whatever the adapter: masked edits are composited so pixels outside the mask
  are unchanged; background removal transfers the model's alpha onto the original pixels and reports colour
  drift; segmentation output is normalised to a binary white-on-black mask at the source size; upscales are
  resized to exactly the requested factor.
* **Vectors and layers:** `svg_render` (resvg) previews SVG; `svg_layerize` builds Inkscape layers by group,
  colour or an explicit mapping; `layers_compose` stacks SVG and raster layers; `export_pdf` writes a vector PDF,
  with `layered: true` one Optional Content Group per layer.
* Inputs: local paths (relative to the project), URLs or data URIs. Outputs: `.stack/images/<YYYYMMDD>/` plus a
  JSON sidecar (operation, adapter, URL host, model, prompt, parameters; never keys).
* Quality loop: the image agents send results to `visual-reviewer`; `/visual-iterate` runs the same
  produce-review rounds as a saved workflow.

## Optional servers (`config/mcp.optional.json`)

`bin/stack mcp list` (catalog servers show as `lazy`), `bin/stack mcp enable <name>`, `bin/stack mcp disable <name>`.
An enabled server goes into `.mcp.json` and connects for the whole session (not lazy). `bin/stack mcp sync
[--dry-run]` re-renders the inline copies after a catalog change.

| name | what |
|---|---|
| `fal` / `fal-oauth` | fal's hosted MCP (~60 tools incl. `create_entity` reusable characters/styles from 1–20 refs) |
| `replicate` | official Replicate MCP (stdio, `REPLICATE_API_TOKEN`) |
| `recraft` | official Recraft remote MCP (OAuth) |
| `flux` | official Black Forest Labs MCP (OAuth) |
| `runware` | official Runware MCP (`RUNWARE_API_KEY`) |
| `peekaboo` | open-source macOS computer use for headless runs |
| `markitdown` | Microsoft markitdown (PDF/Office/HTML to markdown), Python server via `uvx --python 3.13`; free |
| `firecrawl`, `tavily`, `brave-search` | alternative search/scrape backends |
