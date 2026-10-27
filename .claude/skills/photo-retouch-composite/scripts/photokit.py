#!/usr/bin/env python3
"""Deterministic photo corrections for retouching and compositing (NumPy + Pillow).

The stack venv has Pillow but not NumPy; run it in an ephemeral uv environment (a shell function,
because zsh does not word-split a command stored in a variable):
    pk() { uv run -q --no-project --python 3.13 --with numpy --with pillow python -I "$PK" "$@"; }
    pk stats photo.png
Images are 8-bit sRGB (PNG/JPEG/TIFF; EXIF orientation applied); masks are PNGs, white = region.
Every command that writes prints the output path; measurements print JSON.

Measure
  stats IMG [--mask M]                     per channel p0.5/p50/p99.5/mean/std (0..255), linear Y mean,
                                           OKLab mean/std (an RGBA image defaults to its opaque pixels)
  hist OUT IMG[:MASK]...                   stacked RGB histograms, one panel per image (before/after)
  grain-measure IMG [--mask M] [--sigma 1.5] [--block 32] [--flat 0.1]
                                           high-pass std of luma in the flattest blocks (0..255)
  swatch IMG --mask M --ref '#RRGGBB'      mean colour of a region vs a reference: dE_OK, dE76
  whitebg IMG [--fill 0.85] [--margin 6]   exact (255,255,255) border and background outside the
                                           product box, product fill ratio; exit 1 on failure
Global corrections (alpha, if any, passes through unchanged)
  levels IN OUT [--lo 0.5] [--hi 99.5] [--per-channel] [--mask M]
  wb IN OUT (--neutral X,Y[,R] | --grayworld) [--mask M]
  curve IN OUT [--gamma G] [--points 0,0 64,58 192,198 255,255]   monotone cubic LUT
  sharpen IN OUT [--radius 0.8] [--percent 80] [--threshold 2]   unsharp mask on luma only
  persp IN OUT --src X,Y X,Y X,Y X,Y --dst X,Y X,Y X,Y X,Y [--fill #ffffff]
                                           perspective warp mapping 4 source points (TL TR BR BL)
                                           onto 4 destination points (keystone, tilted labels)
Local corrections
  ramp OUT --like IMG --from X0,Y0 --to X1,Y1   linear gradient mask (0 at FROM, 255 at TO)
  dodge IN OUT --ev E [--mask M] [--feather PX] exposure change in linear light, weighted by the
                                           mask (no mask = global); negative E burns
Compositing
  transfer SRC REF OUT [--src-mask M] [--ref-mask M] [--apply-mask M] [--space oklab|lab]
                       [--channels L,a,b] [--strength 0.6] [--std-clamp 0.67,1.5]
                                           Reinhard mean/std match: statistics from the two masked
                                           regions (SRC default: its alpha), applied to all of SRC
                                           (or --apply-mask); --std-clamp 1,1 = mean shift only
  grain-add IN OUT --target T [--current C] [--mask M] [--size 0.0] [--chroma 0.0] [--seed 1]
  shadow CUT BG OUT --x X --y Y [--scale S] [--kind contact|cast] [--opacity O] [--squash Q]
                    [--below 0.25] [--blur B] [--angle DEG] [--length L] [--blur-far B2] [--color #RRGGBB]
                                           multiplies BG in linear light; opacity = share of light
                                           blocked; blur values are % of the subject width
  reflect CUT BG OUT --x X --y Y [--scale S] [--opacity 0.3] [--fade 0.35] [--blur 1.0]
  decontam CUT OUT [--radius 3]            recolour semi-transparent edge pixels from the opaque
                                           interior (removes background spill, keeps hair alpha)
x, y, scale place CUT exactly as `masktool.py over` does (LANCZOS resize, top-left at x, y).
Exit codes: 0 ok, 1 check failed (whitebg), 2 usage or I/O error.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

# --- I/O ------------------------------------------------------------------------------------

def die(msg):
    sys.stderr.write("error: %s\n" % msg)
    sys.exit(2)

def load(p):
    try:
        im = ImageOps.exif_transpose(Image.open(p))
    except OSError as e:
        die("cannot read %s: %s" % (p, e))
    alpha = np.asarray(im.getchannel("A"), np.float32) / 255 if "A" in im.getbands() else None
    return np.asarray(im.convert("RGB"), np.float32) / 255, alpha

def save(p, rgb, alpha=None):
    im = Image.fromarray(np.clip(np.rint(rgb * 255), 0, 255).astype(np.uint8))
    if alpha is not None:
        im.putalpha(Image.fromarray(np.clip(np.rint(alpha * 255), 0, 255).astype(np.uint8)))
    im.save(p)
    print(p)

def mask(p, shape, default=None):
    if not p:
        return np.ones(shape[:2], bool) if default is None else default
    try:
        m = Image.open(p).convert("L")
    except OSError as e:
        die("cannot read mask %s: %s" % (p, e))
    if m.size != (shape[1], shape[0]):
        die("mask %s is %sx%s, image is %sx%s" % (p, m.size[0], m.size[1], shape[1], shape[0]))
    return np.asarray(m) >= 128

# --- colour spaces --------------------------------------------------------------------------

def to_lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)

OK_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566],
                  [0.0883024619, 0.2817188376, 0.6299787005]])
OK_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099],
                  [0.0259040371, 0.7827717662, -0.8086757660]])
OK_I2 = np.array([[1.0, 0.3963377774, 0.2158037573], [1.0, -0.1055613458, -0.0638541728],
                  [1.0, -0.0894841775, -1.2914855480]])
OK_I1 = np.array([[4.0767416621, -3.3077115913, 0.2309699292], [-1.2684380046, 2.6097574011, -0.3413193965],
                  [-0.0041960863, -0.7034186147, 1.7076147010]])
XYZ_M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
D65 = np.array([0.95047, 1.0, 1.08883])

def to_space(rgb, space):
    lin = to_lin(rgb)
    if space == "oklab":
        return np.cbrt(lin @ OK_M1.T) @ OK_M2.T
    t = (lin @ XYZ_M.T) / D65
    f = np.where(t > (6 / 29) ** 3, np.cbrt(t), t / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)

def from_space(lab, space):
    if space == "oklab":
        return to_srgb(((lab @ OK_I2.T) ** 3) @ OK_I1.T)
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    t = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29))
    return to_srgb((t * D65) @ np.linalg.inv(XYZ_M).T)

def luma(rgb):
    return rgb @ np.array([0.299, 0.587, 0.114])

# --- filters --------------------------------------------------------------------------------

def gblur(a, sigma):
    """Separable Gaussian blur of a 2-D float array (reflect padding)."""
    if sigma <= 0:
        return a
    r = max(1, int(math.ceil(3 * sigma)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k /= k.sum()
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(a, pad, mode="reflect")
        n = a.shape[axis]
        a = sum(w * (p[i:i + n] if axis == 0 else p[:, i:i + n]) for i, w in enumerate(k))
    return a

def place_alpha(cut_path, size, x, y, scale):
    """Alpha of CUT placed on a canvas of `size` exactly like masktool over."""
    fg = Image.open(cut_path).convert("RGBA")
    if scale != 1.0:
        fg = fg.resize((max(1, round(fg.width * scale)), max(1, round(fg.height * scale))), Image.LANCZOS)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.paste(fg, (x, y), fg)
    return layer

# --- commands -------------------------------------------------------------------------------

def c_stats(a):
    rgb, al = load(a.img)
    m = mask(a.mask, rgb.shape, None if al is None else al >= 0.5)
    px = rgb[m] * 255
    lab = to_space(rgb[m], "oklab")
    out = {"file": a.img, "pixels": int(m.sum()), "clipped_hi": round(float((px >= 254).all(1).mean()), 5),
           "clipped_lo": round(float((px <= 1).all(1).mean()), 5)}
    for i, ch in enumerate("RGB"):
        p = np.percentile(px[:, i], [0.5, 50, 99.5])
        out[ch] = {"p0.5": round(float(p[0]), 1), "p50": round(float(p[1]), 1), "p99.5": round(float(p[2]), 1),
                   "mean": round(float(px[:, i].mean()), 2), "std": round(float(px[:, i].std()), 2)}
    out["Y_linear_mean"] = round(float((to_lin(rgb[m]) @ np.array([0.2126, 0.7152, 0.0722])).mean()), 5)
    out["oklab_mean"] = [round(float(v), 4) for v in lab.mean(0)]
    out["oklab_std"] = [round(float(v), 4) for v in lab.std(0)]
    print(json.dumps(out, indent=1))

def c_hist(a):
    panels = []
    for spec in a.imgs:
        path, _, mpath = spec.partition(":")
        rgb, al = load(path)
        m = mask(mpath or None, rgb.shape, None if al is None else al >= 0.5)
        px = np.rint(rgb[m] * 255).astype(int)
        p = Image.new("RGB", (512, 150), "white")
        d = ImageDraw.Draw(p)
        hs = [np.bincount(px[:, i], minlength=256) for i in range(3)]
        top = max(h[1:-1].max() for h in hs) or 1
        for h, col in zip(hs, ("#d62728", "#2ca02c", "#1f77b4")):
            d.line([(2 * i, 140 - 120 * min(1.0, h[i] / top)) for i in range(256)], fill=col, width=1)
        d.text((4, 2), spec[-60:], fill="black")
        panels.append(p)
    sheet = Image.new("RGB", (512, 150 * len(panels)), "white")
    for i, p in enumerate(panels):
        sheet.paste(p, (0, 150 * i))
    sheet.save(a.out)
    print(a.out)

def c_levels(a):
    rgb, al = load(a.inp)
    m = mask(a.mask, rgb.shape, None if al is None else al >= 0.5)
    if a.per_channel:
        lo = np.percentile(rgb[m], a.lo, axis=0)
        hi = np.percentile(rgb[m], a.hi, axis=0)
    else:
        y = luma(rgb)[m]
        lo, hi = np.percentile(y, a.lo), np.percentile(y, a.hi)
    out = (rgb - lo) / np.maximum(hi - lo, 1e-3)
    sys.stderr.write("levels black %s white %s (0..255)\n" % (np.round(np.atleast_1d(lo) * 255, 1), np.round(np.atleast_1d(hi) * 255, 1)))
    save(a.out, out, al)

def c_wb(a):
    rgb, al = load(a.inp)
    lin = to_lin(rgb)
    if a.neutral:
        v = [int(t) for t in a.neutral.split(",")]
        x, y, r = v[0], v[1], (v[2] if len(v) > 2 else 8)
        patch = lin[max(0, y - r):y + r + 1, max(0, x - r):x + r + 1].reshape(-1, 3)
    else:
        m = mask(a.mask, rgb.shape, None if al is None else al >= 0.5)
        m = m & (rgb.max(-1) < 0.98) & (rgb.min(-1) > 0.02)  # skip clipped pixels
        patch = lin[m]
    means = patch.mean(0)
    gains = means.mean() / np.maximum(means, 1e-6)
    sys.stderr.write("wb gains R %.4f G %.4f B %.4f (linear light)\n" % tuple(gains))
    save(a.out, to_srgb(lin * gains), al)

def pchip_lut(xs, ys):
    """Monotone cubic (Fritsch-Carlson) through control points, sampled at 0..255."""
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    h, dlt = np.diff(xs), np.diff(ys) / np.diff(xs)
    m = np.zeros_like(xs)
    m[0], m[-1] = dlt[0], dlt[-1]
    for i in range(1, len(xs) - 1):
        if dlt[i - 1] * dlt[i] > 0:
            w1, w2 = 2 * h[i] + h[i - 1], h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / dlt[i - 1] + w2 / dlt[i])
    t = np.arange(256, dtype=float)
    k = np.clip(np.searchsorted(xs, t, side="right") - 1, 0, len(xs) - 2)
    s = (t - xs[k]) / h[k]
    h00, h10, h01, h11 = 2 * s**3 - 3 * s**2 + 1, s**3 - 2 * s**2 + s, -2 * s**3 + 3 * s**2, s**3 - s**2
    return np.clip(h00 * ys[k] + h10 * h[k] * m[k] + h01 * ys[k + 1] + h11 * h[k] * m[k + 1], 0, 255)

def c_curve(a):
    rgb, al = load(a.inp)
    if a.points:
        pts = sorted(tuple(float(v) for v in p.split(",")) for p in a.points)
        lut = pchip_lut([p[0] for p in pts], [p[1] for p in pts])
    else:
        lut = 255 * (np.arange(256) / 255) ** (1 / a.gamma)
    idx = np.clip(np.rint(rgb * 255), 0, 255).astype(int)
    save(a.out, lut[idx] / 255, al)

def c_sharpen(a):
    """Unsharp mask on luma in float (no 8-bit YCbCr round trip); the luma delta is added to R, G
    and B alike, so hue and saturation stay put. radius = Gaussian sigma in px, percent = amount,
    threshold = smallest detail (0..255 levels) that gets sharpened, as in Pillow's UnsharpMask."""
    rgb, al = load(a.inp)
    y = luma(rgb)
    detail = y - gblur(y, a.radius)
    detail = np.where(np.abs(detail) * 255 >= a.threshold, detail, 0.0)
    save(a.out, rgb + (a.percent / 100.0) * detail[..., None], al)

def c_ramp(a):
    w, h = Image.open(a.like).size
    (x0, y0), (x1, y1) = [[float(v) for v in t.split(",")] for t in (a.frm, a.to)]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = x1 - x0, y1 - y0
    t = np.clip(((xx - x0) * dx + (yy - y0) * dy) / max(dx * dx + dy * dy, 1e-6), 0, 1)
    Image.fromarray(np.uint8(np.rint(t * 255))).save(a.out)
    print(a.out)

def c_dodge(a):
    rgb, al = load(a.inp)
    if a.mask:
        m = np.asarray(Image.open(a.mask).convert("L"), np.float32) / 255
        if m.shape != rgb.shape[:2]:
            die("mask size differs from the image")
        m = gblur(m, a.feather) if a.feather > 0 else m
    else:
        m = np.ones(rgb.shape[:2], np.float32)
    save(a.out, to_srgb(to_lin(rgb) * np.power(2.0, a.ev * m)[..., None]), al)

def c_transfer(a):
    src, al = load(a.src)
    ref, _ = load(a.ref)
    sm = mask(a.src_mask, src.shape, None if al is None else al >= 0.5)
    rm = mask(a.ref_mask, ref.shape)
    S, R = to_space(src, a.space), to_space(ref, a.space)
    ms, ss = S[sm].mean(0), S[sm].std(0)
    mr, sr = R[rm].mean(0), R[rm].std(0)
    lo, hi = (float(v) for v in a.std_clamp.split(","))
    ratio = np.clip(sr / np.maximum(ss, 1e-6), lo, hi)
    use = np.array([c in a.channels.split(",") for c in ("L", "a", "b")])
    target = (S - ms) * ratio + mr
    out = np.where(use, S + a.strength * (target - S), S)
    am = mask(a.apply_mask, src.shape) if a.apply_mask else np.ones(src.shape[:2], bool)
    rgb = np.where(am[..., None], from_space(out, a.space), src)
    sys.stderr.write(json.dumps({"space": a.space, "src_mean": np.round(ms, 4).tolist(), "ref_mean": np.round(mr, 4).tolist(),
                                 "std_ratio": np.round(ratio, 3).tolist(), "strength": a.strength}) + "\n")
    save(a.out, rgb, al)

def hp_noise_gain(sigma, size, seed=7):
    n = np.random.default_rng(seed).standard_normal((256, 256))
    if size > 0:
        n = gblur(n, size)
        n /= n.std()
    return float((n - gblur(n, sigma))[16:-16, 16:-16].std())

def c_grain_measure(a):
    rgb, al = load(a.img)
    y = luma(rgb) * 255
    hp = y - gblur(y, a.sigma)
    lowg = np.hypot(*np.gradient(gblur(y, 2 * a.sigma)))
    m = mask(a.mask, rgb.shape, None if al is None else al >= 0.99)
    b, rows = a.block, []
    for r0 in range(0, y.shape[0] - b + 1, b):
        for c0 in range(0, y.shape[1] - b + 1, b):
            if m[r0:r0 + b, c0:c0 + b].mean() < 0.95:
                continue
            mu = y[r0:r0 + b, c0:c0 + b].mean()
            if 12 < mu < 243:  # clipped blocks hide noise
                rows.append((lowg[r0:r0 + b, c0:c0 + b].mean(), hp[r0:r0 + b, c0:c0 + b].std(), mu))
    if not rows:
        die("no usable flat blocks: lower --block or widen the mask")
    rows.sort()
    flat = rows[:max(3, int(len(rows) * a.flat))]
    print(json.dumps({"file": a.img, "hp_sigma": a.sigma, "blocks": len(rows), "flat_blocks": len(flat),
                      "grain_hp_std": round(float(np.median([r[1] for r in flat])), 3),
                      "flat_luma_mean": round(float(np.median([r[2] for r in flat])), 1),
                      "white_noise_hp_gain": round(hp_noise_gain(a.sigma, 0), 4)}, indent=1))

def c_grain_add(a):
    rgb, al = load(a.inp)
    h, w = rgb.shape[:2]
    rng = np.random.default_rng(a.seed)
    def field():
        n = rng.standard_normal((h, w))
        if a.size > 0:
            n = gblur(n, a.size)
            n /= n.std()
        return n
    mono = field()
    noise = np.sqrt(1 - a.chroma**2) * mono[..., None] + a.chroma * np.stack([field() for _ in range(3)], -1)
    luma_share = math.sqrt(1 - a.chroma**2 + a.chroma**2 * float(np.sum(np.array([0.299, 0.587, 0.114]) ** 2)))
    need = math.sqrt(max(a.target**2 - a.current**2, 0.0)) / (hp_noise_gain(a.sigma, a.size) * luma_share)
    m = mask(a.mask, rgb.shape).astype(np.float32)
    if a.mask:
        m = np.clip(gblur(m, 1.0), 0, 1)
    y = luma(rgb)
    taper = np.clip(np.minimum(y, 1 - y) / 0.03, 0, 1)  # keep pure black and pure white exact
    sys.stderr.write("adding grain std %.3f (0..255) for hp target %.3f from %.3f\n" % (need, a.target, a.current))
    save(a.out, rgb + noise * (need / 255) * (m * taper)[..., None], al)

def c_shadow(a):
    bg, _ = load(a.bg)
    H, W = bg.shape[:2]
    A = np.asarray(place_alpha(a.cut, (W, H), a.x, a.y, a.scale).getchannel("A"), np.float32) / 255
    ys, xs = np.nonzero(A > 0.5)
    if not len(ys):
        die("cutout has no opaque pixels at that placement")
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    ow, oh = x1 - x0 + 1, y1 - y0 + 1
    if a.kind == "contact":
        crop = Image.fromarray(np.uint8(A[y0:y1 + 1, x0:x1 + 1] * 255))
        sh = max(2, round(oh * a.squash))
        flat = np.asarray(crop.resize((ow, sh), Image.LANCZOS), np.float32) / 255
        S = np.zeros((H, W), np.float32)
        top = y1 - round(sh * (1 - a.below))  # most of the footprint hides behind the base
        r0, r1 = max(0, top), min(H, top + sh)
        S[r0:r1, x0:x1 + 1] = flat[r0 - top:r1 - top]
        S = gblur(S, a.blur * ow / 100)
        op = a.opacity
    else:
        ang = math.radians(a.angle)
        if abs(math.sin(ang)) < 0.1:
            die("--angle must point into the ground plane (|sin| >= 0.1): try -25 or 25")
        k = a.length * math.sin(ang)
        cot = math.cos(ang) / math.sin(ang)
        aim = Image.fromarray(np.uint8(A * 255))
        proj = aim.transform((W, H), Image.Transform.AFFINE,
                             (1, -cot, cot * y1, 0, -1 / k, y1 + y1 / k), resample=Image.BILINEAR)
        P = np.asarray(proj, np.float32) / 255
        dist = np.clip(np.abs(np.arange(H) - y1)[:, None] / max(1.0, abs(k) * oh), 0, 1)
        near, far = gblur(P, a.blur * ow / 100), gblur(P, a.blur_far * ow / 100)
        S = near * (1 - dist) + far * dist
        op = a.opacity * (1 - 0.7 * dist)
    tint = np.array([int(a.color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    out = to_srgb(to_lin(bg) * (1 - (op * S)[..., None] * (1 - tint)))  # light blocked, in linear light
    sys.stderr.write("subject bbox x %d-%d y %d-%d; shadow %s peak %.2f\n" % (x0, x1, y0, y1, a.kind, float((op * S).max())))
    save(a.out, out)

def c_reflect(a):
    bg, _ = load(a.bg)
    H, W = bg.shape[:2]
    layer = place_alpha(a.cut, (W, H), a.x, a.y, a.scale)
    arr = np.asarray(layer, np.float32) / 255
    ys, _ = np.nonzero(arr[..., 3] > 0.5)
    if not len(ys):
        die("cutout has no opaque pixels at that placement")
    y0, y1 = ys.min(), ys.max()
    oh = y1 - y0 + 1
    src = arr[y0:y1 + 1][::-1]
    n = min(oh, H - (y1 + 1))
    refl = np.zeros_like(arr)
    refl[y1 + 1:y1 + 1 + n] = src[:n]
    fade = np.clip(1 - (np.arange(H) - y1) / (a.fade * oh), 0, 1)[:, None]
    ra = refl[..., 3] * a.opacity * fade
    if a.blur > 0:
        ra = gblur(ra, a.blur)
        rgb = np.stack([gblur(refl[..., i] * refl[..., 3], a.blur) for i in range(3)], -1) / np.maximum(gblur(refl[..., 3], a.blur), 1e-4)[..., None]
    else:
        rgb = refl[..., :3]
    save(a.out, bg * (1 - ra[..., None]) + np.clip(rgb, 0, 1) * ra[..., None])

def c_decontam(a):
    """Estimate the foreground colour of semi-transparent edge pixels from nearby opaque pixels
    (normalised convolution at growing radii, so long strands far from the body are reached too)."""
    rgb, al = load(a.cut)
    if al is None:
        die("decontam needs an RGBA cutout")
    core = (al >= 0.99).astype(np.float32)
    edge = (al > 0) & (al < 0.99)
    todo, out = edge.copy(), rgb.copy()
    for r in (a.radius, a.radius * 3, a.radius * 9, a.radius * 27):
        w = gblur(core, r)
        ok = todo & (w > 1e-3)
        if ok.any():
            fill = np.stack([gblur(rgb[..., i] * core, r) for i in range(3)], -1) / np.maximum(w, 1e-6)[..., None]
            out[ok] = fill[ok]
            todo &= ~ok
    sys.stderr.write("recoloured %d edge pixels, %d left unchanged\n" % (int(edge.sum() - todo.sum()), int(todo.sum())))
    save(a.out, out, al)

def c_swatch(a):
    rgb, al = load(a.img)
    m = mask(a.mask, rgb.shape)
    mean = rgb[m].mean(0)
    ref = np.array([int(a.ref.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)])
    ok, okr = to_space(mean, "oklab"), to_space(ref, "oklab")
    lab, labr = to_space(mean, "lab"), to_space(ref, "lab")
    print(json.dumps({"mean_hex": "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in mean), "ref": a.ref,
                      "oklab": np.round(ok, 4).tolist(), "ref_oklab": np.round(okr, 4).tolist(),
                      "dE_OK": round(float(np.linalg.norm(ok - okr)), 4),
                      "dE76": round(float(np.linalg.norm(lab - labr)), 2)}, indent=1))

def c_persp(a):
    im = ImageOps.exif_transpose(Image.open(a.inp))
    src = [[float(v) for v in t.split(",")] for t in a.src]
    dst = [[float(v) for v in t.split(",")] for t in a.dst]
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):  # Pillow maps each output pixel back to an input pixel
        rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        rhs += [u, v]
    coeffs = np.linalg.solve(np.array(rows), np.array(rhs))
    rgba = "A" in im.getbands()  # cutouts keep transparent corners
    fill = (0, 0, 0, 0) if rgba else tuple(int(a.fill.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    im.convert("RGBA" if rgba else "RGB").transform(
        im.size, Image.Transform.PERSPECTIVE, tuple(coeffs), Image.BICUBIC, fillcolor=fill).save(a.out)
    print(a.out)

def c_whitebg(a):
    rgb, _ = load(a.img)
    px = np.rint(rgb * 255).astype(np.uint8)
    H, W = px.shape[:2]
    white = (px == 255).all(-1)
    border = np.concatenate([white[0], white[-1], white[:, 0], white[:, -1]])
    ys, xs = np.nonzero((px < 250).any(-1))  # product core: clearly not background
    res = {"file": a.img, "size": [W, H], "border_exact_white": round(float(border.mean()), 5)}
    fails = []
    if res["border_exact_white"] < 1.0:
        fails.append("border pixels not exactly (255,255,255)")
    if len(ys):
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        res.update(product_bbox=[int(x0), int(y0), int(x1), int(y1)],
                   fill_long_side=round(max((x1 - x0 + 1) / W, (y1 - y0 + 1) / H), 4),
                   fill_area=round((x1 - x0 + 1) * (y1 - y0 + 1) / (W * H), 4))
        out = np.ones((H, W), bool)
        out[max(0, y0 - a.margin):y1 + a.margin + 1, max(0, x0 - a.margin):x1 + a.margin + 1] = False
        res["off_white_outside_product"] = int((out & ~white).sum())
        if res["off_white_outside_product"]:
            fails.append("%d pixels outside the product box are not pure white" % res["off_white_outside_product"])
        if res["fill_long_side"] < a.fill:
            fails.append("product spans %.1f%% of the frame (< %.0f%%)" % (100 * res["fill_long_side"], 100 * a.fill))
    else:
        fails.append("no product found (nothing darker than 250)")
    res["fails"] = fails
    print(json.dumps(res, indent=1))
    return 1 if fails else 0

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("stats"); x.add_argument("img"); x.add_argument("--mask"); x.set_defaults(fn=c_stats)
    x = s.add_parser("hist"); x.add_argument("out"); x.add_argument("imgs", nargs="+"); x.set_defaults(fn=c_hist)
    x = s.add_parser("levels"); x.add_argument("inp"); x.add_argument("out"); x.add_argument("--mask")
    x.add_argument("--lo", type=float, default=0.5); x.add_argument("--hi", type=float, default=99.5)
    x.add_argument("--per-channel", action="store_true"); x.set_defaults(fn=c_levels)
    x = s.add_parser("wb"); x.add_argument("inp"); x.add_argument("out"); g = x.add_mutually_exclusive_group(required=True)
    g.add_argument("--neutral"); g.add_argument("--grayworld", action="store_true"); x.add_argument("--mask"); x.set_defaults(fn=c_wb)
    x = s.add_parser("curve"); x.add_argument("inp"); x.add_argument("out"); x.add_argument("--gamma", type=float, default=1.0)
    x.add_argument("--points", nargs="+"); x.set_defaults(fn=c_curve)
    x = s.add_parser("sharpen"); x.add_argument("inp"); x.add_argument("out"); x.add_argument("--radius", type=float, default=0.8)
    x.add_argument("--percent", type=int, default=80); x.add_argument("--threshold", type=int, default=2); x.set_defaults(fn=c_sharpen)
    x = s.add_parser("ramp"); x.add_argument("out"); x.add_argument("--like", required=True)
    x.add_argument("--from", dest="frm", required=True); x.add_argument("--to", required=True); x.set_defaults(fn=c_ramp)
    x = s.add_parser("dodge"); x.add_argument("inp"); x.add_argument("out"); x.add_argument("--ev", type=float, required=True)
    x.add_argument("--mask"); x.add_argument("--feather", type=float, default=0.0); x.set_defaults(fn=c_dodge)
    x = s.add_parser("transfer"); x.add_argument("src"); x.add_argument("ref"); x.add_argument("out")
    x.add_argument("--src-mask"); x.add_argument("--ref-mask"); x.add_argument("--apply-mask")
    x.add_argument("--space", choices=["oklab", "lab"], default="oklab")
    x.add_argument("--channels", default="L,a,b"); x.add_argument("--strength", type=float, default=0.6)
    x.add_argument("--std-clamp", default="0.67,1.5"); x.set_defaults(fn=c_transfer)
    x = s.add_parser("grain-measure"); x.add_argument("img"); x.add_argument("--mask"); x.add_argument("--sigma", type=float, default=1.5)
    x.add_argument("--block", type=int, default=32); x.add_argument("--flat", type=float, default=0.1); x.set_defaults(fn=c_grain_measure)
    x = s.add_parser("grain-add"); x.add_argument("inp"); x.add_argument("out"); x.add_argument("--target", type=float, required=True)
    x.add_argument("--current", type=float, default=0.0); x.add_argument("--mask"); x.add_argument("--sigma", type=float, default=1.5)
    x.add_argument("--size", type=float, default=0.0); x.add_argument("--chroma", type=float, default=0.0)
    x.add_argument("--seed", type=int, default=1); x.set_defaults(fn=c_grain_add)
    x = s.add_parser("shadow"); x.add_argument("cut"); x.add_argument("bg"); x.add_argument("out")
    x.add_argument("--x", type=int, required=True); x.add_argument("--y", type=int, required=True)
    x.add_argument("--scale", type=float, default=1.0); x.add_argument("--kind", choices=["contact", "cast"], default="contact")
    x.add_argument("--opacity", type=float, default=0.5); x.add_argument("--squash", type=float, default=0.08)
    x.add_argument("--below", type=float, default=0.25, help="share of the contact footprint below the base row")
    x.add_argument("--blur", type=float, default=2.0, help="percent of subject width (near blur for cast)")
    x.add_argument("--angle", type=float, default=-30.0); x.add_argument("--length", type=float, default=0.6)
    x.add_argument("--blur-far", type=float, default=6.0); x.add_argument("--color", default="#000000"); x.set_defaults(fn=c_shadow)
    x = s.add_parser("reflect"); x.add_argument("cut"); x.add_argument("bg"); x.add_argument("out")
    x.add_argument("--x", type=int, required=True); x.add_argument("--y", type=int, required=True)
    x.add_argument("--scale", type=float, default=1.0); x.add_argument("--opacity", type=float, default=0.3)
    x.add_argument("--fade", type=float, default=0.35); x.add_argument("--blur", type=float, default=1.0); x.set_defaults(fn=c_reflect)
    x = s.add_parser("decontam"); x.add_argument("cut"); x.add_argument("out")
    x.add_argument("--radius", type=float, default=3.0); x.set_defaults(fn=c_decontam)
    x = s.add_parser("swatch"); x.add_argument("img"); x.add_argument("--mask", required=True)
    x.add_argument("--ref", required=True); x.set_defaults(fn=c_swatch)
    x = s.add_parser("persp"); x.add_argument("inp"); x.add_argument("out")
    x.add_argument("--src", nargs=4, required=True); x.add_argument("--dst", nargs=4, required=True)
    x.add_argument("--fill", default="#ffffff", help="colour for areas outside the source"); x.set_defaults(fn=c_persp)
    x = s.add_parser("whitebg"); x.add_argument("img"); x.add_argument("--fill", type=float, default=0.85)
    x.add_argument("--margin", type=int, default=6, help="px around the product box excluded from the stray scan")
    x.set_defaults(fn=c_whitebg)
    a = p.parse_args(argv)
    return a.fn(a) or 0

if __name__ == "__main__":
    sys.exit(main())
