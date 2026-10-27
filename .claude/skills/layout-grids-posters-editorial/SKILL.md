---
name: layout-grids-posters-editorial
description: "Layout grids and composition for pages, screens, posters, editorial spreads and slides: column, modular and baseline grid math, spacing scales, responsive CSS grids, hierarchy and squint tests, grid-overlay checks, formats by viewing distance, editorial furniture, academic posters, 16:9 slides and HTML/Typst-to-PDF render-check loops. Load when composing, critiquing or producing any layout."
when_to_use: "Composing or critiquing a poster, flyer, social post, ad, slide, editorial spread, academic poster or landing-page layout; choosing columns, margins, gutters, a baseline or spacing scale; a layout that looks crowded, misaligned or flat; .html/.css/.typ print layouts or InDesign/Affinity hand-off specs; checking a rendered PNG or PDF against its grid."
---

# Layout grids, posters and editorial

Every element sits on a declared line: a column edge, a module edge or a baseline. A layout is
done when the grid is stated in numbers, an overlay of that grid on the render shows every edge
landing on a line, the squint test shows one focal point, and the hub `graphic-design` critique
rubric (10 criteria x 0-3) scores >= 22/30 with no zero.

Deep material: [formats and furniture](references/formats-and-furniture.md) (paper and screen
sizes, viewing-distance table, editorial and academic-poster specs, slide grid) |
[production recipes](references/production-recipes.md) (full HTML/CSS, Typst and Playwright
files used below, hand-off sheet, render loop).

Helper [gridcheck.py](scripts/gridcheck.py) (`columns`, `modular`, `spacing` are stdlib; `overlay`, `squint` need Pillow):

```bash
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"
PY="$STACK/.venv/bin/python"; GC="$STACK/.claude/skills/layout-grids-posters-editorial/scripts/gridcheck.py"
"$PY" "$GC" --help      # lengths take px, mm, pt or in suffixes; --unit sets the default
```

Shell variables do not persist between Bash calls: repeat the two lines in every call.

## 1. Column grids

```
column = (W - 2M - (n - 1) G) / n          W canvas, M outer margin, G gutter, n columns
```

| Canvas | n | G | M | Column |
|---|---|---|---|---|
| Web 1440 px | 12 | 24 | 72 | (1440 - 144 - 264) / 12 = **86 px** |
| Social 1080 px | 6 | 24 | 64 | 138.67 px: snap M to **60** for exact **140 px** |
| Slide 1920 px | 12 | 24 | 96 (5%) | **122 px** |
| A2 poster 420 mm | 6 | 4.94 mm (14 pt) | 21 mm (5%) | **58.88 mm** |
| Phone 375 px | 4 | 16 | 16 | 73.75 px: use fluid `1fr` columns, not fixed px |

Snap margins so columns are whole pixels (fractional columns blur edges and drift in exports):
`python3 -I "$GC" columns 1080 6 --gutter 24 --margin 64 --snap` lists M = 60 (140 px),
72 (136 px), 48 (144 px). Prefer the smallest change that stays on the spacing scale.

| Content | Grid | Why |
|---|---|---|
| continuous reading: book, report, long article | manuscript (1 column at a 45-75 character measure) | the measure, not the page, sets the width |
| web pages, dashboards, mixed editorial | column grid, 4 / 8 / 12 columns | 12 divides by 2, 3, 4, 6 |
| posters, catalogues, image-heavy editorial | modular (columns x rows) | images and text blocks snap to modules |
| multi-column text, print | baseline grid = body leading | lines align across columns and pages |
| one-off hero or landing composition | hierarchical / custom | still declare its key lines and margins |

## 2. Modular and baseline grids

- Baseline B = body leading (10/14 pt print, 16/24 px web). Gutters = B, so modules read square.
- Module height = k x B with one B between rows. n rows fill a text area of
  `T = (n k + n - 1) B`; pick n, then the integer k that leaves sensible margins:
  `python3 -I "$GC" modular 594mm --leading 14pt --rows 8 --min-margin 20mm --unit mm`
  gives k = 13: T = 548.22 mm, 45.78 mm left for top + bottom (21 + 24.78).
- Every style's line pitch is a multiple of B: 10/14 (1 B), 20/28 (2 B), 28/42 (3 B),
  84/84 (6 B). Space above and below headings is also a multiple of B.
- First baseline sits one pitch below the module top (cap height hangs inside the module).
- Spreads: inner margins are smaller than outer (two inner margins meet at the spine) and top
  smaller than bottom. Reference: Van de Graaf canon = inner W/9, top H/9, outer 2W/9, bottom
  2H/9; the text block is 2/3 of the page in each direction (margins 2:3:4:6 on a 2:3 page).
  A4: 23.3 / 33.0 / 46.7 / 66.0 mm, text block 140 x 198 mm. Content-dense work uses tighter
  margins in the same proportions; add the printer's binding allowance for perfect binding.

## 3. Spacing scale

Base 4 (dense UI) or 8 (marketing, print-like): 4, 8, 12, 16, 24, 32, 48, 64, 96, 128.

| Relation | Rule |
|---|---|
| inside a group (label to field, headline to deck) | at most half the space between groups (ratio >= 1:2) |
| between groups / sections | next step up or two (24 → 48, 32 → 64) |
| outer margin, posters and social | >= 5% of the short side (54 px on 1080; 21 mm on A2); more for premium work: cramped margins read cheap |

Off-scale values are defects: `python3 -I "$GC" spacing src/**/*.css tokens.json` prints
`file:line property: value -> nearest` for margin, padding, gap, inset and Figma-style keys
(`itemSpacing`, `paddingLeft`) and exits 1. `var()`, `calc()` and `clamp()` are skipped:
audit the token definitions. Override with `--scale 0,4,8,12,16,20,24,32,40,48,64`.

## 4. Responsive grids

Design content-first: add a breakpoint where the content breaks (measure above 75 characters,
cards below their minimum width), not at device names.

| Range | Columns | Margin | Gutter |
|---|---|---|---|
| phones 360-430 | 4 | 16-24 | 16 |
| tablet 768 | 8 | 32 | 24 |
| laptop 1024-1280 | 12 | 32-64 | 24 |
| desktop 1440+ | 12 in a max-width container | 64-80 | 24-32 |

```css
.page  { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); column-gap: var(--g, 24px);
         padding-inline: var(--m, 64px); max-width: 1440px; margin-inline: auto; }
@media (max-width: 767px) { .page { grid-template-columns: repeat(4, minmax(0, 1fr)); --g: 16px; --m: 16px; } }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 18rem), 1fr)); gap: 24px; }
.card  { display: grid; grid-row: span 3; grid-template-rows: subgrid; }  /* title, body, footer align across cards */
.aside { container-type: inline-size; }
@container (min-width: 28rem) { .teaser { display: grid; grid-template-columns: 1fr 2fr; } }
```

`minmax(0, 1fr)` instead of `1fr` (= `minmax(auto, 1fr)`) stops a long word or image from
widening one column. Media queries lay out the page from the viewport; container queries let a
component adapt to the slot it is placed in (the same teaser in a sidebar and in the main
column). Subgrid and size container queries work in all current engines (Baseline 2023).

## 5. Hierarchy and composition

| Lever (strongest first in most layouts) | Use | Watch |
|---|---|---|
| size | primary message 2-4 scale steps above the rest | too many big things cancel out |
| value contrast | dark/light against the ground | measure text pairs (WCAG) |
| position | top-left in LTR, optical centre a little above geometric | |
| isolation | whitespace around the focal element | crowding kills it |
| weight | bold for the one thing to read first | |
| hue / saturation | one accent colour for the action | never the only cue |
| motion (screens) | one moving element at most | respect `prefers-reduced-motion` |

- One focal point per view; three emphasis levels (primary, secondary, body), never five.
- Group by proximity, similarity, common region, continuity, closure and figure-ground before
  adding boxes or rules.
- Reading patterns: Z for sparse layouts (posters, heroes, social), F for text-heavy screens;
  the call to action sits at the Z terminal (bottom right in LTR).
- Balance: symmetric for formal and institutional work, asymmetric with a counterweight for
  dynamic work; a large light shape balances a small dark one.
- Optical corrections: circles and triangles overshoot the square's edges by about 1-3% of
  their size; align round and pointed shapes optically, not by bounding box.

Squint test: `"$PY" "$GC" squint render.png squint.png --scale 0.25` (greyscale, blurred), then
Read `squint.png`. The first blob you see must be the primary message, the second the action. Two
blobs competing: demote one by size, value contrast or saturation, then re-run.

## 6. Grid-overlay verification

1. Render at a known scale: 1x PNG for screens; PDF → PNG at 100 ppi for print (section 10).
2. Overlay the declared grid and Read the result:
   `"$PY" "$GC" overlay post.png post-grid.png --cols 6 --gutter 24 --margin 60 --baseline 8`;
   print at 100 ppi: `... --unit mm --ppi 100 --gutter 14pt --margin 21mm --rows 8 --baseline 14pt`.
   Red fields are columns and modules, cyan lines baselines.
3. For HTML, measure instead of eyeballing: inject the CSS overlay and dump element boxes with
   Playwright, then compare every `left`/`right` with the edges `gridcheck columns` printed:

```css
body::after { content: ""; position: fixed; inset: 0 60px; pointer-events: none; z-index: 2147483647;
  background: repeating-linear-gradient(to right, rgb(255 0 64 / .18) 0 140px, transparent 140px 164px),
              repeating-linear-gradient(to bottom, rgb(0 170 255 / .3) 0 1px, transparent 1px 8px); }
```

4. Pass: every edge within 1 px of a line at 1x (0.5 mm in print), every text baseline on a
   baseline. Report misses as `element - edge - distance - fix`.

## 7. Posters

Readable size from viewing distance: cap height ≈ distance / 250 (comfortable) to / 300;
font size ≈ cap height / cap-height ratio (about 0.7-0.73 em for common sans; check the font).

| Read from | Cap height | Size (cap 0.72 em) | Typical role |
|---|---|---|---|
| 1 m | 3.3-4 mm | 13-16 pt | details, fine print |
| 2 m | 6.7-8 mm | 26-31 pt | date, venue, body |
| 5 m | 17-20 mm | 66-79 pt | headline on A2/A1 |
| 10 m | 33-40 mm | 131-157 pt | headline on A0 or a banner |

Sizes (mm): A0 841 x 1189, A1 594 x 841, A2 420 x 594, A3 297 x 420; US 18 x 24 in, 24 x 36 in.
Pixels at 300 ppi and bleed: [formats and furniture](references/formats-and-furniture.md).

- 3-second test: shown for 3 s at 15-20% size (or the squint render), a viewer names what,
  when and where. Fail → cut words, enlarge the headline, remove a competing element.
- Headline about 7 words or fewer; one dominant image; at most three text levels.
- QR codes: symbol >= 20 mm and >= scan distance / 10 (rule of thumb; /8 in poor light or
  low contrast), quiet zone of 4 modules on every side, dark on light, error correction M
  (Q or H if anything overlaps it). Shorter URLs give fewer, larger modules: a 19-character URL
  is version 2 (25 x 25 modules), so 25 mm gives 1 mm modules and a 33 mm footprint. Scan the
  printed proof with two phones at the real distance.

```bash
uv run --python 3.13 --with segno python -I -c "import segno; q = segno.make('https://ex.org/dc26', error='m', micro=False); \
print(q.version, q.error, q.symbol_size(border=0)); q.save('qr.svg', scale=25 / q.symbol_size(border=0)[0], border=4, unit='mm')"
```

(`segno` raises the error level when capacity allows; it printed `2 Q (25, 25)` here.)

## 8. Editorial furniture and images

| Element | Spec |
|---|---|
| kicker / overline | small caps or caps +6-10% tracking, accent colour, 1 line |
| headline | 2-4 scale steps above body, balanced lines (`text-wrap: balance`), no widow |
| deck (dek) / standfirst | 1.25-1.5x body, 1-3 lines, between headline and body |
| byline, dateline | meta size, one style everywhere |
| drop cap | 3 lines deep (`initial-letter: 3` in Chromium and Safari, `-webkit-` prefix in Safari, not in Firefox at last check: keep a float fallback in `@supports not`) |
| pull quote | 1.5-2x body, at most 3 lines, not on the same spread as the quoted sentence |
| subheads | body size bold or one step up, space above > space below |
| captions + credits | one caption style, touching the image or within one gutter |
| folio, running head / foot | outer margin, same baseline on every page |
| jump line | "Continued on page 12" / "Continued from page 1", same style both ends |

- Measure: 35-70 characters; 45-75 (about 66) for single-column body, 35-50 per column in
  multi-column layouts. Estimate: characters ≈ column width / (0.5 x font size), then measure.
- Crop to the focal point: eyes near the upper third line in portraits, lead room in the gaze
  or motion direction, never cut at joints. Bleed (to the trim plus 3 mm) for impact, boxed on
  the module grid for calm; one choice per spread.
- Effective resolution = pixel width / placed width in inches: >= 300 ppi in print (150 ppi for
  large format viewed from a distance).

## 9. Academic posters and slides

| Item | Academic poster (A0) | Slide (1920 x 1080) |
|---|---|---|
| grid | portrait 3 columns, landscape 4; 25-40 mm margins | 12 columns, G 24, M 96 → 122 px columns |
| safe area | trim margin | 5% each side: 96 px x 54 px (the 90% title-safe area) |
| title | band across the top 10-15%: title >= 72 pt, authors, affiliations, logos | 64-80 px, one line |
| body | >= 24 pt (cap ≈ 6 mm, readable at about 1.5-1.8 m) | >= 48 px (24 pt on PowerPoint's 13.33 x 7.5 in page) |
| content | numbered sections flowing down then across; one dominant figure | one idea, about 6 lines |
| captions | >= 18 pt | >= 32 px |

"24 pt" is page-relative: on Google Slides' 10 x 5.625 in page it is 64 px at 1080. Specify
slide type in px of a 1920 x 1080 canvas or as a share of slide height. Projectors wash out
contrast: aim for >= 7:1 on body text.

## 10. Production and render-check loop

| Route | Page setup | Build |
|---|---|---|
| HTML/CSS print | `@page { size: 420mm 594mm; margin: 21mm 21mm 24.78mm; bleed: 3mm; marks: crop cross; }` | `weasyprint poster.html poster.pdf` (`--pdf-variant pdf/x-4` exists) or `pagedjs-cli poster.html -o poster.pdf` |
| HTML screen PDF | `@page { size: 1920px 1080px; margin: 0 }` | Playwright `page.pdf(path=..., prefer_css_page_size=True, print_background=True)` |
| Typst | `#set page(paper: "a2", margin: (...))` | `typst compile poster.typ poster.pdf`; `--format png --ppi 100` renders PNG directly |
| InDesign / Affinity | hand-off sheet (below) | the designer builds it; you verify the exported PDF |

Hand-off sheet: page size and bleed; margins; columns and gutter; rows and row gutter (InDesign
Layout → Create Guides, Affinity Guides Manager); baseline grid start and increment; paragraph
styles (font, size/leading, tracking, align to baseline grid); swatches (HEX plus CMYK or spot);
font files and licences; image links with effective ppi. Template:
[production recipes](references/production-recipes.md).

Loop (stop after 3 rounds without a rubric gain; report the blocker):

```bash
pdffonts poster.pdf                         # every font "emb yes" (pikepdf check in the recipes if poppler is absent)
pdftoppm -r 100 -png poster.pdf out/poster  # or: gs -q -dSAFER -dBATCH -dNOPAUSE -sDEVICE=png16m -r100 -o out/poster-%d.png poster.pdf
"$PY" "$GC" overlay out/poster-1.png out/poster-grid.png --unit mm --ppi 100 --cols 6 --gutter 14pt --margin 21mm \
  --margin-bottom 24.78mm --rows 8 --baseline 14pt
"$PY" "$GC" squint out/poster-1.png out/poster-squint.png --scale 0.25
```

Read the render, the overlay and the squint image; score the rubric; fix the top three issues
by impact; rebuild. Print colour, PDF/X and preflight: sibling `print-prepress-pdfx`.

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| everything centred, everything big | no hierarchy decision | pick one focal element; left-align the rest to a column edge |
| equal spacing everywhere | groups not expressed | within-group space <= half of between-group space |
| elements aligned to nothing | no declared grid | state the grid, run the overlay, move edges to lines |
| copy over a busy image area | image placed before copy space was reserved | move copy, crop differently, or scrim measured over pixels (sibling `social-asset-kit`) |
| crop cuts the focal point | crop chosen per format by eye | crop around a declared focal box; check every format |
| QR too small or no quiet zone | QR treated as decoration | >= 20 mm, >= distance / 10, 4-module quiet zone, scan the proof |
| caption styles differ between pages | ad-hoc formatting | one caption paragraph style |
| headline widow or orphan | default line breaking | `text-wrap: balance`, manual break, or edit the copy |
| baselines drift between columns | leading not a multiple of B, or spacing off-grid | pitches and paragraph spacing as multiples of B |
| text below 24 pt on an academic poster | A4 habits scaled up | size from viewing distance (section 7) |
| 1fr columns of unequal width | `1fr` min-content blow-out | `minmax(0, 1fr)` |

## 12. Worked example: 1080 x 1350 webinar post

Brief (hub intake): developers on LinkedIn mobile, register for a 12 Nov webinar.
Grid: 6 columns, M 60, G 24 → 140 px columns, column edges 60/200, 224/364, 388/528, 552/692,
716/856, 880/1020; 4 px spacing scale. Type: scale 1.333 from 18 px → 18/24/32/43/57/76;
headline 76/80 bold, -2% tracking, two balanced lines; date 57/64 + 32/40; CTA 24 px bold in a
56 px button. Colour: ground #1A1A2E with white text 17.06:1; the brand pink #E94560 fails as
text on the ground (4.46:1), so one hue gives two tokens: `accent-on-dark` #EC4862 (4.61:1, the
kicker) and `accent-fill` #D63151 behind white (4.75:1, the button).

```css
.post { display: grid; height: 100%; padding: 60px; column-gap: 24px;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        grid-template-rows: 32px 32px 160px 64px 1fr 64px 56px; }   /* kicker, gap, headline, gap, art, gap, CTA */
.kicker { grid-area: 1 / 1 / 2 / 4; }       h1 { grid-area: 3 / 1 / 4 / 6; }   /* headline columns 1-5 */
.when   { grid-area: 5 / 1 / 6 / 3; }       .art { grid-area: 5 / 3 / 6 / 7; margin-right: -60px; }  /* image 3-6, bleeds */
.who    { grid-area: 7 / 1 / 8 / 4; }       .cta { grid-area: 7 / 5 / 8 / 7; }  /* CTA at the Z terminal */
```

Spacing: kicker → headline 32 (same group), headline → art 64 and art → CTA 64 (between groups):
ratio 1:2. Playwright (installed Chrome: `p.chromium.launch(channel="chrome")`, viewport
1080 x 1350) rendered it and reported the boxes: kicker 60-528 x 60-92, h1 60-856 x 124-284,
art 388-1080 x 348-1170, when 60-364 from y 348, CTA 716-1020 x 1234-1290. Every x matches a
column edge, the art bleeds 60 px past the 1020 margin to the canvas edge, the bottom margin is
60 px; the CSS overlay screenshot confirmed it. Squint round 1: the illustration was as bright
as the headline (rubric 21/30, hierarchy 1). Fix: illustration exposure and chroma down
(art brief in sibling `image-brief-writing`); round 2 squint shows headline → art → CTA,
rubric 25/30. Deliver PNG sRGB, the HTML source, alt text and the contrast table.

## 13. Worked example: A2 event poster, 6 x 8 modules on a 14 pt baseline

Margins 21 mm (5% of 420), B = G = 14 pt = 4.939 mm, columns 58.88 mm, modules 13 B = 182 pt
= 64.21 mm, bottom margin 24.78 mm (section 2). Layout: rows 1-2 kicker 20/28 + headline 84/84
"Build faster. Ship safer." (cap ≈ 21 mm → readable at 5-6 m); rows 3-6 the one dominant image;
row 7 date and venue (cols 1-3) and programme (cols 4-6) at 20/28 (readable at about 1.3-1.5 m);
row 8 CTA 28/42 bold (cols 1-4) and a 25 mm QR plus 4 mm quiet zone (33 mm) in module (6, 8).

```typst
#let bl = 14pt
#let mg = 21mm
#let (cols, rows, k) = (6, 8, 13)
#let colw = (420mm - 2 * mg - (cols - 1) * bl) / cols
#let modh = k * bl
#set page(paper: "a2", margin: (x: mg, top: mg, bottom: 594mm - mg - rows * modh - (rows - 1) * bl))
#set text(font: ("Inter", "Helvetica"), size: 10pt, top-edge: bl, bottom-edge: 0pt)  // line box = pitch
#set par(leading: 0pt, spacing: bl)              // so every baseline lands on the 14 pt grid
#let type(size, lines, ..args, body) = { set text(size: size, top-edge: lines * bl, ..args); body }
#let at(c, r, cs: 1, rs: 1, body) = place(top + left, dx: (c - 1) * (colw + bl), dy: (r - 1) * (modh + bl),
  block(width: cs * colw + (cs - 1) * bl, height: rs * modh + (rs - 1) * bl, body))
#at(1, 1, cs: 6, rs: 2)[
  #type(20pt, 2, weight: "bold", fill: rgb("#D63151"))[DEVCONF 2026 · BERLIN]

  #type(84pt, 6, weight: "bold", tracking: -0.02em)[Build faster.\ Ship safer.]
]
#at(1, 3, cs: 6, rs: 4)[#image("hero.jpg", width: 100%, height: 100%, fit: "cover")]
#at(1, 7, cs: 3)[#type(20pt, 2)[*12-14 November*\ Arena Berlin, Hall 2\ Doors 09:00]]
#at(4, 7, cs: 3)[#type(20pt, 2)[40 talks, 12 workshops\ Keynote: Dr. A. Example]]
#at(1, 8, cs: 4)[#type(28pt, 3, weight: "bold")[Register free:\ ex.org/dc26]]
#at(6, 8)[#align(right + bottom, image("qr.svg", width: 33mm))]
```

Typst's default line box runs from cap height to baseline, so leading alone does not give a
baseline grid; `top-edge: <pitch>, bottom-edge: 0pt, leading: 0pt` does (verified: every
baseline measured at an integer multiple of 14 pt from the top margin). Build with
`typst compile poster.typ poster.pdf` and `typst compile --format png --ppi 100 poster.typ
poster.png` (1654 x 2339 px); the overlay command of section 10 showed kicker, headline and info
baselines on cyan lines, the image filling rows 3-6 exactly and the QR's quiet zone flush with
module (6, 8). Fonts: subset and embedded (pikepdf check). Then bleed, colour and PDF/X with
sibling `print-prepress-pdfx`.

## Quality gate

- [ ] Grid declared in numbers (columns, gutter, margins, baseline, modules) in the output.
- [ ] Overlay rendered and Read; misses listed or none.
- [ ] Squint render Read; one focal point; reading order matches the brief.
- [ ] Sizes justified by viewing distance (print) or platform minimums (screen).
- [ ] Spacing audit clean or deviations justified; text pairs measured for contrast.
- [ ] Rubric table with total and top fixes; fonts embedded; source files delivered.

Related: `type-scale-systems`, `print-prepress-pdfx`, `visual-accessibility-audit`,
`oklch-palette-ramps`, `ui-mockup-hifi`, `social-asset-kit`, `image-brief-writing`,
`brand-guidelines-system`, hub `graphic-design`.
