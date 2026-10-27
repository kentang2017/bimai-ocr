# -*- coding: utf-8 -*-
"""Assemble per-page OCR results into electronic text (right-to-left columns)."""
from __future__ import annotations

import json
from pathlib import Path


def run_pipeline(source_paths: list[Path], out_dir: Path, *,
                 seg_fn, ocr_fn, rerank_fn=None, keep_punct: bool = False,
                 max_pages: int | None = None, verbose=True) -> Path:
    """source_paths: page images in order. seg_fn(page_img)->PageSegments.
    ocr_fn(pil_image, seg)->str. Writes out/ocr_result.txt/.json."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pages_txt: list[str] = []
    all_meta = []
    for pi, p in enumerate(source_paths):
        if max_pages and pi >= max_pages:
            break
        page = _load(p)
        segs = seg_fn(page)
        # merge tiles belonging to one column into a single line
        cols: dict[int, list] = {}
        for s in segs.strips:
            cols.setdefault(s.x0, []).append(s)
        lines = []
        ordered_x = sorted(cols, key=lambda x: -x)
        drafts: dict[int, list[str]] = {}
        boxes_store: dict[int, list] = {}
        for x0 in ordered_x:
            parts = sorted(cols[x0], key=lambda s: s.y0)
            chunks = []
            boxes = []
            for s in parts:
                txt = ocr_fn(page, s)
                chunks.append(txt)
                boxes.append({"x0": s.x0, "y0": s.y0, "x1": s.x1, "y1": s.y1, "text": txt})
            line = "".join(chunks)
            drafts[x0] = line
        if rerank_fn is not None:
            for xi, x0 in enumerate(ordered_x):
                right_draft = drafts[ordered_x[xi - 1]] if xi > 0 else ""
                left_draft = drafts[ordered_x[xi + 1]] if xi + 1 < len(ordered_x) else ""
                parts = sorted(cols[x0], key=lambda s: s.y0)
                re_lines = []
                for s in parts:
                    re_lines.append(rerank_fn(page, s, drafts[x0], left_draft, right_draft))
                drafts[x0] = "".join(re_lines)
        # 依 rerank 修正版輸出
        for x0 in ordered_x:
            line = drafts[x0]
            lines.append(line)
            all_meta.append({"page": pi + 1, "file": Path(p).name, "column_x": x0,
                             "boxes": boxes_store.get(x0, []), "text": line})
        page_text = "\n".join(lines)
        pages_txt.append(page_text)
        if verbose:
            print(f"[page {pi+1}] {Path(p).name}: {len(lines)} columns", flush=True)
        # per-page txt
        (out_dir / f"page_{pi+1:04d}.txt").write_text(page_text, encoding="utf-8")

    body = "\n\n".join(f"第 {i+1} 頁\n{t}" for i, t in enumerate(pages_txt))
    (out_dir / "ocr_result.txt").write_text(body, encoding="utf-8")
    (out_dir / "ocr_result.json").write_text(
        json.dumps(all_meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_dir / "ocr_result.txt"


def _load(p: Path):
    from PIL import Image
    return Image.open(p).convert("RGB")