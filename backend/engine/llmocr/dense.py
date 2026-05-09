"""Dense-page OCR mode — per-box crop OCR for pages with many detected boxes.
Matches ahnafnafee/local-llm-pdf-ocr --dense-mode auto/always/never."""

import asyncio
import logging
from llmocr.refine import is_refinable, crop_for_ocr

log = logging.getLogger(__name__)


async def process_dense_pages(
    images_dict: dict[int, str],
    pages_data: dict[int, list[tuple[list[float], str]]],
    ocr_processor,
    threshold: int = 60,
    concurrency: int = 1,
    progress_cb=None,
) -> dict[int, list[tuple[list[float], str]]]:
    """For pages where Surya detected more than `threshold` boxes,
    run per-box OCR instead of full-page LLM OCR.

    Mutates and returns pages_data.
    """
    dense_pages = [
        p_num for p_num, boxes in pages_data.items()
        if len(boxes) > threshold
    ]

    if not dense_pages:
        return pages_data

    log.info("Dense-page mode: %d pages above threshold %d", len(dense_pages), threshold)
    if progress_cb:
        await progress_cb("ocr", 0, len(dense_pages),
            f"Dense pages: {len(dense_pages)} above {threshold} boxes")

    sem = asyncio.Semaphore(max(1, concurrency))

    for page_idx, p_num in enumerate(dense_pages):
        boxes = pages_data[p_num]
        image_url = images_dict.get(p_num)
        if not image_url:
            continue

        async def ocr_one_box(idx: int, box: list[float]) -> tuple[int, str]:
            async with sem:
                crop_b64 = await asyncio.to_thread(crop_for_ocr, image_url, box)
                if crop_b64 is None:
                    return idx, ""
                text = await ocr_processor.perform_ocr_on_crop(crop_b64)
                return idx, (text or "").strip()

        tasks = [
            ocr_one_box(i, box)
            for i, (box, _) in enumerate(boxes)
            if is_refinable(box)
        ]

        if tasks:
            results = await asyncio.gather(*tasks)
            for idx, text in results:
                bb, _ = pages_data[p_num][idx]
                pages_data[p_num][idx] = (bb, text)

        if progress_cb:
            await progress_cb("ocr", page_idx + 1, len(dense_pages),
                f"Dense page {p_num} ({len(boxes)} boxes)")

    return pages_data
