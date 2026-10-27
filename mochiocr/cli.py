# -*- coding: utf-8 -*-
"""MochiOCR command line.

Examples:
  # 1) start the model server (LoRA gguf on llama.cpp; ROCm/Vulkan/CPU auto)
  python3 -m mochiocr serve --gguf mochiocr/model/*.gguf --lora mochiocr/model/caoshu-v8-lora-f16.gguf

  # 2) ancient-book PDF -> electronic text
  python3 -m mochiocr pdf2text 古籍.pdf -o out/book --pages 1-8 --dpi 200 \
      --backend http://127.0.0.1:8800/v1

  # 3) folder of calligraphy photos -> text
  python3 -m mochiocr pdf2text IMG_DIR -o out/letters --backend http://127.0.0.1:8800/v1

  # 4) use a running Ollama vision model instead (zero-shot, no LoRA)
  python3 -m mochiocr pdf2text 古籍.pdf -o out/ --backend ollama:qwen3-vl:30b-a3b-instruct-q4_K_M
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

from . import ocrclient
from .segment import detect_columns, crop_strip
from .assemble import run_pipeline


def _resolve_endpoint(spec: str):
    if spec.startswith("ollama:"):
        return "http://127.0.0.1:11434/v1", spec.split(":", 1)[1]
    return spec, "default"


def _resolve(args):
    if args.backend.startswith("ollama:"):
        model = args.backend.split(":", 1)[1]
        base = "http://127.0.0.1:11434/v1"
        return base, model
    if args.backend.startswith("http"):
        base = args.backend
        model = args.model or "default"
        return base, model
    raise SystemExit(f"--backend 形式錯誤: {args.backend}")


def cmd_pdf2text(args):
    from . import pdfrender
    src = Path(args.input)
    if src.is_dir():
        paths = pdfrender.image_dir_images(src)
        if args.max_side:
            paths = pdfrender.resize_pages(paths, args.max_side)
    else:
        paths = pdfrender.pdf_pages(src, Path(args.out) / "pages", args.pages, args.dpi)
        if args.max_side:
            paths = pdfrender.resize_pages(paths, args.max_side)
    base, model = _resolve(args)
    if not ocrclient.server_ready(base):
        print(f"錯誤：OCR 服務 {base} 沒有回應。請先用 `python3 -m mochiocr serve` 啟動。", file=sys.stderr)
        return 2
    prompt = args.prompt or ocrclient.DEFAULT_PROMPT

    strip_side = args.strip_side

    def ocr_fn(page_img, seg):
        crop = crop_strip(page_img, seg, side=strip_side)
        if args.consensus and args.consensus > 1:
            extra = None
            if args.model2:
                b2, m2 = _resolve_endpoint(args.model2)
                extra = [(b2, m2)]
            return ocrclient.consensus_ocr(base, model, crop, prompt=prompt,
                                           samples=args.consensus,
                                           extra_endpoints=extra,
                                           max_tokens=args.max_tokens)
        return ocrclient.chat_ocr_robust(base, model, crop, prompt=prompt,
                                         max_tokens=args.max_tokens)

    def seg_fn(page_img):
        return detect_columns(page_img, verbose=True)

    rerank_fn = None
    if args.rerank:
        def rerank_fn(page_img, seg, draft, left_draft, right_draft):
            crop = crop_strip(page_img, seg, side=strip_side)
            ctx = ("以下為同頁相鄰列的暫定釋讀（可能有誤，僅供文意參考）。\n"
                   f"右列(先讀): {right_draft or '（無）'}\n"
                   f"左列(後讀): {left_draft or '（無）'}\n"
                   f"本列暫定: {draft}\n")
            p2 = (prompt + "\n" + ctx +
                  "請只依圖中實際筆畫重新逐字釋讀本列，可參考文意校正明顯形近字，"
                  "但不得無中生有；看不清的字寧可少寫。")
            return ocrclient.chat_ocr_robust(base, model, crop, prompt=p2,
                                             max_tokens=args.max_tokens)

    out_txt = run_pipeline(paths, Path(args.out), seg_fn=seg_fn, ocr_fn=ocr_fn,
                           rerank_fn=rerank_fn)
    print(f"完成：{out_txt}")
    return 0


def cmd_serve(args):
    import glob as globlib
    exe = args.llama_server or "/home/kinyeah/llama.cpp/build/bin/llama-server"
    ggufs = sorted(globlib.glob(args.gguf)) if args.gguf else []
    gguf = next((g for g in ggufs if "mmproj" not in g.lower()), None)
    mmproj = args.mmproj or next((g for g in ggufs if "mmproj" in g.lower()), None)
    if not gguf:
        raise SystemExit("找不到模型 gguf（--gguf）")
    cmd = [exe, "-m", gguf, "--host", args.host, "--port", str(args.port),
           "--ctx-size", str(args.ctx), "--jinja"]
    if mmproj:
        cmd += ["--mmproj", mmproj]
    if args.lora:
        cmd += ["--lora", args.lora]
    ngl = args.ngl if args.ngl is not None else 99
    if ngl >= 0:
        cmd += ["-ngl", str(ngl)]
    print("啟動：", " ".join(cmd), flush=True)
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mochiocr", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("pdf2text", help="古籍 PDF 或圖片資料夾 → 電子文字")
    p1.add_argument("input", help="PDF 檔，或是含頁圖的資料夾")
    p1.add_argument("-o", "--out", required=True)
    p1.add_argument("--pages", default=None, help='頁碼規格，如 "1-5,8"')
    p1.add_argument("--dpi", type=int, default=200)
    p1.add_argument("--max-side", type=int, default=3200, help="頁面預先縮圖上限")
    p1.add_argument("--backend", default="http://127.0.0.1:8800/v1",
                    help="'http://host:port/v1' 或 'ollama:<model>'")
    p1.add_argument("--model", default=None, help="OpenAI 端點的 model 名")
    p1.add_argument("--model2", default=None, help="第二投票模型，如 ollama:qwen3-vl:30b-a3b-instruct-q4_K_M")
    p1.add_argument("--max-tokens", type=int, default=260)
    p1.add_argument("--prompt", default=None)
    p1.add_argument("--consensus", type=int, default=1, help="每列取 N 次取樣投票（>=2 開啟）")
    p1.add_argument("--rerank", action="store_true", help="整頁組稿後依相鄰列文意重讀校正")
    p1.add_argument("--strip-side", type=int, default=3100, help="單列長邊上限（訓練尺度=2600）")
    p1.set_defaults(fn=cmd_pdf2text)

    p2 = sub.add_parser("serve", help="啟動 llama.cpp OpenAI 伺服器（載入 LoRA）")
    p2.add_argument("--gguf", default="mochiocr/model/caoshu-v8-merged-Q4_K_M.gguf")
    p2.add_argument("--mmproj", default=None)
    p2.add_argument("--lora", default=None,
                    help="生產＝v8 已整入主檔（免 --lora）；要 runtime-LoRA 才需要這個參數")
    p2.add_argument("--llama-server", default=None)
    p2.add_argument("--host", default="127.0.0.1")
    p2.add_argument("--port", type=int, default=8800)
    p2.add_argument("--ctx", type=int, default=8192)
    p2.add_argument("--ngl", type=int, default=None, help="-ngl 層數；-1=全 CPU")
    p2.set_defaults(fn=cmd_serve)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())