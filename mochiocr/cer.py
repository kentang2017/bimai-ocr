# -*- coding: utf-8 -*-
"""CER benchmark for the 3-page demo (ground truth from the museum site).

Usage:
  python3 -m mochiocr.cer mochiocr/samples/demo_lora_out
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Ground truth columns (right -> left), from hcsartmuseum.com project pages
REF = {
    1: [  # 傅山《草書錄李夢陽詩》 pid 15210
        "夜雨清池館晨光散石林一舟相過日",
        "千里獨來心樹擁江聲斷潮生山氣",
        "陰異時懷舊意應比未逢深山書",
    ],
    2: [  # 宋曹《草書孫過庭書譜句》 pid 14419
        "右軍書代多稱習已可據為宗匠所立指歸",
        "豈唯會古通今乃情深調合致使摹搨",
        "日廣研習歲滋先後著名多從散落",
        "歷代孤紹非其效歟射陵逸史宋曹",
    ],
    3: [  # 豐坊《草書王昌齡送魏二》立軸 pid 15115
        "醉別江樓橘柚香",
        "江風引雨入船涼憶君遙在",
        "湘江月愁聽清猿夢裏長禺史",
    ],
}


def lcs_len(a: str, b: str) -> int:
    m, n = len(a), len(b)
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        cur = [0] * (n + 1)
        ai = a[i - 1]
        for j in range(1, n + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = cur[j - 1] if cur[j - 1] >= prev[j] else prev[j]
        prev = cur
    return prev[n]


def page_lines(out_dir: Path, page: int) -> list[str]:
    p = out_dir / f"page_{page:04d}.txt"
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def main(out_dir: str):
    from collections import Counter
    out = Path(out_dir)
    tot_hit = tot_ref = 0
    per_page = {}
    detail = []
    for page, ref_cols in REF.items():
        pred_cols = page_lines(out, page)
        hits = []
        for i, ref in enumerate(ref_cols):
            pred = pred_cols[i] if i < len(pred_cols) else ""
            pred_cjk = "".join(re.findall(r"[\u4e00-\u9fff]", pred))
            hit = lcs_len(ref, pred_cjk)
            hits.append(hit)
            detail.append((page, i, len(ref), len(pred_cjk),
                           round(hit / len(ref) * 100) if ref else 0, pred_cjk[:24]))
        tot_hit += sum(hits)
        tot_ref += sum(len(c) for c in ref_cols)
        per_page[page] = round(sum(hits) / sum(len(c) for c in ref_cols) * 100, 1)
    acc = tot_hit / tot_ref * 100
    print("逐欄: (頁欄, 真長, 出長, 準%, 輸出前綴)")
    for d in detail:
        print(f"  p{d[0]}c{d[1]}: ref={d[2]:2d} out={d[3]:2d} acc={d[4]:3d}%  {d[5]}")
    print("各頁字準%:", per_page)
    print(f"整體: 字準 {acc:.1f}% | CER {100 - acc:.1f}%  (n={tot_ref})")
    return acc


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mochiocr/samples/demo_lora_out")