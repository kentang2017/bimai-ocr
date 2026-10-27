#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推論端多樣本集合辨識（ensemble_ocr）

以 N 個樣本（1 個貪婪 + N-1 個取樣）做 DP 對齊加權投票：
每個樣本的權重 = exp(該樣本平均 token logprob)，讓模型「有把握」的讀法主導。
實驗依據（gold_test40）：
  greedy 30.12% → vote 29.61% → vote_w 28.94%（同一次實驗內比較，N=10/temp0.7）
  oracle 22.19% —— 說明正確答案多半已在候選集中，只差好的選擇器。
"""
from __future__ import annotations

import json
import math
import time
from typing import Any

from . import ocrclient

try:
    from .ocrclient import align_seq, clean_text, degenerated, to_b64
except Exception:  # pragma: no cover
    align_seq = None
    clean_text = None
    degenerated = None
    to_b64 = None


def _post_chat(base_url: str, model: str, image, prompt: str,
               temperature: float, seed: int, max_tokens: int = 220,
               timeout: int = 900) -> tuple[str, float]:
    """單次推理，回傳 (清洗後文字, 平均 token logprob)。"""
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        url += "/chat/completions"
    elif not url.endswith("/chat/completions"):
        url += "/v1/chat/completions"
    payload = {
        "model": model,
        "stream": False,
        "temperature": temperature,
        "seed": seed,
        "max_tokens": max_tokens,
        "logprobs": True,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": "data:image/png;base64," + to_b64(image)}},
        ]}],
    }
    for attempt in range(3):
        try:
            d = ocrclient._post(url, payload, timeout=timeout)
            ch = d["choices"][0]
            raw = ch["message"].get("content") or ""
            txt = clean_text(raw)
            lp = ch.get("logprobs") or {}
            toks = lp.get("content") or []
            lps = [t.get("logprob", -99.0) for t in toks]
            mean_lp = (sum(lps) / len(lps)) if lps else -99.0
            if txt and degenerated and degenerated(txt):
                # 退化成重複字時降分，讓它不會主導投票
                mean_lp -= 5.0
            return txt, mean_lp
        except Exception:
            if attempt == 2:
                return "", -99.0
            time.sleep(1.5 * (attempt + 1))
    return "", -99.0


def ensemble_ocr(base_url: str, model: str, image, prompt: str = ocrclient.DEFAULT_PROMPT,
                 n: int = 6, temperature: float = 0.5, base_seed: int = 20260101,
                 verbose: bool = False) -> str:
    """N 樣本 + 置信度加權投票。n<=1 時等同 greedy。"""
    if n <= 1:
        return ocrclient.chat_ocr_robust(base_url, model, image, prompt=prompt)

    samples: list[tuple[str, float]] = []
    g, g_lp = _post_chat(base_url, model, image, prompt, 0.0, base_seed + 7)
    if g:
        samples.append((g, g_lp))
    for k in range(max(0, n - 1)):
        t, lp = _post_chat(base_url, model, image, prompt, temperature, base_seed + 100 + k * 13)
        if t:
            samples.append((t, lp))
    if not samples:
        return ""
    if len(samples) == 1:
        return samples[0][0]
    if verbose:
        print("  samples:", [(s[:10], round(lp, 2)) for s, lp in samples], flush=True)

    # 保守版：以 greedy（最高權重樣本）為底稿，逐字對齊其他人的投票
    greedy = max(samples, key=lambda x: x[1])[0]
    ref = greedy
    votes: list[dict[str, float]] = [dict() for _ in ref]
    for s, lp in samples:
        w = math.exp(max(lp, -20.0))
        if s == ref:
            continue
        m2k = align_seq(ref, s) if align_seq else None
        if m2k is None:
            continue
        for j, k in enumerate(m2k):
            if k is not None:
                votes[k][s[j]] = votes[k].get(s[j], 0.0) + w
    w_ref = math.exp(max(max(lp, -20.0) for _, lp in samples))
    MARGIN = 1.6   # 挑戰者需超過底稿票數 1.6 倍才改字
    out = []
    changed = 0
    for k in range(len(ref)):
        cand = votes[k]
        base = ref[k]
        if not cand:
            out.append(base)
            continue
        alt, alt_w = max(cand.items(), key=lambda kv: kv[1])
        if alt != base and alt_w > w_ref * MARGIN:
            out.append(alt)
            changed += 1
        else:
            out.append(base)
    if verbose:
        print("  changed chars:", changed, "/", len(ref), flush=True)
    res = "".join(out)
    if degenerated and degenerated(res):
        return ref
    return res