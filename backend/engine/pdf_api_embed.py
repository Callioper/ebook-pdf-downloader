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

    # === Multi-line detection (matching LLM OCR pipeline) ===
    norm_height = ny1 - ny0
    aspect = box_h / max(0.01, box_w)
    words = text.split()
    if norm_height > 0.07 and aspect > 0.20 and len(words) >= 2:
        n_lines = 3 if norm_height > 0.13 else 2
        n_lines = min(n_lines, len(words))
        slice_h = norm_height / n_lines
        for i in range(n_lines):
            start = round(i * len(words) / n_lines)
            end = round((i + 1) * len(words) / n_lines)
            line_text = " ".join(words[start:end])
            if not line_text:
                continue
            _draw_block(page, nx0, ny0 + i * slice_h, nx1, ny0 + (i + 1) * slice_h, line_text, pw, ph, font, fontname)
        return

    # === Single-line: auto-size font + horizontal morph scaling ===
    ascender = getattr(font, "ascender", 1.075)
    descender = getattr(font, "descender", -0.299)
    extent_em = max(0.01, ascender - descender)
    fs = max(3.0, min(24.0, box_h / extent_em))  # cap at 24pt — MinerU bboxes have generous padding

    baseline = fitz.Point(x0, y1 + descender * fs)

    natural_width = font.text_length(text, fontsize=fs)
    if natural_width <= 0:
        return

    target_width = max(1.0, box_w * 0.98)
    scale_x = target_width / natural_width
    morph = (baseline, fitz.Matrix(scale_x, 1.0))

    try:
        page.insert_text(baseline, text, fontname=fontname, fontsize=fs, render_mode=3, morph=morph)
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
