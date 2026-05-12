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

            # Auto-size font: 9pt minimum, 14pt maximum
            fs = max(9.0, min(14.0, rect.height / 12.0))

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


def embed_with_surya_boxes(
    input_path: str,
    output_path: str,
    surya_boxes: Dict[int, List[List[float]]],
    page_texts: Dict[int, List[str]],
) -> None:
    """Embed text at Surya's precise line-level bbox positions (LLM OCR pipeline approach).

    Surya bboxes are tight around individual text lines, so insert_text + morph
    scaling works correctly (unlike MinerU's block-level bboxes).

    Args:
        input_path: Source PDF path
        output_path: Output PDF path with text layer
        surya_boxes: {page_idx: [[x0,y0,x1,y1], ...]} — normalized [0..1] Surya bboxes
        page_texts: {page_idx: ["line1 text", "line2 text", ...]} — text per line
    """
    doc = fitz.open(input_path)
    has_sim = Path(_SIMSUN_PATH).exists()

    for pg in range(len(doc)):
        page = doc[pg]
        pw = page.rect.width
        ph = page.rect.height
        boxes = surya_boxes.get(pg, [])
        texts = page_texts.get(pg, [])
        if not boxes or not texts:
            continue

        if has_sim:
            try:
                page.insert_font(fontname="F1", fontfile=_SIMSUN_PATH)
            except Exception:
                has_sim = False

        font = fitz.Font(fontfile=_SIMSUN_PATH) if has_sim else fitz.Font("helv")
        fontname = "F1" if has_sim else "helv"

        # Pair boxes with texts in reading order (both sorted)
        for i, bbox in enumerate(boxes):
            text = texts[i].strip() if i < len(texts) else ""
            if not text:
                continue

            pdf_rect = fitz.Rect(
                bbox[0] * pw, bbox[1] * ph,
                bbox[2] * pw, bbox[3] * ph,
            )
            box_w = pdf_rect.width
            box_h = pdf_rect.height
            if box_w <= 1 or box_h <= 1:
                continue

            # LLM OCR pipeline's font sizing + morph scaling for tight single-line bboxes
            ascender = getattr(font, "ascender", 1.075)
            descender = getattr(font, "descender", -0.299)
            extent_em = max(0.01, ascender - descender)
            fs = max(3.0, min(72.0, box_h / extent_em))

            baseline = fitz.Point(pdf_rect.x0, pdf_rect.y1 + descender * fs)
            natural_width = font.text_length(text, fontsize=fs)
            if natural_width <= 0:
                continue

            target_width = max(1.0, box_w * 0.98)
            scale_x = target_width / natural_width
            morph = (baseline, fitz.Matrix(scale_x, 1.0))

            try:
                page.insert_text(baseline, text, fontname=fontname, fontsize=fs, render_mode=3, morph=morph)
            except Exception:
                pass

    doc.save(output_path, garbage=3, deflate=True)
    doc.close()


def allocate_text_to_surya_boxes(
    surya_boxes: Dict[int, List[List[float]]],
    mineru_blocks: PageTextBlocks,
) -> Dict[int, List[str]]:
    """Distribute MinerU block-level text to Surya line-level bboxes.

    For each MinerU block on a page, finds all Surya boxes whose center
    falls within the block's region. Splits the block text proportionally
    by box width, allocating approximate portions to each matching box.

    Surya boxes with no matching MinerU block get empty strings.
    MinerU blocks with no matching Surya boxes are silently dropped.

    Args:
        surya_boxes: {page_idx: [[x0,y0,x1,y1], ...]} normalized [0..1]
        mineru_blocks: {page_idx: [{"text": ..., "bbox": [x0,y0,x1,y1]}, ...]}

    Returns:
        {page_idx: ["line1 text", "line2 text", ...]} — one string per Surya box
    """
    page_texts: Dict[int, List[str]] = {}

    for pg in sorted(surya_boxes.keys()):
        boxes = surya_boxes[pg]
        blocks = mineru_blocks.get(pg, [])

        # Initialize all boxes with empty text
        texts = [""] * len(boxes)

        for block in blocks:
            block_text = (block.get("text") or "").strip()
            block_bbox = block.get("bbox")
            if not block_text or not block_bbox or len(block_bbox) != 4:
                continue

            bx0, by0, bx1, by1 = float(block_bbox[0]), float(block_bbox[1]), float(block_bbox[2]), float(block_bbox[3])

            # Find Surya boxes whose center falls within this MinerU block
            matching: list[tuple[int, float]] = []  # [(box_index, box_width)]
            for i, bbox in enumerate(boxes):
                if len(bbox) < 4:
                    continue
                sx0, sy0, sx1, sy1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                cx = (sx0 + sx1) / 2.0
                cy = (sy0 + sy1) / 2.0
                if bx0 <= cx <= bx1 and by0 <= cy <= by1:
                    box_w = max(0.001, sx1 - sx0)
                    matching.append((i, box_w))

            if not matching:
                continue

            # Split block text proportionally by box width
            total_w = sum(w for _, w in matching)
            text_len = len(block_text)
            cursor = 0

            for idx, box_w in matching:
                ratio = box_w / total_w
                chars = max(0, round(text_len * ratio))
                end = min(text_len, cursor + chars)
                # Last box in group gets remaining text to avoid truncation
                if idx == matching[-1][0]:
                    end = text_len
                chunk = block_text[cursor:end]
                if chunk:
                    if texts[idx]:
                        texts[idx] = texts[idx] + " " + chunk
                    else:
                        texts[idx] = chunk
                cursor = end

        page_texts[pg] = texts

    return page_texts
