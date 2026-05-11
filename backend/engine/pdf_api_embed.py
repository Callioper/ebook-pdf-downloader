"""Embed text layer into PDF from online API layout results (MinerU/PaddleOCR).

Uses PyMuPDF (fitz) for proper CJK text encoding — avoids pikepdf CID issues.
"""

from pathlib import Path
from typing import Any, Dict, List

import fitz

PageTextBlocks = Dict[int, List[Dict[str, Any]]]

_SIMSUN_PATH = r"C:\Windows\Fonts\simsun.ttc"

DEFAULT_FONT_SIZE = 8.0


def embed_api_text_layer(
    input_path: str,
    output_path: str,
    layout: PageTextBlocks,
    font_size: float = DEFAULT_FONT_SIZE,
) -> None:
    doc = fitz.open(input_path)

    # Compute pixel-to-point scale per page from bbox ranges
    page_max_xy: Dict[int, tuple] = {}
    for pg, blocks in layout.items():
        if pg >= len(doc):
            continue
        max_x = max_y = 1
        for b in blocks:
            bbox = b.get("bbox")
            if bbox:
                max_x = max(max_x, bbox[2])
                max_y = max(max_y, bbox[3])
        page_max_xy[pg] = (max_x, max_y)

    for pg in range(len(doc)):
        page = doc[pg]
        pw = page.rect.width
        ph = page.rect.height
        blocks = layout.get(pg, [])

        if not blocks:
            continue

        # Get pixel dimensions for this page
        pmax = page_max_xy.get(pg)
        if not pmax or pmax[0] <= 1:
            continue
        px_w, px_h = pmax

        # Scale: points = pixels * (page_points / pixel_max)
        sx = pw / px_w
        sy = ph / px_h

        # Embed CJK font
        cjk_needed = any(b.get("text", "") for b in blocks)
        if cjk_needed and Path(_SIMSUN_PATH).exists():
            try:
                page.insert_font(fontname="F1", fontfile=_SIMSUN_PATH)
                fontname = "F1"
            except Exception:
                fontname = "helv"
        else:
            fontname = "helv"

        for block in blocks:
            text = (block.get("text") or "").strip()
            if not text:
                continue

            bbox = block.get("bbox")
            if bbox and len(bbox) == 4:
                rect = fitz.Rect(
                    bbox[0] * sx,
                    bbox[1] * sy,
                    bbox[2] * sx,
                    bbox[3] * sy,
                )
            else:
                rect = fitz.Rect(50, 50, pw - 50, ph - 50)

            if rect.width <= 0 or rect.height <= 0:
                continue

            try:
                page.insert_textbox(
                    rect,
                    text,
                    fontname=fontname,
                    fontsize=font_size,
                    render_mode=3,  # invisible
                    align=0,
                )
            except Exception:
                pass

    doc.save(output_path, incremental=False, encryption=0)
    doc.close()
