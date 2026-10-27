# -*- coding: utf-8 -*-
"""MochiOCR — vertical-manuscript OCR for 古籍 PDF（草書／手寫中文）.

Pipeline: PDF → page images → column detection → single-column strips
→ vision-LLM transcription (LoRA-served Qwen3-VL) → assembled text.
"""
__version__ = "0.3.0"