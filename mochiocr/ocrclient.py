# -*- coding: utf-8 -*-
"""Vision-LLM OCR client (OpenAI-compatible /v1/chat/completions).

Works with:
  * llama.cpp `llama-server` (this package's `serve` command, LoRA loaded)
  * Ollama's OpenAI-compatible endpoint (e.g. qwen3-vl base zero-shot)
  * any other OpenAI-compatible multimodal server
"""
from __future__ import annotations

import io
import json
import base64
import time
import re
import urllib.request
from pathlib import Path

CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

DEFAULT_PROMPT = (
    "這是古典文稿中的一個「直列」（由上往下書寫，可能為手寫或草書）。"
    "只根據圖中可見筆畫逐字釋讀。禁止默寫唐詩或名帖全文。"
    "只輸出你確實看見的繁體字，看不清就停；不要標點、不要解說。"
)


def to_b64(img) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _post(url, payload, timeout=900):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def chat_ocr(base_url: str, model: str, image, prompt: str = DEFAULT_PROMPT,
             temperature: float = 0.0, max_tokens: int = 220, retries: int = 2,
             timeout: int = 900) -> str:
    """Send one strip image, return cleaned CJK transcription."""
    img_b64 = to_b64(image)
    content = [{"type": "text", "text": prompt},
               {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}}]
    msgs = [{"role": "user", "content": content}]
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        if url.endswith("/v1"):
            url += "/chat/completions"
        else:
            url += "/v1/chat/completions"
    payload = {"model": model, "messages": msgs, "temperature": temperature,
               "max_tokens": max_tokens, "stream": False}
    last = None
    for i in range(retries + 1):
        try:
            d = _post(url, payload, timeout=timeout)
            txt = (d["choices"][0]["message"].get("content") or "")
            return txt
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"OCR request failed after {retries + 1} tries: {last}")


def clean_text(s: str, keep_ascii_num: bool = False) -> str:
    t = "".join(CJK.findall(s or ""))
    return t


def degenerated(s: str) -> bool:
    if re.search(r"(.)\1{7,}", s):
        return True
    for L in (2, 3, 4):
        if re.search(rf"(.{{{L}}})\1{{3,}}", s):
            return True
    return False


def chat_ocr_robust(base_url, model, image, prompt=DEFAULT_PROMPT, **kw) -> str:
    txt = chat_ocr(base_url, model, image, prompt=prompt, **kw)
    t = clean_text(txt)
    if t and degenerated(t):
        # one retry with a little temperature; keep the non-repeating head otherwise
        t2 = clean_text(chat_ocr(base_url, model, image, prompt=prompt, temperature=0.75, **kw))
        if t2 and not degenerated(t2):
            return t2
        return re.split(r"(.)\1{6,}", t)[0]
    return t


def server_ready(base_url: str, timeout: float = 3.0) -> bool:
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        url += "/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:
        return False

def align_seq(ref: str, other: str, gap: float = 0.62, mismatch: float = 0.05):
    """Monotone Needleman-Wunsch; returns other-index -> ref-index map (or None)."""
    N, M = len(ref), len(other)
    if N == 0 or M == 0:
        return [None] * M
    INF = float("-inf")
    d = [[0.0] * (M + 1) for _ in range(N + 1)]
    tr = [[0] * (M + 1) for _ in range(N + 1)]
    for i in range(1, N + 1):
        d[i][0] = d[i - 1][0] - gap
        tr[i][0] = 2
    for j in range(1, M + 1):
        d[0][j] = d[0][j - 1] - gap
        tr[0][j] = 3
    for i in range(1, N + 1):
        di, drow = d[i - 1], d[i]
        ai = ref[i - 1]
        for j in range(1, M + 1):
            eq = (ai == other[j - 1])
            best, bk = di[j] + (1.0 if eq else mismatch), 1
            v = di[j - 1] - gap
            if v > best:
                best, bk = v, 3
            v = drow[j - 1] - gap
            if v > best:
                best, bk = v, 2
            d[i][j], tr[i][j] = best, bk
    ends = [(d[N][M], N, M)]
    for ii in range(N, -1, -1):
        if d[ii][M] > ends[0][0]:
            ends = [(d[ii][M], ii, M)]
    for jj in range(M, -1, -1):
        if d[N][jj] > ends[0][0]:
            ends = [(d[N][jj], N, jj)]
    score, i, j = ends[0]
    m2k = [None] * M
    while i > 0 and j > 0:
        t = tr[i][j]
        if t == 1:
            if ref[i - 1] == other[j - 1]:
                m2k[j - 1] = i - 1
            i -= 1
            j -= 1
        elif t == 2:
            i -= 1
        elif t == 3:
            j -= 1
        else:
            break
    return m2k


def consensus_ocr(base_url, model, image, prompt=DEFAULT_PROMPT, samples=3,
                  temperatures=(0.0, 0.7, 1.0), extra_endpoints=None, **kw) -> str:
    """K-pass self-consistency: majority vote over DP-aligned characters.

    extra_endpoints: list of (base_url, model) — other models to vote with
    (cross-model ensemble, independent error distributions)."""
    outs = []
    endpoints = [(base_url, model, t) for t in temperatures[:max(1, samples)]]
    for be, mo, t in (extra_endpoints or [])[:max(0, 3 - len(endpoints))]:
        endpoints.append((be, mo, 0.0))
    for base_i, model_i, t in endpoints:
        try:
            txt = clean_text(chat_ocr(base_i, model_i, image, prompt=prompt,
                                      temperature=t, **kw))
            if txt:
                outs.append(txt)
        except Exception:
            continue
    if not outs:
        return ""
    if len(outs) == 1:
        return outs[0]
    ref = max(outs, key=len)
    votes = [dict() for _ in ref]
    for k, ch in enumerate(ref):
        votes[k][ch] = votes[k].get(ch, 0) + 1
    for other in outs:
        if other is ref:
            continue
        m2k = align_seq(ref, other)
        for j, k in enumerate(m2k):
            if k is not None:
                votes[k][other[j]] = votes[k].get(other[j], 0) + 1
    out = []
    for k in range(len(ref)):
        best = max(votes[k].items(), key=lambda kv: (kv[1], kv[0] == ref[k]))
        out.append(best[0])
    res = "".join(out)
    return res
