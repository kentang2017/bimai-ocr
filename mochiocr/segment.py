# -*- coding: utf-8 -*-
"""Column/strip segmentation for vertical handwritten script pages.

Approach proven in the mochi data pipeline:
  background normalisation -> ink mask -> x-profile -> global-valley column cuts
  -> ink-extent trimming -> subdivide oversized bands -> y-tighten
  -> reading order right-to-left. Tall columns tile into OCR-sized chunks.
"""
from __future__ import annotations

import numpy as np
import cv2
from PIL import Image
from dataclasses import dataclass, field


@dataclass
class Segment:
    x0: int
    y0: int
    x1: int
    y1: int
    kind: str = "column"   # column / tile
    tile_i: int = 0
    parts: int = 1


@dataclass
class PageSegments:
    width: int
    height: int
    strips: list[Segment] = field(default_factory=list)   # reading order: right -> left


def preprocess_gray(page_img) -> np.ndarray:
    g = cv2.cvtColor(np.asarray(page_img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    h, w = g.shape
    small = cv2.resize(g, (max(1, w // 4), max(1, h // 4)), interpolation=cv2.INTER_AREA)
    bg = cv2.resize(cv2.medianBlur(small, 51), (w, h), interpolation=cv2.INTER_LINEAR)
    norm = np.clip(g.astype(np.float32) / np.maximum(bg, 1.0) * 200.0, 0, 255).astype(np.uint8)
    return norm


def detect_columns(page_img, *,
                   ink_hi: int = 115,
                   band_min_w: int = 22,
                   width_keep: float = 0.32,
                   valley_frac: float = 0.32,
                   subdivide: bool = True,
                   max_tile: int = 2750,
                   keep_full_until: int = 5500,
                   verbose: bool = False) -> PageSegments:
    im = page_img.convert("RGB")
    g = preprocess_gray(im)
    ink = (g <= ink_hi).astype(np.float32)
    h, w = ink.shape
    prof = ink[int(h * 0.04):int(h * 0.96)].sum(axis=0)
    k = max(9, int(0.012 * w) | 1)
    ps = np.convolve(prof, np.ones(k) / k, mode="same")
    mx = float(ps.max())
    if mx < 3.0:
        return PageSegments(w, h, [])

    def global_valleys(frac):
        thr = frac * mx
        mins = []
        for i in range(1, w - 1):
            if ps[i] <= ps[i - 1] and ps[i] <= ps[i + 1] and ps[i] < thr:
                mins.append(i)
        if not mins:
            return []
        mins.sort()
        d = []
        last = None
        for i in mins:                      # keep the deepest min per gap region
            if last is None or i - last > 14:
                d.append([i, i])
                last = i
            else:
                if ps[i] < ps[d[-1][0]]:
                    d[-1][0] = i
                d[-1][1] = i
                last = i
        return [p for p, q in d]

    fracs = [valley_frac, max(0.2, valley_frac - 0.1), min(0.5, valley_frac + 0.14)]
    cuts = []
    for fr in fracs:
        cuts = global_valleys(fr)
        if len(cuts) >= 2:
            break
    marks = [0] + cuts + [w]
    merged: list[tuple[int, int]] = []
    for lo, hi in zip(marks, marks[1:]):
        seg = ps[lo:hi]
        idx = np.where(seg > 0.16 * mx)[0]
        if idx.size == 0:
            continue
        a0 = min(max(lo + int(idx[0]) - 6, lo), w)
        b1 = max(min(lo + int(idx[-1]) + 7, hi), a0)
        if b1 - a0 < band_min_w:
            continue
        if merged and a0 <= merged[-1][1] + 4:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b1))
        else:
            merged.append((a0, b1))
    widths = [b - a for a, b in merged]
    med = float(np.median(widths)) if widths else 0
    if subdivide and med > 0 and len(merged) >= 2:
        subdiv = []
        for a, b in merged:
            bwid = b - a
            if bwid > 1.25 * med:
                n = max(2, min(4, round(bwid / med)))
                step = bwid / n
                for kk in range(n):
                    if kk == 0:
                        subdiv.append((a, int(a + step)))
                    elif kk == n - 1:
                        subdiv.append((int(a + kk * step) + 8, b))
                    else:
                        subdiv.append((int(a + kk * step) + 4, int(a + (kk + 1) * step) + 4))
            else:
                subdiv.append((a, b))
        merged = subdiv
    merged = [(a, b) for a, b in merged if (b - a) >= width_keep * med]
    merged.sort(key=lambda t: -t[0])   # right -> left

    out: list[Segment] = []
    for xa, xb in merged:
        sub = ink[:, xa:xb]
        rows = sub.mean(axis=1)
        yy = np.where(rows > max(0.02, float(rows.max()) * 0.08))[0]
        if yy.size == 0:
            continue
        y0 = max(0, int(yy[0]) - 8)
        y1 = min(h, int(yy[-1]) + 9)
        col_h = y1 - y0
        if col_h <= keep_full_until:
            parts = [(y0, y1)]
        else:
            n = (col_h + max_tile - 1) // max_tile
            step = col_h / n
            parts = [(int(y0 + i * step), int(y0 + (i + 1) * step)) for i in range(n)]
        for ti, (ay, by) in enumerate(parts):
            out.append(Segment(x0=xa, y0=ay, x1=xb, y1=by, kind="tile", tile_i=ti, parts=len(parts)))
    if verbose:
        print(f"  [seg] {w}x{h}: {len(out)} strips (bands={len(merged)}, cuts={len(cuts)})")
    return PageSegments(w, h, out)


def crop_strip(page_img, seg: Segment, pad: int = 6, side: int = 3100) -> Image.Image:
    im = page_img.convert("RGB")
    x0 = max(0, seg.x0 - pad)
    x1 = min(im.width, seg.x1 + pad)
    y0 = max(0, seg.y0 - pad)
    y1 = min(im.height, seg.y1 + pad)
    crop = im.crop((x0, y0, x1, y1))
    ls, ss = max(crop.size), min(crop.size)
    if ls < 1100:
        up = 2.0 if ss < 300 else 1.6
        crop = crop.resize((int(crop.width * up), int(crop.height * up)), Image.LANCZOS)
    elif ls > side:
        dn = side / ls
        crop = crop.resize((max(1, int(crop.width * dn)), max(1, int(crop.height * dn))), Image.LANCZOS)
    return crop