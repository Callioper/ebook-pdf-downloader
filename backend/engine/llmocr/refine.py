"""Per-box crop re-OCR — refine stage for boxes DP alignment couldn't populate.
Matches ahnafnafee/local-llm-pdf-ocr OCRPipeline._refine_uncertain."""

import asyncio
import base64
import io
import logging
from typing import Optional

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

_PANGRAMS: set[str] = {
    "the quick brown fox jumps over the lazy dog",
    "the quick brown fox jumps over a lazy dog",
    "pack my box with five dozen liquor jugs",
    "sphinx of black quartz judge my vow",
    "how vexingly quick daft zebras jump",
    "the five boxing wizards jump quickly",
    "jackdaws love my big sphinx of quartz",
}

def _is_pangram(text: str) -> bool:
    """Detect LLM hallucination fallback text (pangrams)."""
    normalized = " ".join(text.lower().split())
    return normalized in _PANGRAMS


def is_refinable(box: list[float]) -> bool:
    """Only trigger re-OCR for boxes large enough to plausibly contain text.
    Cutoffs in normalized (0..1) page coords, tuned to skip rules/decorations."""
    width = box[2] - box[0]
    height = box[3] - box[1]
    return width > 0.03 and height > 0.008


def crop_for_ocr(image_url: str, box: list[float], pad_ratio: float = 0.02) -> Optional[str]:
    """Crop a Surya-detected box from a page image for individual re-OCR.
    
    Accepts either raw base64 or data: URL. Returns base64 data URL
    of the JPEG crop, or None if blank.
    """
    import base64
    if "," in image_url:
        raw = base64.b64decode(image_url.split(",", 1)[1])
    else:
        raw = base64.b64decode(image_url)
    img = Image.open(io.BytesIO(raw))
    w, h = img.size

    nx0, ny0, nx1, ny1 = box
    px0 = max(0, int(nx0 * w - w * pad_ratio))
    py0 = max(0, int(ny0 * h - h * pad_ratio))
    px1 = min(w, int(nx1 * w + w * pad_ratio))
    py1 = min(h, int(ny1 * h + h * pad_ratio))

    if px1 <= px0 or py1 <= py0:
        return None

    crop = img.crop((px0, py0, px1, py1))

    # Blank check: skip near-uniform regions to avoid LLM pangram fallback
    arr = np.array(crop.convert("L"))
    if arr.std() < 12.0:
        return None

    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")


async def refine_uncertain(
    pages_data: dict[int, list[tuple[list[float], str]]],
    images_dict: dict[int, str],
    ocr_processor,  # LlmApiClient with perform_ocr_on_crop(image_b64) -> str
    concurrency: int = 3,
    progress_cb=None,
) -> None:
    """Re-OCR boxes that DP alignment left empty.

    Mutates pages_data in place: replaces empty-text boxes with re-OCR'd text.

    Args:
        pages_data: {page_num: [(box, text), ...]} — mutated in place
        images_dict: {page_num: base64_image} — page images for cropping
        ocr_processor: has async perform_ocr_on_crop(image_b64) -> str method
        concurrency: max concurrent LLM calls
        progress_cb: async callback(stage, current, total, message)
    """
    targets: list[tuple[int, int, list[float]]] = []
    for p_num, aligned in pages_data.items():
        for idx, (box, text) in enumerate(aligned):
            if not text.strip() and is_refinable(box):
                targets.append((p_num, idx, box))

    if not targets:
        return

    total = len(targets)
    if progress_cb:
        await progress_cb("refine", 0, total, f"Refining {total} uncertain boxes...")

    sem = asyncio.Semaphore(max(1, concurrency))

    async def refine_one(p_num: int, idx: int, box: list[float]):
        async with sem:
            if images_dict.get(p_num) is None:
                return p_num, idx, ""
            crop_b64 = await asyncio.to_thread(crop_for_ocr, images_dict[p_num], box)
            if crop_b64 is None:
                return p_num, idx, ""
            text = await ocr_processor.perform_ocr_on_crop(crop_b64)
            text = (text or "").strip()
            if _is_pangram(text):
                log.debug("Refine pangram filtered for box %d page %d", idx, p_num)
                text = ""
            return p_num, idx, text

    completed = 0
    for coro in asyncio.as_completed([refine_one(p, i, b) for p, i, b in targets]):
        p_num, idx, text = await coro
        bb, _ = pages_data[p_num][idx]
        pages_data[p_num][idx] = (bb, text)
        completed += 1
        if progress_cb:
            await progress_cb("refine", completed, total, f"Refining boxes ({completed}/{total})")

    # Dedup: drop refine text already present in a matched nearby box
    for p_num in pages_data:
        _dedup_page(pages_data[p_num])

    if progress_cb:
        await progress_cb("refine", total, total, "Refine complete.")


def _dedup_page(page_boxes: list[tuple[list[float], str]], radius: int = 4) -> None:
    """One-way dedup: if refined box text appears in a non-refined neighbour, clear it."""
    for r_idx in range(len(page_boxes)):
        r_text = page_boxes[r_idx][1]
        if not r_text:
            continue
        r_norm = " ".join(r_text.lower().split())
        if not r_norm:
            continue
        lo, hi = max(0, r_idx - radius), min(len(page_boxes), r_idx + radius + 1)
        for o_idx in range(lo, hi):
            if o_idx == r_idx:
                continue
            o_text = page_boxes[o_idx][1]
            if not o_text:
                continue
            o_norm = " ".join(o_text.lower().split())
            if r_norm in o_norm:
                page_boxes[r_idx] = (page_boxes[r_idx][0], "")
                break
