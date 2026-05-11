"""Embed text layer into PDF from online API layout results (MinerU/PaddleOCR).

Uses PyMuPDF (fitz) with page.insert_text() for precise per-block positioning,
matching the LLM OCR pipeline's approach (not insert_textbox which auto-fits).
"""

from pathlib import Path
from typing import Any, Dict, List

import fitz

PageTextBlocks = Dict[int, List[Dict[str, Any]]]

_SIMSUN_PATH = r"C:\Windows\Fonts\simsun.ttc"


def _ensure_cjk_font(page):
    """Embed CJK font in page if available. Returns fontname."""
    if Path(_SIMSUN_PATH).exists():
        try:
            page.insert_font(fontname="F1", fontfile=_SIMSUN_PATH)
            return fitz.Font(fontfile=_SIMSUN_PATH), "F1"
        except Exception:
            pass
    return fitz.Font("helv"), "helv"


def _has_cjk(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in (
            (0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF),
            (0x3040, 0x309F), (0x30A0, 0x30FF), (0x3000, 0x303F),
            (0xFF00, 0xFFEF),
        )):
            return True
    return False


def embed_api_text_layer(
    input_path: str,
    output_path: str,
    layout: PageTextBlocks,
    font_size: float = 9.0,
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

            # Normalized coordinates → PDF points
            x0 = bbox[0] * pw
            y0 = bbox[1] * ph
            x1 = bbox[2] * pw
            y1 = bbox[3] * ph

            box_w = x1 - x0
            box_h = y1 - y0
            if box_w <= 1 or box_h <= 1:
                continue

            # Auto-size font to fit within box height
            ascender = getattr(font, "ascender", 1.075)
            descender = getattr(font, "descender", -0.299)
            extent_em = max(0.01, ascender - descender)
            fs = max(3.0, min(72.0, box_h / extent_em))

            # Baseline at box bottom, shifted up by descender
            baseline = fitz.Point(x0, y1 + descender * fs)

            # Horizontal scaling: stretch text to fill box width (matching LLM OCR pipeline)
            natural_width = font.text_length(text, fontsize=fs)
            if natural_width > 0:
                target_width = max(1.0, box_w * 0.98)
                scale_x = target_width / natural_width
                morph = (baseline, fitz.Matrix(scale_x, 1.0))
            else:
                morph = None

            try:
                kwargs = {"fontsize": fs, "render_mode": 3}
                if _has_cjk(text):
                    kwargs["fontname"] = "F1"
                else:
                    kwargs["fontname"] = fontname
                if morph:
                    kwargs["morph"] = morph
                page.insert_text(baseline, text, **kwargs)
            except Exception:
                pass

    doc.save(output_path, incremental=False, encryption=0)
    doc.close()
