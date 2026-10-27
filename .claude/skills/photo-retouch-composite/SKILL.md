---
name: photo-retouch-composite
description: "Photographic retouching and compositing with the image-edit router plus deterministic Pillow/NumPy steps: non-destructive step order, global tone and white balance, cleanup passes, colour and grain matching between plates, light, perspective and depth-of-field consistency, contact and cast shadows, product and portrait retouch limits, verified by diffs. Load when an edit or composite must look photographically real."
when_to_use: "A photo edit or composite must pass as a real photograph: product cutouts placed into lifestyle or generated scenes, marketplace packshots on pure white 255,255,255, dust, seam and distraction cleanup, colour casts and white balance, grain or sharpness that differs between plates, objects that float without contact shadows, halos or green spill around cutouts, hair and fur mattes, portrait skin retouch requests, 'looks pasted on', 'colours do not match the scene', retouching disclosure questions."
---

# Photo retouching and compositing

The photographic layer on top of hub `image-editing` (tools, masks, ground rules, review loop).
Everything measurable is done deterministically (photokit, masktool) so nothing drifts; model calls
are for content only: fills (`image_edit` with a mask), mattes (`image_remove_background`), masks
(`image_segment`) and an optional harmonise pass. Done means: the plates agree on every row of the
matching checklist (section 4) with the numbers logged, containment diffs pass, the sheet reads as one
photograph, and `visual-reviewer` passed it (hub section 11).

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
PY="$STACK/.venv/bin/python"; MT="$STACK/.claude/skills/image-editing/scripts/masktool.py"
IMG="$STACK/.claude/skills/image-generation/scripts/imgcheck.py"
PK="$STACK/.claude/skills/photo-retouch-composite/scripts/photokit.py"    # NumPy + Pillow, deterministic
pk() { uv run -q --no-project --python 3.13 --with numpy --with pillow python -I "$PK" "$@"; }
pk --help      # stats hist grain-measure swatch whitebg levels wb curve sharpen persp ramp dodge
               # transfer grain-add shadow reflect decontam
```

The stack venv has Pillow but not NumPy, hence the ephemeral `uv run`; a function rather than a
variable because zsh does not word-split a command stored in a variable. Define it in every Bash
call that uses it.

## 1. Step order

| # | Step | Tools | Gate before moving on |
|---|---|---|---|
| 0 | Assess | `image_ops_status`, `image_info`, Read, `pk stats`, `pk grain-measure`, light notes | checklist values written down (section 4) |
| 1 | Global tone and white balance | `pk levels`, `pk wb`, `pk curve` | neutrals neutral, no new clipping (`stats` clipped_hi/lo) |
| 2 | Cleanup: dust, seams, distractions | masks + `image_edit` (section 3) | containment diff passes |
| 3 | Local dodge and burn | `pk ramp` + `pk dodge` | light falloff matches the scene |
| 4 | Composite | matte, `pk transfer`, `pk shadow`/`reflect`, `masktool over`, `pk grain-add` | checklist rows match |
| 5 | Final grade | `pk curve`, low-strength `pk transfer` on the whole frame | histogram sane, skin and product colours checked |
| 6 | Output sharpen | `pk sharpen` at the delivered size | grain unchanged (`grain-measure`) |
| 7 | Upscale, last and only if needed | hub section 9 | the content was accepted first; sharpen the upscaled file, not the small one |

Why this order: models fill with the corrected colours; cleanup fills do not undo local tone work;
plates are clean before they are combined; every resample softens and sharpening amplifies grain,
so sharpening comes once, at the size that ships. Job folder and log, per the hub ground rules:

```bash
J=".stack/images/edits/$(date +%Y%m%d-%H%M)-<slug>"; mkdir -p "$J" && cp -n <input> "$J/00-original.png"
echo '{"step":1,"op":"photokit levels","in":["00-original.png"],"out":"01-levels.png","params":{"lo":0.5,"hi":99.5},"notes":"black 33.5 white 252.6"}' >> "$J/steps.jsonl"
```

One numbered file per step; a deterministic step logs its exact command and the numbers it printed,
so the chain can be replayed. EXIF-rotated JPEGs: normalise once (`ImageOps.exif_transpose`, hub
mask conventions) because photokit applies EXIF orientation on load and masktool does not.

## 2. Deterministic global corrections

| Correction | Command | Formula | Defaults and evidence |
|---|---|---|---|
| Levels | `pk levels in out [--lo 0.5 --hi 99.5] [--per-channel]` | out = (in - P_lo) / (P_hi - P_lo), percentiles of luma | luma-linked keeps hue; `--per-channel` also removes a cast, only for scenes that should be neutral; a flat test plate went from G p0.5/p99.5 103/201 to 0/254 |
| White balance, picked neutral | `pk wb in out --neutral x,y,r` | gains g_c = mean(m) / m_c on linear RGB of the patch | grey card, white paper, white wall; the test mug read 229.6/230.0/229.8 afterwards |
| White balance, gray-world | `pk wb in out --grayworld [--mask m]` | the same gains from the image mean, clipped pixels excluded | wrong for scenes dominated by one hue: a warm kitchen turned blue, a blue product got R gain 1.44 |
| Gamma | `pk curve in out --gamma 1.2` | LUT 255 (v / 255)^(1/gamma) | gamma 1.2 lifts 64 to 80.6 and 128 to 143.6 |
| Curves | `pk curve in out --points 0,0 64,56 128,128 192,202 255,255` | monotone cubic through the points (no overshoot) | gentle S: 64 → 56, 192 → 202 |
| Output sharpening | `pk sharpen in out --radius 0.6-1.0 --percent 50-100 --threshold T` | detail = Y - G_r(Y); RGB += amount x detail where abs(detail) >= T | screen output at final size; T = 2.5 x grain_hp_std keeps grain intact (test: T 8 left 3.14 unchanged, T 2 raised it to 4.08) |

All maths runs in float; exposure and white balance in linear light. Avoid 8-bit colour-space round
trips: Pillow's RGB to YCbCr to RGB alone moved pixels by MAE 2.0 (max 3) in a test. Core, for when
the script is not at hand:

```python
import numpy as np
lin = lambda c: np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
enc = lambda c: np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.clip(c, 1e-9, 1) ** (1 / 2.4) - 0.055)
y = rgb @ [0.299, 0.587, 0.114]; lo, hi = np.percentile(y, [0.5, 99.5])
rgb = np.clip((rgb - lo) / (hi - lo), 0, 1)                         # levels (rgb float 0..1, HxWx3)
m = lin(rgb[y0:y1, x0:x1]).reshape(-1, 3).mean(0)                   # neutral patch
rgb = np.clip(enc(lin(rgb) * (m.mean() / m)), 0, 1)                 # white balance in linear light
rgb = (255 * rgb ** (1 / 1.2)).round() / 255                        # gamma 1.2
```

## 3. Cleanup with the router

1. Mask each distraction: `image_segment {image, prompt}` for nameable things, `masktool rect`
   (`--ellipse` for specks) or `polygon` for the rest; union several with `ImageChops.lighter`.
2. Grow by max(8, 0.015 s), s = short side (3000 px: 45 px): `masktool threshold` then
   `grow --px N`; thin wires and scratches max(6, 0.01 s) (hub sizing table). Overlay and Read.
3. Fill: `image_edit {image, mask, instruction: "Fill the masked area with <what continues there:
   the seamless grey paper backdrop>, matching texture, grain and light; nothing else changes."}`.
   Describe the fill content, never the object. Strict inpainting: IMAGE_EDIT on fal
   `fal-ai/flux-pro/v1/fill` (white = edit); Opper mask-capable models and OpenRouter's
   mask-as-reference approximation work with the hub's extra checks.
4. Composite back: the server keeps every pixel outside the mask (`preserve_unmasked: true`, 1-2 px
   feather). For a softer join in skies and gradients: `preserve_unmasked: false`, `masktool feather`
   4-8 px, `masktool composite orig edit feather out`.
5. Containment: `grow mask diffmask --px 3`;
   `masktool diff orig edit --mask diffmask --max-outside 0.5 --min-inside 2` (exit 1 on failure):
   outside MAE <= 0.5 (0.0 with the server composite), inside >= 2 (below = no-op).
6. Fills are often cleaner than the plate: `pk grain-measure fill.png --mask grownmask.png` against the
   plate, then add grain inside the mask (section 6).

At most ~15 % of the frame per call. Visible repeats or cloned-looking texture: undo and do two
smaller passes with different masks. Specks on a seamless white backdrop are cheaper to remove by
compositing onto exact white (section 9) than by a model call.

## 4. Plate-matching checklist

| Property | Measure | Fix with | Pass |
|---|---|---|---|
| Light direction | shadow of a reference object: angle = atan2(dy, dx) from base centre to tip; length / object height; highlight side | `shadow --angle --length`, `ramp` + `dodge` on the element | element shadow within ~10 degrees; highlights on the same side |
| Light hardness | penumbra width of the reference shadow relative to object height (hard sun ~2 %, softbox 5-15 %) | `shadow --blur` / `--blur-far` (% of subject width) | edge softness alike at equal distance from the base |
| Shadow density | opacity = 1 - Y_shadow / Y_lit, linear Y from `pk stats --mask` on the same material | `shadow --opacity` | within ~0.05 |
| Colour temperature | OKLab a, b of a neutral in each plate | `transfer --std-clamp 1,1` neutral to neutral | dE_OK between the neutrals <= 0.02 |
| Black and white points | p0.5 / p99.5 per plate (`stats`) near the placement | `levels` / `curve` on the element | the element's blacks no deeper than the plate's at that depth (haze lifts them) |
| Horizon, camera height | horizon row y_h from converging lines; ellipse ratio of round tops and bases (about sin of the viewing angle) | choose or regenerate an element shot from that height; warping fixes little | ellipses of element and plate agree at the same image row |
| Scale | known object: px per cm at its base row; on one ground plane H_px = H_real (y_base - y_h) / h_cam | `masktool over --scale` | within ~5 % of the expected size |
| Depth of field | 10-90 % edge rise w of plate edges at the subject's depth; Gaussian sigma = w / 2.563 | blur the element by sqrt(sigma_plate^2 - sigma_element^2) | edge rise within ~25 % |
| Noise and grain | `grain-measure` on both at the final scale | `grain-add` (section 6) | within 5 % |

## 5. Colour transfer (Reinhard, masked)

Reinhard et al. (2001) match per-channel mean and standard deviation in a decorrelated opponent space;
OKLab and CIELAB serve the same purpose. Statistics come from masked regions, the result is applied
to the whole element, partially:

```python
S, R = to_space(src, "oklab"), to_space(ref, "oklab")  # float HxWx3 sRGB in, OKLab out (photokit)
ms, ss = S[src_mask].mean(0), S[src_mask].std(0)       # stats region in the element
mr, sr = R[ref_mask].mean(0), R[ref_mask].std(0)       # matching region in the plate
ratio = np.clip(sr / np.maximum(ss, 1e-6), 0.67, 1.5)  # std ratio clamped; (1, 1) = mean shift only
T = (S - ms) * ratio + mr
out = S + strength * (T - S)                           # strength 0.3-1.0; restrict channels if needed
rgb = from_space(out, "oklab")
```

`pk transfer src ref out --src-mask m1 --ref-mask m2 [--channels L,a,b] [--strength 0.6] [--std-clamp 0.67,1.5] [--space oklab|lab]`

| Region pair | Settings | Effect |
|---|---|---|
| neutral on the element (label paper, white cap) to a neutral in the plate (white mug, grey wall) | `--std-clamp 1,1 --strength 0.7-1.0` | light colour and white point, product colours kept |
| same material in both (sky to sky, skin to skin, foliage) | full mean and std, strength 0.5-0.8 | texture contrast and tone |
| whole element to whole background | avoid; at most chroma at strength <= 0.3 | turns a blue bottle beige |

Then the local tweak: exposure differences in OKLab L between where the neutral was sampled and where
the element sits convert as EV = 3 log2(L2 / L1) (L is the cube root of luminance for neutrals);
apply with `pk dodge --ev`, and a light falloff across the element with `pk ramp` + `pk dodge --mask`.
Compare before and after: `pk hist sheet.png elem.png:mask before.png:mask plate.png:refmask` and the
`stats` means and percentiles.

## 6. Grain matching

1. Plate: `pk grain-measure plate.png` → `grain_hp_std`: median high-pass std of luma
   (Gaussian sigma 1.5 px removed) over the flattest 10 % of 32 px blocks, mid-tones only.
2. Element: on the composite, inside its subject mask eroded 4 px (`masktool grow --px -4`),
   `--block 16`.
3. `pk grain-add comp.png out.png --target T --current C --mask subj.png [--chroma 0.35] [--size 0.5]`:
   noise std = sqrt(T^2 - C^2) / (g k), g = high-pass gain of the noise (0.945 for white noise at
   sigma 1.5), k = luma share of the mono plus chroma mix. Re-measure: within 5 % of T.
4. `--chroma` sets the per-channel (colour) share, 0 = pure luminance grain; `--size` blurs the noise
   field for coarse film grain or upscaled plates. Judge on a 200 % crop next to the plate.

Grain is measured at the final scale (resizing changes it). An element noisier than the plate is
blurred (sigma 0.5-1 px), never "matched" by adding more. grain-add tapers to zero within 3 % of pure
black and white, so marketplace whites stay 255.

## 7. Shadows and reflections

Build them on the background, then put the element on top with the same scale and position:

```bash
pk shadow cut.png bg.png s1.png --x X --y Y --scale S --kind contact --opacity 0.6 --squash 0.08 --below 0.25 --blur 3
pk shadow cut.png s1.png s2.png --x X --y Y --scale S --kind cast --angle -28 --length 0.94 --opacity 0.45 --blur 1.5 --blur-far 6
pk reflect cut.png s2.png s3.png --x X --y Y --scale S --opacity 0.3 --fade 0.35 --blur 1   # glossy surfaces only
"$PY" "$MT" over cut.png s3.png comp.png --scale S --x X --y Y
```

- Contact: the element's alpha squashed to 6-10 % of its height, 75 % hidden behind the base,
  blurred 2-4 % of its width, opacity 0.5-0.7: darkest where it touches. Without it things float.
- Cast: the silhouette projected along the measured light direction (`--angle` must point into the
  ground plane, abs(sin) >= 0.1), blur growing from `--blur` to `--blur-far`, opacity falling to
  30 % at the tip. Daylight shadows take a cool tint: `--color '#1b2433'`.
- Shadows multiply in linear light (opacity = share of light blocked), matching the measured density.
- Reflection: flipped, faded over 30-40 % of the height, 0.2-0.35 opacity, on glass, gloss, water.
- Optional harmonise (router): `image_edit` without mask, "Harmonise the lighting and colour of the
  <element> with the scene, soft light from the left; keep its shape, label text, colours and position
  unchanged; do not add or move objects." Needs an instruction-edit model on IMAGE_EDIT (a fill-only
  model cannot do it). Then containment on the subject alpha:
  `masktool diff pre.png harm.png --mask subj.png` → inside MAE <= 6 keep; above, the model redrew the
  element: `masktool over cut.png harm.png restored.png` with the same scale and position (the new
  grade and shadows around it stay). Outside MAE 2-8 is normal re-rendering: compare the sheet.

## 8. Cutout quality

- Matte: `image_remove_background`. For hair, fur, lace and glass edges, IMAGE_BG_REMOVAL on fal
  BiRefNet v2 (`fal-ai/birefnet/v2`) with `params: {"model": "Matting", "operating_resolution":
  "2048x2048"}` (or the same JSON in `IMAGE_BG_REMOVAL_PARAMS`; check `warnings` for dropped
  parameters); hard products: BRIA RMBG 2.0 (`fal-ai/bria/background/remove`). The `provider_run`
  tool of older docs does not exist on the current `image` server. Not configured: Open doubt naming
  IMAGE_BG_REMOVAL_URL, _KEY, _MODEL.
- Inspect over black and over white (`masktool over cut.png black.png`, `... white.png`, one sheet);
  `imgcheck info` `alpha_partial_frac` above ~0.05 on a hard product = soft, fringed matte.
- Hard-edged halo: defringe: `split-alpha cut rgb a`, `grow a a1 --px -1`, `feather a1 a2 --px 0.8`,
  `merge-alpha rgb a2 clean`.
- Background spill in hair (green or the old wall colour in soft pixels): `pk decontam cut out
  --radius 3` re-estimates edge colours from nearby opaque pixels and keeps the alpha. Test on a
  green-screen strand sample: spill (mean G-R on edges) 106 → -60 with every visible pixel kept;
  defringe left 67.5 and removed 13.5 % of the visible pixels (the thin strands).
- Edge sharpness must match the plate at that depth (section 4, depth of field row).

## 9. Product retouch

- Straighten: `pk persp in out --src <label TL TR BR BL> --dst <the rectangle they belong on>`
  (bicubic; areas outside the source fill white, transparent for RGBA); keystone the same way.
- Dust, seams, scratches: section 3 masks (mould seams: thin polygons grown max(6, 0.01 s)). Never
  remove real features the buyer gets: printed text, capacity marks, certification logos, actual
  defects of used goods.
- Pure white background: crop the cutout to its alpha box
  (`"$PY" -c "from PIL import Image; c=Image.open('cut.png'); c.crop(c.getchannel('A').getbbox()).save('tight.png')"`),
  composite it onto an exact white W x H canvas with `masktool over` at s = 0.87 x min(W / w, H / h),
  x = (W - w s) / 2, y = (H - h s) / 2, then `pk whitebg packshot.png --fill 0.85` (exit 1 on
  failure): `border_exact_white` 1.0, `off_white_outside_product` 0, `fill_long_side` >= 0.85.
  Re-run it on the exported JPEG.
- Colour accuracy: `pk swatch packshot.png --mask swatch.png --ref '#3a70a8'` → `dE_OK` <= 0.02
  (about one just-noticeable difference, the OKLab JND that CSS Color 4 gamut mapping uses) on the
  neutral-light packshot. A lifestyle composite legitimately shifts it (worked example: 0.067 under
  warm light).
- Marketplace rules and the checks that map to them: [disclosure and marketplaces](references/disclosure-and-marketplaces.md).

## 10. Portrait limits and disclosure

- Without extra consent: exposure, colour, white balance, crop, stray hairs, temporary blemishes,
  background distractions. With consent stated by the caller only: face or body shape, slimming,
  skin beyond temporary blemishes, age, permanent features (moles, scars, tattoos), expression, skin
  tone, placing a person into another scene (hub ground rule 6). Never IDs, documents, evidence.
- Keep skin texture: frequency separation (low = Gaussian sigma 4-8 px, high = image - low); even
  tone on the low layer, keep the high layer. Check `grain-measure --mask skin.png` before and after:
  keeping less than ~75 % of the high-pass energy reads as plastic (a working threshold).
- Disclosure (report to the caller, never certify compliance): France requires "Photographie
  retouchée" on commercial photos of models whose silhouette was made thinner or thicker (since
  1 Oct 2017; fine 37,500 EUR, up to 30 % of the ad spend); Norway requires a standard label on ads
  where body shape, size or skin was changed, filters included (since 1 July 2022); the EU AI Act
  art. 50(4) requires disclosure of AI-generated or AI-manipulated photoreal "deep fake" images (from
  2 Aug 2026). Details and consent table: [disclosure and marketplaces](references/disclosure-and-marketplaces.md).

## 11. Worked example: product cutout into a generated lifestyle scene

Brief: put the studio bottle on the counter of the generated kitchen scene (1600x1067) next to the
mug, "shot together"; deliver the composite and `steps.jsonl`. Numbers are from a run of these
commands on test plates; IMAGE_BG_REMOVAL on fal BiRefNet v2, IMAGE_EDIT an instruction model.

1. Assess. `grain-measure 00-scene.png` → `grain_hp_std` 3.14. Mug shadow: base centre (365,780) to
   tip (515,700) → angle -28 degrees, length 170 px / mug 180 px = 0.94; `stats --mask` shadow vs lit
   counter Y 0.1296 / 0.2357 → opacity 0.45. Scale: mug 180 px ≈ 9.5 cm → 19 px/cm, so a 20 cm bottle
   ≈ 380 px. Wall OKLab L: 0.874 at the mug, 0.835 and 0.821 at the bottle's left and right edges.
2. Matte. `image_remove_background {image: "$J/00-product.png", output_dir: "$J", params: {"model":
   "Matting"}}` → `01-cut.png` (520x900); over-black/over-white sheet clean, `alpha_partial_frac`
   0.018: hard edge, no defringe.
3. Colour. Neutral pair: label strip `masktool rect 01-cut.png 03-label.png --box 95,485,425,515`,
   lit side of the mug `rect 00-scene.png 03-mug.png --box 310,620,345,760`;
   `pk transfer 01-cut.png 00-scene.png 03-cut-matched.png --src-mask 03-label.png --ref-mask 03-mug.png --std-clamp 1,1 --strength 0.85`
   → label OKLab (0.974, 0.001, -0.003) → (0.939, 0.003, 0.018); mug (0.933, 0.002, 0.022).
4. Light. 3 log2(0.835 / 0.874) = -0.20 EV to the bottle's position, 3 log2(0.821 / 0.835) = -0.07 EV
   across it: `pk dodge 03-cut-matched.png 04-cut-exp.png --ev -0.20`;
   `pk ramp 04-ramp.png --like 04-cut-exp.png --from 60,0 --to 460,0`;
   `pk dodge 04-cut-exp.png 04-cut-lit.png --ev -0.07 --mask 04-ramp.png`.
5. Shadows, scale 0.42 (378 px tall) at x 760, y 422: contact `--opacity 0.6 --squash 0.08
   --below 0.25 --blur 3`, then cast `--angle -28 --length 0.94 --opacity 0.45 --blur 1.5 --blur-far 6`
   (commands as in section 7) → `05-shadows.png`; subject box x 785-952, y 426-795.
6. Place: `"$PY" "$MT" over 04-cut-lit.png 05-shadows.png 06-comp.png --scale 0.42 --x 760 --y 422`;
   subject mask: `over` onto a transparent canvas of the scene size → `06-placed.png`, then
   `from-alpha 06-placed.png 06-subj.png --keep-subject`, `grow 06-subj.png 06-core.png --px -4`.
7. Grain: element 0.0 on `06-core.png`; `pk grain-add 06-comp.png 07-grain.png --target 3.14
   --current 0 --mask 06-subj.png --chroma 0.35` (noise std 3.44) → re-measured 3.148.
8. Harmonise (optional): `image_edit` as in section 7 → `08-harm.png`; `masktool diff 07-grain.png
   08-harm.png --mask 06-subj.png`: inside MAE <= 6 keep it, else restore the bottle with `over`.
9. Finish: `pk sharpen 07-grain.png 09-final.png --radius 0.6 --percent 60 --threshold 8`
   (8 ≈ 2.5 x 3.14: grain stays 3.148). Verify: `masktool diff 00-scene.png 09-final.png --mask
   06-subj.png` → outside MAE 0.24, 0.96 % of pixels changed, all in the shadow zone (0.13 with the
   subject grown 40 px); `imgcheck expect 09-final.png --aspect 3:2` passes; `pk hist` of label vs
   mug; sheet scene / comp / final / cutout on black, Read; swatch of the bottle blue vs the studio
   value dE_OK 0.067 (expected under warm light, noted). Flatten to RGB for delivery
   (`alpha_effective` false), then the `visual-reviewer` round.

Log lines (one per numbered file), for example:

```json
{"step":3,"op":"photokit transfer","in":["01-cut.png","00-scene.png","03-label.png","03-mug.png"],"out":"03-cut-matched.png","params":{"space":"oklab","std_clamp":"1,1","strength":0.85},"notes":"label L,a,b 0.974,0.001,-0.003 -> 0.939,0.003,0.018; mug 0.933,0.002,0.022"}
{"step":7,"op":"photokit grain-add","in":["06-comp.png","06-subj.png"],"out":"07-grain.png","params":{"target":3.14,"current":0,"chroma":0.35},"notes":"remeasured 3.148"}
```

## 12. Failure table

| Symptom | Cause | Fix |
|---|---|---|
| light or dark halo around the element | old background in the edge pixels | defringe (hard edges) or `decontam` (hair), check over black and white |
| element floats | no contact shadow, base not on the ground row | contact shadow; move the base to the ground plane row |
| element looks pasted on | cleaner or sharper than the plate | grain-add to the measured value; blur by the depth-of-field sigma |
| mismatched sharpness | different capture or resize history | blur the sharper plate (sigma from edge rise) or sharpen the softer one at final size |
| wrong colour cast on the element | stats taken from non-neutral regions | neutral-to-neutral transfer with mean shift only |
| product colour changed | whole-subject Reinhard, gray-world | redo from the cutout; swatch check |
| two light directions | cast shadow or highlights disagree with the plate | re-measure the reference shadow angle; ramp the other way |
| plastic skin | smoothing on the high frequencies, strength too high | reduce strength, restore the high-pass layer, check texture energy |
| repeated or cloned texture after cleanup | one big fill | two smaller passes with different masks |
| white background reads 254 | resize, export or grain on the background | composite onto exact white last; `whitebg` on the exported file |
| harmonise redrew the product | unmasked re-render | restore the original element on top (section 7) |

## Pitfalls

- Doing exposure, white balance or shadows on gamma-encoded values: mid-tones shift; work in linear
  light (photokit does).
- 8-bit colour-space round trips (YCbCr, HSV) drift by about 2 levels per trip.
- Gray-world on scenes or products dominated by one hue.
- Reinhard across unrelated regions; std ratios unclamped on a flat element explode its contrast.
- Measuring grain or sharpness before the final resize; sharpening with a threshold below the grain.
- Shadows composited over the element instead of under it; placement numbers that differ between
  the shadow, the `over` and the restore steps (log x, y and scale once, reuse them).
- JPEG intermediates: keep PNG until export; masks always PNG.
- EXIF orientation handled by one tool and not another: normalise at step 0.
- One IMAGE_EDIT model serves both cleanup and harmonise: a fill-only model cannot harmonise and an
  instruction model is a weaker inpainter; plan the passes around what `image_ops_status` shows.
- Disclosure and consent are the caller's decisions: flag them, never decide them.

Related: `image-generation`, `visual-review`, `image-brief-writing`, `social-asset-kit`, `vector-art`,
hub `image-editing`.
