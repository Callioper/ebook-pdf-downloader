"""Embed text layer into PDF from online API layout results (MinerU/PaddleOCR).

Uses PyMuPDF page.insert_textbox() for block-level bbox — MinerU provides
paragraph-level text within region-level bboxes. insert_textbox auto-fits
multi-line text within the rect, avoiding manual line-splitting inaccuracies.
"""

from pathlib import Path
from typing import Any, Dict, List

import fitz

PageTextBlocks = Dict[int, List[Dict[str, Any]]]

_SIMSUN_PATH = r"C:\Windows\Fonts\simsun.ttc"


def embed_api_text_layer(
    input_path: str,
    output_path: str,
    layout: PageTextBlocks,
) -> None:
    doc = fitz.open(input_path)
    has_simsun = Path(_SIMSUN_PATH).exists()

    for pg in range(len(doc)):
        page = doc[pg]
        pw = page.rect.width
        ph = page.rect.height
        blocks = layout.get(pg, [])
        if not blocks:
            continue

        if has_simsun:
            try:
                page.insert_font(fontname="F1", fontfile=_SIMSUN_PATH)
            except Exception:
                has_simsun = False

        for block in blocks:
            text = (block.get("text") or "").strip()
            if not text:
                continue
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue

            rect = fitz.Rect(
                bbox[0] * pw,
                bbox[1] * ph,
                bbox[2] * pw,
                bbox[3] * ph,
            )
            if rect.width < 2 or rect.height < 2:
                continue

            # Auto-size font based on bbox height: 6pt floor, 10pt ceiling
            fs = max(6.0, min(10.0, rect.height / 15.0))

            try:
                page.insert_textbox(
                    rect,
                    text,
                    fontname="F1" if has_simsun else "helv",
                    fontsize=fs,
                    render_mode=3,
                    align=0,
                )
            except Exception:
                pass

    doc.save(output_path, garbage=3, deflate=True)
    doc.close()
