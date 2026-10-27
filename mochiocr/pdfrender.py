# -*- coding: utf-8 -*-
"""PDF rendering: PDF pages to images via poppler (pdftoppm)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from PIL import Image


def pdf_pages(pdf: str | Path, out_dir: Path, pages: str | None = None,
              dpi: int = 200) -> list[Path]:
    """Render PDF pages to PNG files named page-<NNNN>.png.

    pages: spec like "1-5,8" (1-based); None = every page.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # clean old pages (avoid stale mixing)
    for old in out_dir.glob("page-*.png"):
        old.unlink()
    first, last = _spec_bounds(pages) if pages else (None, None)
    cmd = ["pdftoppm", "-r", str(dpi), "-png"]
    if first is not None and last is not None:
        cmd += ["-f", str(first), "-l", str(last)]
    elif first is not None:
        cmd += ["-f", str(first)]
    cmd += [str(pdf), str(out_dir / "page")]
    subprocess.run(cmd, check=True, capture_output=True)
    return sorted(out_dir.glob("page-*.png"))


def _spec_bounds(spec: str) -> tuple[int, int | None]:
    """Return (first, last|None); None last means 'to the end'."""
    first, last = None, None
    for part in [x for x in spec.replace(" ", "").split(",") if x]:
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a) if a else 1
            b = int(b) if b else None
            first = a if first is None else min(first, a)
            last = None if b is None else max(last or b, b)
        else:
            v = int(part)
            first = v if first is None else min(first, v)
    return (first or 1), last


def image_dir_images(d_dir: str | Path) -> list[Path]:
    exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"}
    d = Path(d_dir)
    return sorted(p for p in d.iterdir() if p.suffix.lower() in exts)


def resize_pages(paths: list[Path], max_side: int = 3200) -> list[Path]:
    """Downscale huge scans in place-adjacent .mo.png files."""
    out = []
    for p in paths:
        im = Image.open(p)
        if max(im.size) <= max_side:
            out.append(p)
            continue
        r = max_side / max(im.size)
        im2 = im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))), Image.LANCZOS)
        q = p.with_suffix(".mo.png")
        im2.convert("RGB").save(q)
        out.append(q)
    return out