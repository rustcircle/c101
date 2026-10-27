# image-router v2: the `image` MCP server

One MCP stdio server, `image`, with one tool per kind of image operation. Each operation is
bound to exactly the endpoint, key and model tag you set for it in `~/.claude/stack.env`.
Bring your own key (BYOK) through a router: **OpenRouter** and **Opper** today, or any
OpenAI-compatible endpoint. There are no fallbacks. An operation uses its configured endpoint
and model, and if the operation is not configured the tool says which env vars to set.

The server also has local tools that need no model: image info, mask conversion, SVG
optimise / inspect / render, layers (list, layerize, compose) and a layered vector PDF export.

Requires Python 3.13 under uv: `mcp` 2.x, `httpx`, `Pillow`, `resvg-py`, `svglib` +
`reportlab`, `pikepdf` and `vtracer` (see [Libraries and licences](#libraries-and-licences)).

## Running

```bash
bin/image-router                    # stdio JSON-RPC on stdout, logs on stderr (--mode is accepted and ignored)
bin/image-router --check            # per-operation status (adapter, host, model; never keys), then exit
uv run --python 3.13 python -m stack_mcp.image_router
```

`.mcp.json` starts the server as `image` through `bin/mcp-run bin/image-router`. Agents use the
tools as `mcp__image__<tool>`.

## Configuration: one endpoint per operation

For each operation `OP`, set three variables in `~/.claude/stack.env` (the template is
`config/stack.env.example`; `CLAUDE_STACK_ENV` overrides the path):

| variable | meaning |
|---|---|
| `IMAGE_<OP>_URL` | router base URL: `https://openrouter.ai/api/v1`, `https://api.opper.ai`, or an OpenAI-compatible base |
| `IMAGE_<OP>_KEY` | the key for that URL (optional only for a loopback OpenAI-compatible server) |
| `IMAGE_<OP>_MODEL` | the model tag sent to that URL, e.g. `google/gemini-nano-banana-2.1` |
| `IMAGE_<OP>_API` | optional: `openrouter`, `opper` or `openai`; `local` for `TRACE`/`UPSCALE`. The default is detected from the URL host |
| `IMAGE_<OP>_PARAMS` | optional JSON object deep-merged into every request for the operation, e.g. `'{"quality":"high"}'` |

The server reads the file **on every call**, with the same parsing rules as `stack/envfile.py`
and `bin/mcp-run`: `KEY=VALUE`, optional `export`, matching quotes, and an inline ` # comment`
on unquoted values. A non-empty value in the file wins; otherwise `os.environ` is used, except
for the values `bin/mcp-run` copied from the file into the environment at launch: the server
snapshots the file when it starts serving and ignores environment values that still equal that
snapshot, so deleting or blanking a line takes effect too (it does not fall back to the stale
launch copy). Edits therefore take effect without a restart.

That includes whether `svg_transform` is listed. The server advertises `tools.listChanged` and
sends `notifications/tools/list_changed` when the env file changes that (it polls the file's
mtime every `IMAGE_ROUTER_WATCH_INTERVAL` seconds, default 2, `0` disables, and re-checks on every
tool call), so clients that cache `tools/list` (Claude Code does) pick the change up without a
`/mcp` reconnect.

The adapter is detected from the URL host: `openrouter.ai` uses openrouter, `opper.ai` uses
opper, and any other host uses openai (OpenAI-compatible).

`IMAGE_<OP>_PARAMS` and a tool call's `params` may not set `model`, `prompt`, `messages` or the
input images (`input_references`, `image`, `image[]`, `mask`, `reference_images`): the model is
always `IMAGE_<OP>_MODEL` (a per-call switch would be a silent fallback and the sidecar would
record the wrong model). A configuration that tries is reported as a configuration error; a tool
call that tries is refused before anything is sent.

Two keys inside `IMAGE_<OP>_PARAMS` are router directives and are never sent:

- `strategy`:
  - `render` or `detect` for SEGMENT
  - `image` or `chat` for VECTOR and TRACE
- `mask_convention`: `white-edit`, `black-edit` or `alpha-transparent`, for Opper edits

| OP | tools | purpose |
|---|---|---|
| `GEN` | `image_generate` | text -> image |
| `REF` | `image_generate_with_references` | generation guided by 1..N reference images |
| `EDIT` | `image_edit` | instruction edit; masked inpaint when `mask` is given |
| `TRANSPARENT` | `image_generate_transparent` | transparent (RGBA) generation (`IMAGE_RGBA_*` is a deprecated alias) |
| `SEGMENT` | `image_segment` | segmentation: prompt -> white-on-black mask PNG of the source size (`IMAGE_MASK_*` is a deprecated alias) |
| `BG_REMOVAL` | `image_remove_background` | background removal -> RGBA cut-out on the original pixels (`IMAGE_RGBA_*` is a deprecated alias) |
| `UPSCALE` | `image_upscale` | faithful upscaling (`IMAGE_UPSCALE_API=local`: Pillow Lanczos) |
| `VECTOR` | `vector_generate` | native SVG generation (`layered=true`: layers by group) |
| `TRACE` | `image_vectorize` | raster -> SVG (`IMAGE_TRACE_API=local`: vtracer; `layered=true`: one layer per colour) |
| `VECTOR_MANIPULATION` | `svg_transform` | listed **only** when `IMAGE_VECTOR_MANIPULATION_*` is configured with a model other than `claude` |

An operation's tool is listed only while that operation is configured (URL + KEY + MODEL, or `API=local` for TRACE and
UPSCALE). `image_ops_status` and the local tools are always listed; `tools/list_changed` is sent when the set changes.

`IMAGE_VECTOR_MANIPULATION_MODEL` defaults to `claude`. In that mode the agent edits SVG text
itself with Read/Edit, using `svg_inspect`, `svg_render` and `svg_layers` to check its work.

`config/image-ops.json` documents every operation: its env names, tools, per-adapter request
mapping and default output format. It holds no secrets and no model choices.

Example:

```bash
IMAGE_GEN_URL=https://openrouter.ai/api/v1
IMAGE_GEN_KEY=sk-or-...
IMAGE_GEN_MODEL=google/gemini-nano-banana-2.1
IMAGE_EDIT_URL=https://api.opper.ai
IMAGE_EDIT_KEY=op-...
IMAGE_EDIT_MODEL=fal/ideogram-v4.5-edit
IMAGE_SEGMENT_URL=https://openrouter.ai/api/v1
IMAGE_SEGMENT_KEY=sk-or-...
IMAGE_SEGMENT_MODEL=moondream/moondream3.1-9b-a2b
IMAGE_SEGMENT_PARAMS='{"strategy":"detect"}'
IMAGE_TRACE_API=local
IMAGE_UPSCALE_API=local
```

## Adapters

Each adapter module lives in `providers/`. An operation configured against an adapter that
cannot do it fails with a clear message. Nothing else is tried.

### OpenRouter (`providers/openrouter.py`)

Every image operation is one call, `POST {URL}/images`. There is no `/images/edits`; it
returns 404.

- **Headers:** `Authorization: Bearer KEY`, plus `HTTP-Referer` and `X-OpenRouter-Title`
  (also sent as `X-Title`). Override the defaults with `OPENROUTER_APP_URL` and
  `OPENROUTER_APP_TITLE`.
- **Body:** `model`, `prompt`, `n`, `aspect_ratio`, `size` (a tier or `WxH`; an explicit
  `WxH` drops `aspect_ratio`), `resolution`, `quality`, `background`, `output_format`, `seed`.
- **Input images:** sent as `input_references: [{"type":"image_url","image_url":{"url":...}}]`,
  using a data URL, or the public URL when the input was an unmodified public download.
- **Response:** `data[].b64_json` plus `media_type`. For SVG, the base64 decodes to UTF-8
  markup.
- **Masks:** there is no mask parameter. An EDIT mask is sent as input reference 2, with the
  instruction "edit only the white region of image 2", and `notes` say so.
- **SEGMENT:** `render` (the default) asks the image model for a pure black and white mask and
  normalises it. `detect` calls `POST {URL}/chat/completions` with a vision model, for example
  moondream `/detect {"object": ...}`, and rasterises the boxes it returns.
- **Approximations:** cut-outs, upscales and traces are regenerations, because OpenRouter has
  no matting, upscale or tracing models. See [Fidelity](#fidelity-post-processing).
- **Catalog:** the adapter reads the public `GET {URL}/images/models` (cached for an hour;
  `supported_parameters` per model) to:
  - split `n` into single-image requests (run concurrently) for models that declare `n` 1..1 or
    no `n` at all - most current models; images already generated are kept if some of the
    requests fail, with a warning;
  - snap `aspect_ratio` to the model's own values;
  - keep the source framing for edit-type tasks (edit, cut-out, upscale, mask, trace): without
    `aspect_ratio`/`size` from the caller it sends the model's ratio nearest the source (or
    `auto` when none is within 2%), and picks a listed `resolution` for upscales;
  - refuse `background=transparent` before paying when the model has no transparent option
    (or only JPEG output).

  When the catalog cannot be read, values are sent as given and `n` is split (always valid).

### Opper (`providers/opper.py`)

Image calls use `POST {URL}/v3/images` with `Authorization: Bearer KEY` (runtime keys start
with `op-`). Opper has no OpenAI-compatible images route, so this adapter calls the endpoint
with httpx.

- **Body:** `model`, `prompt`, `n` (at most 4), `size` (`WxH`) or `aspect_ratio`,
  `resolution`, `quality`, `response_format: b64_json`.
- **Input images:** sent as `image`, `mask` and `reference_images` (a URL or data URI each).
- **Provider options:** go in `parameters`, for example `background`, `output_format`, `seed`
  or `style`. Opper forwards them verbatim and the provider validates them, so each is sent only
  when the model's catalog entry declares it (GPT Image declares no `seed`; Gemini declares no
  parameters at all); others are dropped with a note.
- **Response:** `data[].b64_json` plus `mime_type`. Gemini models return JPEG.
- **Catalog:** the adapter reads `GET {URL}/v3/images/models` (public; cached for an hour) and
  validates every request against the model's `params.image` before paying:
  - `size_constraints` (GPT Image 2/2.5: multiple of 16, edge <= 3840, ratio <= 3,
    655,360-8,294,400 px): a legal `WxH` is sent as is, an illegal one is snapped keeping its
    ratio, an `aspect_ratio` becomes a `WxH` of exactly that ratio (16:9 -> 1536x864), a tier a
    `WxH` of that long edge;
  - presets (`sizes`, where `auto` is a size value) and `aspect_ratios`: the nearest listed one;
  - tiers `1K`/`2K`/`4K` map to `resolution` only when listed there, to `quality` when the
    model expresses them as a quality (Gemini `4k`), to a size by long edge, or are dropped -
    never sent as `size: null`;
  - `quality` is dropped when the model lists no quality tiers or not that one;
  - edit-type tasks without `size`/`aspect_ratio` keep the source framing (a `WxH` of the
    source's ratio, `auto`, or the nearest preset / ratio);
  - `background=transparent` is refused before paying when the model declares no background
    option or its enum lacks `transparent`.

  Only when the catalog is unavailable are values sent unvalidated (with a note).
- **Vector:** models that declare a `style` parameter (Recraft) get
  `parameters.style=vector_illustration` (or the `vector_*` style given) - the documented way to
  ask for vector output; vector styles are billed at a higher rate.
- **Async:** add `"async": true` to `IMAGE_<OP>_PARAMS` for slow models; the synchronous
  deadline is 3 minutes and returns 504. The call then returns 202. The adapter polls
  `GET {URL}/v3/artifacts/{id}/status` until the status is completed or failed, then
  downloads `url`. The key is never sent to the storage host.
- **Mask convention:** chosen from the model tag. GPT Image gets `alpha-transparent`, Ideogram
  gets `black-edit`, and every other model gets `white-edit`. Override it with
  `mask_convention`.
- **Defaults:** TRACE defaults to the `chat` strategy, a vision LLM through
  `/v3/compat/chat/completions`. VECTOR expects `image/svg+xml` from the image endpoint;
  otherwise set `{"strategy":"chat"}`.

### OpenAI-compatible (`providers/openai.py`)

| endpoint | used for | format |
|---|---|---|
| `POST {URL}/images/generations` | text-to-image and transparent generation | JSON |
| `POST {URL}/images/edits` | references, edits, cut-outs, upscales and rendered masks | multipart |

The multipart request sends `image[]` repeated, plus `mask`, `prompt`, `model`, `background`,
`output_format`, `size` and `n`. The response holds `data[].b64_json` or `data[].url`.

The mask is an RGBA PNG where transparent means edit. The source image is re-encoded as PNG so
the mask's format matches. VECTOR and TRACE default to the `chat` strategy, through
`{URL}/chat/completions`.

Sizes: `gpt-image-1.x` and `dall-e` models get their fixed sizes (the nearest by ratio, with a
note); sizes computed from a tier or `aspect_ratio` for other models meet the GPT Image 2 limits
(multiple of 16, 655,360-8,294,400 pixels, edge <= 3840, ratio <= 3), so `1K` + `16:9` is
1280x720, not 1024x576.

### Local (`providers/local.py`, opt-in only)

- **`IMAGE_TRACE_API=local`:** traces with vtracer. vtracer settings go in
  `IMAGE_TRACE_PARAMS` or `params`. `layered=true` uses `hierarchical=cutout`, so shapes never
  overlap and one layer per colour is exact.
- **`IMAGE_UPSCALE_API=local`:** resizes with Pillow Lanczos to exactly `scale` times the
  source size.

### svg_transform

`svg_transform` sends a chat-completions request with the SVG text and the instruction. The
reply must contain one SVG document, which is extracted from code fences or prose. It is
checked for well-formedness, and the SVG namespace is repaired if missing, before anything is
written. The input file is never modified.

## Tools

Every tool returns one JSON text block, flagged `isError` on failure:

```json
{"ok": true, "tool": "image_edit", "op": "EDIT", "adapter": "openrouter", "url_host": "openrouter.ai",
 "model": "krea/k3-edit",
 "files": [{"path": "/abs/.stack/images/20261019/add-a-hat-142233-edit.png", "mime": "image/png", "bytes": 81234, "width": 1024, "height": 768}],
 "notes": ["OpenRouter has no mask parameter: ...", "preserve_unmasked: ..."], "warnings": [], "fidelity": [...]}
```

When an operation is not configured, the payload is
`{"ok": false, "error": "image_generate is not configured: set IMAGE_GEN_URL, IMAGE_GEN_MODEL, IMAGE_GEN_KEY in ...", "missing_env": [...]}`.

### Operation tools

| tool | key parameters |
|---|---|
| `image_generate` | `prompt`, `aspect_ratio?`, `size?` (`1K`/`2K`/`4K` or `WxH`), `n` (1-4), `quality?`, `seed?`, `output_format?` |
| `image_generate_with_references` | as `image_generate`, plus `references` (1..16) |
| `image_edit` | `image`, `instruction`, `mask?`, `references?`, `preserve_unmasked=true`, `feather=1.5`, `resize_mask?` |
| `image_segment` | `image`, `prompt`, `invert?` |
| `image_generate_transparent` | as `image_generate` (RGBA PNG) |
| `image_remove_background` | `image`, `preserve_pixels=true`, `prompt?` |
| `image_upscale` | `image`, `scale` (1-8], `prompt?` |
| `vector_generate` | `prompt`, `style?`, `aspect_ratio?`, `layered?`, `n` |
| `image_vectorize` | `image`, `layered?`, `colormode` (`color`/`binary`; local only), `prompt?` |
| `svg_transform` | `svg_path`, `instruction`, `output_path?` (listed only when configured) |

Every operation tool also takes `output_dir?`, `filename_prefix?` and `params?`. `params` holds
provider-native fields and is deep-merged last, after `IMAGE_<OP>_PARAMS`; it may not set the
reserved fields (`model`, `prompt`, `messages`, input images).

### Local tools

| tool | what it does |
|---|---|
| `image_ops_status()` | Per operation: configured, adapter, URL host, model tag, missing env names, directives. Also says whether `svg_transform` is exposed. Never shows keys |
| `image_info(image)` | Size, mode, alpha (present / used), format and file size. For SVG: declared size and layer count |
| `mask_convert(mask, to, invert?, match_image?, output_path?)` | Converts between `white-edit`, `black-edit` and `alpha-transparent` |
| `svg_optimize(svg_path, precision=2, output_path?)` | Rounds coordinates, strips editor data (keeping the layer markers) and adds a viewBox |
| `svg_inspect(svg_path)` | Reports well-formedness, size/viewBox, element and path counts, palette, layers, text and fonts, embedded rasters and complexity, and flags common problems |
| `svg_render(svg_path, width?, background?, output_path?)` | PNG preview via resvg: text, gradients, transforms, masks, filters; mm/cm/in/pt at 96 dpi; without `width` at most 4096 px on the longest side (64 MP in all) |
| `svg_layers(svg_path)` | Top-level layers: id, label, visibility, element count, palette |
| `svg_layerize(svg_path, by, mapping?, strict_z_order=true, output_path?)` | Rewrites the SVG into layers (see below) |
| `layers_compose(layers, width, height, output_path?)` | Merges SVG and raster sources into one layered SVG |
| `export_pdf(svg_path, output_path?, layered=true, page_size="auto")` | Vector PDF. When layered, each top-level layer becomes a PDF Optional Content Group (OCG) |

### Inputs and outputs

- **Inputs:** a local path (relative to `$CLAUDE_PROJECT_DIR` or the cwd; `~` is expanded), a
  `file://` URL, an `http(s)` URL or a `data:` URI. Raster-operation inputs (and masks) are
  normalised once, so the provider and the local fidelity steps see the same pixels:
  - EXIF orientation is applied: a phone photo is processed and sent upright, as viewers show
    it (sizes, masks and outputs use the displayed orientation; `image_info` reports the
    displayed size plus `exif_orientation` / `stored_size`);
  - formats the routers do not accept (TIFF, BMP, AVIF, HEIC, ICO, ...) are re-encoded as PNG;
  - SVG inputs are rendered to PNG (at most 4096 px on the longest side by default);
  - 16/32-bit greyscale is scaled to 8 bits (not clipped) by the local fidelity steps.
- **Outputs:** written to `output_dir`, which defaults to
  `<project>/.stack/images/<YYYYMMDD>/`. Names are `<prompt slug|prefix>-<HHMMSS>-<op>`, plus
  `-2`, `-3` and so on when a name is taken; files are created atomically. Local tools write
  next to their input unless `output_path` is given; `layers_compose` writes to the output
  directory. A default name never replaces an existing file (a designer's own `logo.pdf` next
  to `logo.svg` makes `export_pdf` write `logo-2.pdf`, with a note); only an explicit
  `output_path` overwrites, which is why the writing local tools are annotated
  `destructiveHint`.
- **Sidecars:** each operation output gets a `<file>.json` holding:
  - `tool`, `op`, `adapter`, `url_host` and `model`;
  - `prompt` or `instruction`;
  - `params` (the call's arguments), `op_params` and `directives`;
  - `request`, the body with payloads replaced by placeholders;
  - `inputs`, `notes`, `warnings`, `fidelity` and `created`.

  Sidecars are sanitised. They never contain key values, key-like fields, base64 or data-URI
  payloads, or the query, fragment or user info of any URL: a public input URL that a provider
  fetches itself (it may be presigned) is recorded as `scheme://host/path?<redacted>`, in the
  request summary as everywhere else. Error messages show only the adapter, the URL **host**
  and the model tag, and any key value is replaced with `***`.

## Fidelity post-processing

These steps are deterministic and local. They are not provider fallbacks.

- **EDIT with a mask** (`preserve_unmasked=true`): the result is fitted to the source size and
  composited as `out = src*(1-m) + result*m`. `m` is the canonical mask feathered *inwards* by
  about `feather` px, so every pixel outside the mask is byte-identical to the source.
  `fidelity` reports the model's drift outside the mask, which is discarded.
- **Another aspect ratio:** a model result whose aspect ratio differs from the source by more
  than 2% is never stretched into the source frame (edits, upscales and rendered masks): it is
  scaled to cover the frame and centre-cropped, `fidelity`/`mask_stats` say `aspect_mismatch`,
  and a warning names both sizes. The adapters request the source framing up front to avoid it.
- **BG_REMOVAL `image_remove_background`** (`preserve_pixels=true`): the model's alpha is resized and
  applied to the original pixels. The mean absolute RGB drift inside the alpha is measured, and
  `warnings` flags it when it is above 18/255. If the model returns no alpha, or a different
  aspect ratio, its own output is kept and a warning explains why.
- **UPSCALE (remote models):** the output is Lanczos-resized to exactly `scale` times the source,
  and drift from the source is reported.
- **SEGMENT:** the model output's brightness (max channel), or its alpha for cut-outs, is resized
  bilinearly to the source size and thresholded at 128 to give a binary white-on-black L PNG.
  `binary_fraction` < 0.8 means the model probably drew a picture rather than a mask. With the
  `detect` strategy the boxes may come back as 0-1 fractions, pixels, per-mille or Gemini's
  `box_2d`; they are normalised (the prompt states the image size), `mask_stats` reports the
  `coordinates` read and the `white_fraction`, and a warning flags boxes that cover none or all
  of the image.

## Layers and layered PDF

**Layer markup.** A layer is a top-level
`<g id="layer-…" inkscape:groupmode="layer" inkscape:label="…">`. Inkscape treats these as
native layers, and Illustrator imports top-level groups as layers. A file without layer markers
treats every top-level `<g>` as a layer.

**`svg_layerize` modes.** It preserves `<defs>`, z-order and appearance, and re-renders the
result to compare it with the original (`appearance`).

- `by="group"`: top-level groups become layers in place. A lone wrapper group is descended
  into, with its attributes kept on each layer's content. Loose elements become "Ungrouped"
  layers.
- `by="color"`: one layer per paint colour (fill, else stroke; gradients and patterns by id).
- `by="mapping"`: `{layer_name: [ids or selectors]}`, where a selector is `#id`, `.class`,
  `tag`, `[attr]`, `[attr=value]` (paint values compare as colours) or the descendant / `>`
  combinators. Unmatched elements go to "Other".

**How colour and mapping modes keep the appearance.**

- **Styles:** colours and visibility resolve as a browser does for the supported subset:
  inline `style` > `<style>` rules (specificity, then order; `!important` wins) > presentation
  attributes > inheritance. Illustrator's "Export As SVG" classes (`.cls-1{fill:...}`) therefore
  give correct colour keys and palettes (also in `svg_inspect` / `svg_layers`).
- **Whole groups:** groups that cannot be split without changing their look stay whole. That
  means groups with opacity, filter, mask, an `objectBoundingBox` clip-path or a blend mode, and
  groups referenced by id - including `#id` selectors in `<style>`. A `userSpaceOnUse` clip-path
  (the default, and what Figma exports around a frame) distributes over the children, so such a
  group is flattened like any other. When the whole drawing is one group that must stay whole, a
  note says why.
- **Flattening:** other groups are flattened. Their transform and presentation attributes are
  re-applied through wrapper groups.
- **Overlap check:** elements are assigned in document order. An element may join an earlier
  layer of its key only if it does not overlap anything drawn in between. Overlap is decided
  from resvg-rasterised coverage at about 384 px, counting any coverage (small text and
  hairlines in large documents only reach a fraction of a grid pixel). Thick shapes are eroded
  by one grid pixel, so anti-aliasing and spline slivers along edges that neighbouring shapes
  share do not count. Thin shapes such as lines and hairlines keep their full coverage, and a
  visible element too small to show at that grid is treated as covering everything, so it is
  never moved.
- **Conflicts:** with `strict_z_order=true` (the default), a conflicting element opens a new
  layer of the same key, for example `#ff0000 (2)`. With `false`, there are fewer layers, the
  move is reported, and the appearance may change.
- **Reporting:** `appearance` gives the mean difference and the changed-pixel fraction. A warning
  is added above 1% changed pixels or a mean difference of 1.5/255.
- **Traces:** local vtracer traces use cutout mode when `layered=true`, so they come out as one
  layer per distinct fill colour.

**`layers_compose`.** SVG sources are fitted into their box using their own
`preserveAspectRatio` and clipped to that box (as a nested `<svg>` viewport would be; content
outside the viewBox or a `slice` overflow cannot paint over other layers) unless the source root
says `overflow="visible"`. Their ids are prefixed and their `<style>` rules are scoped under the
layer id, so sources cannot clash, and their linked local images (`<image href="photo.png">`) are
embedded, resolved against the source's folder (only real image files; anything else is left out
with a warning). Raster sources become `<image>` data URIs in their own layer, upright (EXIF
orientation applied). The first layer is the bottom one.

**`export_pdf`.** Each layer unit is converted with svglib and drawn inside
`/OC /ocN BDC … EMC` on one page. pikepdf then adds `/OCProperties` with one OCG per layer
label, in `/Order`. Hidden SVG layers start `/OFF`, and `/PageMode /UseOC` opens the layers
panel. Each unit is converted with every `<style>` and the transitive closure of the ids it
references (gradients, clip paths, `<use>` targets in other layers), so cross-layer references
still resolve and the export stays linear in the number of layers.

svglib ignores `opacity`, so the writer restores it: a layer's (or, without layers, a top-level
element's) group opacity is applied by drawing it into a Form XObject marked as a transparency
group and painting that with the constant alpha; a single shape's opacity is folded into its
fill/stroke opacity. Linked local images are embedded first (relative to the SVG's folder;
nested SVG images are rasterised). Everything the PDF still cannot reproduce is returned in
`warnings`: masks, filters, pattern fills, `<foreignObject>`, blend modes, radial gradients on
non-square shapes (drawn as circles), group opacity nested inside a layer, text whose characters
the PDF font cannot show (outline it), and anything svglib itself reports.

Loose top-level content becomes "Unlayered" OCGs. An SVG without layers (or `layered=false`)
gives a plain single-layer PDF. Raster images keep their alpha as an `/SMask`. `page_size` is
`auto` (page = drawing; px are converted to pt at 96 dpi), `A4` or `letter` (orientation
follows the drawing) or `WxHmm`; the drawing is scaled to fit and centred.

**`svg_optimize`.** Coordinates are rounded to `precision`; transform coefficients (matrix,
scale, rotate, skew) keep at least 5 significant digits while translations are rounded like
coordinates, as svgo does (Inkscape's 0.26458333 px-to-mm factor stays exact enough); opacities,
gradient offsets and filter coefficients keep at least 2 decimals.

## Libraries and licences

| library | licence | use |
|---|---|---|
| resvg-py (resvg) | MIT (resvg: MIT/Apache-2.0) | `svg_render`, coverage and appearance checks |
| svglib | LGPL-3.0 (used unmodified as a library) | SVG to ReportLab drawing for PDF export |
| reportlab | BSD | PDF drawing |
| pikepdf | MPL-2.0 | Optional Content Groups (layers) |
| vtracer | MIT | local tracing (`IMAGE_TRACE_API=local`) |
| Pillow, httpx, mcp | HPND / BSD / MIT | rasters, HTTP, MCP |

PyMuPDF (AGPL) is not used.

## Layout

```
server.py      ImageServer('image'): registers every tool; tools/list hides svg_transform while VECTOR_MANIPULATION=claude;
               advertises listChanged and notifies when the env file changes that
tools.py       tool functions (typed params + LLM-facing docstrings), input normalisation, fidelity steps, payloads, file writing
config.py      per-op env (stack.env parsed at call time, launch snapshot), adapter detection, redaction, project dir
providers/     base (job/result, chat + SVG helpers), openrouter, opper, openai, local, geometry (sizes, ratios, constraints)
imaging.py     Pillow: info, mask conventions, mask normalisation, composite / alpha transfer / resize
svg.py         svg_optimize (xml.etree)
svgtools.py    inspect, layers, layerize (z-order-safe), compose, PDF layer units, appearance check
render.py      resvg rasterisation; svglib/reportlab/pikepdf layered PDF
http.py        shared AsyncClient factory, retries/backoff, test transport seam
io.py          input resolution, MIME sniffing, data URIs, output naming, sanitised sidecars
tests/         pytest: env parsing, adapter request shapes (httpx.MockTransport), fidelity, SVG/PDF, stdio e2e
```

Run the tests with `uv run --python 3.13 pytest stack_mcp -q`.

## Knobs and limits

**Environment knobs:**

- `IMAGE_ROUTER_HTTP_RETRIES`: default 3. Paid POSTs are retried only when the request cannot
  have been processed (connect errors, 429, 503, 522, 529).
- `IMAGE_ROUTER_BACKOFF_SCALE`: default 1; tests set it to 0.
- `IMAGE_OPPER_POLL_TIMEOUT`: seconds, default 900.
- `IMAGE_ROUTER_WATCH_INTERVAL`: seconds between env-file checks for `tools/list_changed`,
  default 2; `0` disables the watcher (tool calls still re-check).

**Limits:**

- Model-based cut-outs, upscales, traces and masks are approximations. The fidelity steps and
  `warnings` say how far the result drifted.
- The `detect` strategy gives box masks, not outlines.
- `svg_transform` accepts SVGs up to 512 KB. Run `svg_optimize` first for larger files.
- svglib maps fonts to the PDF standard fonts unless it finds a TrueType file. Text-heavy SVGs
  may shift slightly in the PDF, and characters outside those fonts are reported in `warnings`.
- Masks, filters, patterns and `<foreignObject>` are not converted to PDF (reported in `warnings`).

## fal adapter

`IMAGE_<OP>_API=fal`, or detected from a `fal.run` / `fal.ai` URL host. URL `https://queue.fal.run`, KEY the fal
key (sent as `Authorization: Key <key>`), MODEL the fal endpoint id, e.g. `fal-ai/bria/background/remove`,
`fal-ai/sam-3/image`, `fal-ai/topaz/upscale/image`, `fal-ai/recraft/vectorize`. Supports every operation except
VECTOR_MANIPULATION.

- **Queue:** `POST {URL}/{endpoint}` -> `{request_id, status_url, response_url}`; the status is polled with
  backoff (1 s x1.5, at most 8 s) until `COMPLETED`; a run that completed with `error` fails with that error;
  `IMAGE_ROUTER_FAL_TIMEOUT` (default 900 s) cancels and fails. Every `{url}` in the result JSON is downloaded
  (no credentials are sent to the CDN host).
- **Inputs:** names come from the endpoint's OpenAPI schema (`falschema.py`, cached 7 days under
  `.stack/cache/fal-schemas`): prompt, `image_url`/`image_urls`, `mask_url`, `image_size`, `num_images`,
  `background`, `upscale_factor`. Inputs are data URIs (or the public URL of an unmodified download). A canonical
  input the endpoint has no field for is listed in `notes`; a missing source image, mask or prompt fails the call
  before anything is submitted.
- **Masks** are sent white = edit; `IMAGE_<OP>_PARAMS={"mask_convention": "black-edit"}` for endpoints that edit
  black (e.g. Ideogram).
- The fidelity post-processing (mask compositing, alpha transfer, mask normalisation, exact upscale size) applies
  to fal results exactly as to the other adapters.
