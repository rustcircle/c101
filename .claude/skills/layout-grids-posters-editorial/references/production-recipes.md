# Production recipes: HTML/CSS, Playwright, Typst, print CSS, hand-off, render loop

These files were built and rendered while writing the skill (Typst 0.15, Playwright 1.64 with
the installed Chrome, Pillow 13); the art slots now point at image files instead of the test
fills. Adapt names and sizes; keep the derivations.

## 1. Social post as HTML (1080 x 1350, 6 columns, M 60, G 24)

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<style>
  :root { --m: 60px; --g: 24px; --navy: #1A1A2E; --accent-on-dark: #EC4862; --accent-fill: #D63151; }
  * { box-sizing: border-box; margin: 0; }
  body { width: 1080px; height: 1350px; background: var(--navy); color: #fff;
         font-family: Inter, "Helvetica Neue", Arial, sans-serif; overflow: hidden; }
  .post { display: grid; height: 100%; padding: var(--m);
          grid-template-columns: repeat(6, minmax(0, 1fr)); column-gap: var(--g);
          grid-template-rows: 32px 32px 160px 64px 1fr 64px 56px; }
  .kicker { grid-area: 1 / 1 / 2 / 4; font: 700 18px/24px Inter, Arial, sans-serif; letter-spacing: .08em;
            color: var(--accent-on-dark); text-transform: uppercase; }
  .logo   { grid-area: 1 / 6 / 2 / 7; justify-self: end; width: 120px; height: 32px; background: #fff; }
  h1      { grid-area: 3 / 1 / 4 / 6; font: 700 76px/80px Inter, Arial, sans-serif; letter-spacing: -.02em;
            text-wrap: balance; }
  .when   { grid-area: 5 / 1 / 6 / 3; font: 400 32px/40px Inter, Arial, sans-serif; }
  .when b { display: block; font-size: 57px; line-height: 64px; }
  .art    { grid-area: 5 / 3 / 6 / 7; margin-right: calc(-1 * var(--m));      /* bleed off the right edge */
            background: center / cover url("art.png"); }
  .who    { grid-area: 7 / 1 / 8 / 4; align-self: end; font: 400 24px/28px Inter, Arial, sans-serif; }
  .cta    { grid-area: 7 / 5 / 8 / 7; display: grid; place-items: center; border-radius: 8px;
            background: var(--accent-fill); font: 700 24px/1 Inter, Arial, sans-serif; }
</style></head>
<body><main class="post">
  <p class="kicker">Live webinar</p><div class="logo"></div>
  <h1>Ship safer releases with feature flags</h1>
  <p class="when"><b>12 Nov</b>17:00 CET<br>45 min, online</p>
  <div class="art" role="img" aria-label="Abstract network of glowing nodes"></div>
  <p class="who">Ana Ruiz &amp; Tom Lee<br>Platform team</p>
  <p class="cta">Register free</p>
</main></body></html>
```

Load brand fonts with `@font-face` from local files (licence permitting) so the render does not
fall back silently; check `document.fonts.check('700 76px Inter')` in the page if in doubt.

## 2. Render, overlay and measure with Playwright

```python
# shot.py: uv run --python 3.13 --with playwright python -I shot.py "$PWD/post.html"
import sys
from playwright.sync_api import sync_playwright

OVERLAY = """
body::after { content: ""; position: fixed; inset: 0 60px; pointer-events: none; z-index: 2147483647;
  background:
    repeating-linear-gradient(to right, rgb(255 0 64 / .18) 0 140px, transparent 140px 164px),
    repeating-linear-gradient(to bottom, rgb(0 170 255 / .3) 0 1px, transparent 1px 8px); }
"""
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")      # installed Chrome; or `playwright install chromium` and drop channel
    page = b.new_page(viewport={"width": 1080, "height": 1350}, device_scale_factor=1)
    page.goto("file://" + sys.argv[1])
    page.screenshot(path="post.png")
    page.add_style_tag(content=OVERLAY)
    page.screenshot(path="post-grid.png")
    boxes = page.evaluate("""() => [...document.querySelectorAll('.post > *')].map(e => {
        const r = e.getBoundingClientRect(); return [e.className || e.tagName, r.left, r.top, r.right, r.bottom]; })""")
    for bx in boxes:
        print(bx)
    b.close()
```

Output for the post above: `['kicker', 60, 60, 528, 92]`, `['H1', 60, 124, 856, 284]`,
`['art', 388, 348, 1080, 1170]`, `['cta', 716, 1234, 1020, 1290]`. Compare each x with the edges
from `gridcheck.py columns 1080 6 --gutter 24 --margin 60`. For 2x assets use
`device_scale_factor=2` and `--ppi 192` in `gridcheck.py overlay`. A transparent PNG of a
component: `page.screenshot(path=..., omit_background=True)` with a transparent body.

## 3. Typst A2 poster (6 x 8 modules, 14 pt baseline)

```typst
// A2 event poster: 6 x 8 modular grid on a 14 pt baseline. Every measure is derived.
#let bl = 14pt                                   // baseline increment = gutter
#let mg = 21mm                                   // outer margin: 5% of the 420 mm short side
#let (cols, rows, k) = (6, 8, 13)                // k = baselines per module
#let colw = (420mm - 2 * mg - (cols - 1) * bl) / cols    // 58.88 mm
#let modh = k * bl                               // 182 pt = 64.21 mm
#set page(paper: "a2", margin: (x: mg, top: mg,
  bottom: 594mm - mg - rows * modh - (rows - 1) * bl))    // 24.78 mm
// Line box = one pitch, baseline at its bottom: every baseline lands on the grid.
#set text(font: ("Inter", "Helvetica"), size: 10pt, top-edge: bl, bottom-edge: 0pt)
#set par(leading: 0pt, spacing: bl)
#let type(size, lines, ..args, body) = {
  set text(size: size, top-edge: lines * bl, ..args)
  body
}
// Module c (column), r (row), 1-based, spanning cs columns and rs rows.
#let at(c, r, cs: 1, rs: 1, body) = place(top + left,
  dx: (c - 1) * (colw + bl), dy: (r - 1) * (modh + bl),
  block(width: cs * colw + (cs - 1) * bl, height: rs * modh + (rs - 1) * bl, body))

#at(1, 1, cs: 6, rs: 2)[
  #type(20pt, 2, weight: "bold", fill: rgb("#D63151"))[DEVCONF 2026 · BERLIN]

  #type(84pt, 6, weight: "bold", tracking: -0.02em)[Build faster.\ Ship safer.]
]
#at(1, 3, cs: 6, rs: 4)[#image("hero.jpg", width: 100%, height: 100%, fit: "cover")]
#at(1, 7, cs: 3)[#type(20pt, 2)[*12-14 November*\ Arena Berlin, Hall 2\ Doors 09:00]]
#at(4, 7, cs: 3)[#type(20pt, 2)[40 talks, 12 workshops\ Keynote: Dr. A. Example]]
#at(1, 8, cs: 4)[#type(28pt, 3, weight: "bold")[Register free:\ ex.org/dc26]]
#at(6, 8)[#align(right + bottom, image("qr.svg", width: 33mm))]  // 25 mm symbol + 4-module quiet zone
```

Notes:
- Typst's default text box runs from cap height to baseline with `leading: 0.65em` between
  boxes (measured pitch 13.65 pt for 10 pt Helvetica), so a baseline grid needs the
  `top-edge`/`bottom-edge` settings above. A blank line between two `#type(...)` calls starts a
  new paragraph; without it they share a line.
- Missing fonts only warn (`unknown font family: inter`) and fall back: list a fallback, ship the
  font files with `--font-path fonts/`, and check the PDF's embedded fonts.
- Bleed: Typst pages have no bleed box. For a bleed version set the page to 426 x 600 mm, add
  3 mm to every margin, extend bleeding images by 3 mm, and let the print step add marks
  (sibling `print-prepress-pdfx`).

## 4. Print CSS for WeasyPrint or Paged.js

```css
@page { size: 420mm 594mm; margin: 21mm 21mm 24.78mm; bleed: 3mm; marks: crop cross; }
html { font: 10pt/14pt Inter, sans-serif; }               /* B = 14pt: every line-height a multiple */
.poster { display: grid; height: 548.22mm; gap: 14pt;
          grid-template-columns: repeat(6, 1fr); grid-template-rows: repeat(8, 1fr); }
.headline { grid-column: 1 / -1; grid-row: 1 / 3; font: 700 84pt/84pt Inter, sans-serif; }
.hero     { grid-column: 1 / -1; grid-row: 3 / 7; object-fit: cover; width: 100%; height: 100%; }
.bleed    { margin-inline: -24mm; }    /* 21 mm margin + 3 mm bleed: confirm the engine paints into the bleed */
```

Commands: `weasyprint poster.html poster.pdf` (WeasyPrint implements `size`, `bleed` and
`marks`; its CSS Grid support covers simple grids, not subgrid, so check the overlay;
`--pdf-variant pdf/x-4` is available, but validate PDF/X output) or `pagedjs-cli poster.html -o
poster.pdf` (headless Chromium). CSS has no baseline-grid control: line-heights keep the pitch,
but the first baseline's offset depends on font metrics, so measure it on the overlay and nudge
with `padding-top`. Typst controls the first baseline exactly.

## 5. Hand-off sheet for InDesign or Affinity

```text
Document     A2 portrait 420 x 594 mm, 1 page, bleed 3 mm all sides, slug 0
Margins      top 21, bottom 24.78, inside/left 21, outside/right 21 mm
Columns      6, gutter 4.939 mm (14 pt)
Rows         8, gutter 4.939 mm (InDesign: Layout > Create Guides, fit to margins; Affinity: Guides Manager)
Baseline     start 21 mm relative to top of page (= top margin), increment 14 pt
Styles       Kicker   Inter Bold 20/28, tracking +0, colour accent-fill, align to baseline grid
             Headline Inter Bold 84/84, tracking -20 (thousandths of an em), align to baseline grid
             Info     Inter Regular 20/28; Info-bold Inter Bold 20/28
             CTA      Inter Bold 28/42
Swatches     navy #1A1A2E; accent-fill #D63151 (CMYK or spot from the printer's conversion)
Fonts        Inter (OFL) .otf files supplied in /fonts
Links        hero.tif 5031 x 3208 px placed at 426 x 271.6 mm = 300 ppi (full-width bleed)
Export       PDF/X-4, output intent from the printer (sibling print-prepress-pdfx)
```

The hero frame spans rows 3-6: 4 x 64.21 + 3 x 4.94 = 271.6 mm tall; for a full-width bleed the
frame is 426 mm wide; pixels = mm / 25.4 x 300.

## 6. Fonts embedded and the render loop

```bash
pdffonts poster.pdf                          # poppler: the "emb" column must say yes for every font
STACK="$HOME/.claude/stack"; [ -d "$STACK" ] || STACK="${CLAUDE_PROJECT_DIR:-.}"; PY="$STACK/.venv/bin/python"
"$PY" -I -c "
import pikepdf, sys
pdf = pikepdf.open(sys.argv[1]); seen = {}
for page in pdf.pages:
    for name, f in page.obj.get('/Resources', {}).get('/Font', {}).items():
        d = f.get('/FontDescriptor') or (f['/DescendantFonts'][0].get('/FontDescriptor') if '/DescendantFonts' in f else None)
        seen[str(f.get('/BaseFont'))] = bool(d and any(k in d for k in ('/FontFile', '/FontFile2', '/FontFile3')))
print(seen); sys.exit(0 if all(seen.values()) else 1)" poster.pdf
```

The Typst poster reported `{'/OXTLAO+Helvetica-Bold': True, '/TDUMCJ+Helvetica': True}` (the
six-letter prefix marks a subset).

Render to PNG for review: `pdftoppm -r 100 -png poster.pdf out/poster` writes
`out/poster-1.png` (A2 at 100 ppi = 1654 x 2339 px; multi-page files number every page), or
`gs -q -dSAFER -dBATCH -dNOPAUSE -sDEVICE=png16m -r100 -o out/poster-%d.png poster.pdf`. Read the
PNG, then the `gridcheck.py overlay` and `squint` outputs, score the hub rubric, fix the top
three issues, rebuild. Keep each round's PNG (`poster-r1.png`, `poster-r2.png`) to show the
trend.
