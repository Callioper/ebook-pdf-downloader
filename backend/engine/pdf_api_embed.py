"""Embed text layer into PDF from online API layout results (MinerU/PaddleOCR).

Uses PyMuPDF (fitz) with page.insert_textbox() for block-level bbox positioning.
MinerU's model.json bboxes are region/block-level (not line-level), so insert_textbox
naturally handles multi-line text within each bbox without excessive horizontal scaling.
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
    font_size: float = 6.0,
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

            # Normalized coordinates → PDF points
            rect = fitz.Rect(
                bbox[0] * pw,
                bbox[1] * ph,
                bbox[2] * pw,
                bbox[3] * ph,
            )

            if rect.width < 2 or rect.height < 2:
                continue

            try:
                kwargs = {
                    "fontsize": font_size,
                    "render_mode": 3,
                    "align": 0,
                }
                if has_simsun:
                    kwargs["fontname"] = "F1"
                else:
                    kwargs["fontname"] = "helv"
                page.insert_textbox(rect, text, **kwargs)
            except Exception:
                pass

    doc.save(output_path, incremental=False, encryption=0)
    doc.close()
