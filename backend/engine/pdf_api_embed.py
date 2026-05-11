"""Embed text layer into PDF from online API layout results (MinerU/PaddleOCR).

Matches LLM OCR pipeline approach: insert_text with morph scaling for single-line blocks,
recursive vertical splitting for tall/multi-line blocks.
"""

from pathlib import Path
from typing import Any, Dict, List

import fitz

PageTextBlocks = Dict[int, List[Dict[str, Any]]]

_SIMSUN_PATH = r"C:\Windows\Fonts\simsun.ttc"


def _ensure_cjk_font(page):
    if Path(_SIMSUN_PATH).exists():
        try:
            page.insert_font(fontname="F1", fontfile=_SIMSUN_PATH)
            return fitz.Font(fontfile=_SIMSUN_PATH), "F1"
        except Exception:
            pass
    return fitz.Font("helv"), "helv"


def _draw_block(page, nx0, ny0, nx1, ny1, text, pw, ph, font, fontname):
    """Draw one block of text at normalized coords. Recurses for multi-line blocks."""
    text = text.strip()
    if not text:
        return

    x0, y0, x1, y1 = nx0 * pw, ny0 * ph, nx1 * pw, ny1 * ph
    box_w = x1 - x0
    box_h = y1 - y0
    if box_w <= 1 or box_h <= 1:
        return

    # === Multi-line detection (matching LLM OCR pipeline + CJK support) ===
    norm_height = ny1 - ny0
    aspect = box_h / max(0.01, box_w)
    words = text.split()
    # Also count CJK characters (no spaces between words)
    cjk_chars = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff' or '\u3400' <= ch <= '\u4dbf')
    total_chars = max(len(words), cjk_chars)

    if norm_height > 0.07 and aspect > 0.20 and total_chars >= 2:
        n_lines = 3 if norm_height > 0.13 else 2
        n_lines = min(n_lines, total_chars)
        slice_h = norm_height / n_lines
        # Split text evenly across lines by character count (for CJK) or word count
        if cjk_chars > len(words):
            chars_per_line = max(1, len(text) // n_lines)
            for i in range(n_lines):
                start = i * chars_per_line
                end = start + chars_per_line if i < n_lines - 1 else len(text)
                line_text = text[start:end].strip()
                if not line_text:
                    continue
                _draw_block(page, nx0, ny0 + i * slice_h, nx1, ny0 + (i + 1) * slice_h, line_text, pw, ph, font, fontname)
        else:
            for i in range(n_lines):
                start = round(i * len(words) / n_lines)
                end = round((i + 1) * len(words) / n_lines)
                line_text = " ".join(words[start:end])
                if not line_text:
                    continue
                _draw_block(page, nx0, ny0 + i * slice_h, nx1, ny0 + (i + 1) * slice_h, line_text, pw, ph, font, fontname)
        return

    # === Single-line: place at box top ===
    fs = max(6.0, min(16.0, box_h * 0.7))
    baseline = fitz.Point(x0 + 2, y0 + fs)  # CJK glyph sits on baseline, extends upward
    
    try:
        page.insert_text(baseline, text, fontname=fontname, fontsize=fs, render_mode=3)
    except Exception:
        pass


def embed_api_text_layer(
    input_path: str,
    output_path: str,
    layout: PageTextBlocks,
    font_size: float = 6.0,
) -> None:
    doc = fitz.open(input_path)

    for pg in range(len(doc)):
        page = doc[pg]
        pw = page.rect.width
        ph = page.rect.height
        blocks = layout.get(pg, [])
        if not blocks:
            continue

        font, fontname = _ensure_cjk_font(page)

        for block in blocks:
            text = (block.get("text") or "").strip()
            if not text:
                continue
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            _draw_block(page, bbox[0], bbox[1], bbox[2], bbox[3], text, pw, ph, font, fontname)

    doc.save(output_path, garbage=3, deflate=True)
    doc.close()
