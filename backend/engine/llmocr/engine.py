"""Standalone LLM OCR Pipeline — matches ahnafnafee/local-llm-pdf-ocr.
No ocrmypdf dependency. No Tesseract. Five phases:
  convert -> detect -> ocr -> refine -> embed
"""

import asyncio
import base64
import io
import logging
import os
from pathlib import Path
from typing import Callable, Optional, Awaitable

import fitz
from PIL import Image

from llmocr.aligner import HybridAligner
from llmocr.llm_client import LlmApiClient
from llmocr.refine import refine_uncertain

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".avif"})

ProgressCallback = Callable[[str, int, int, str], Awaitable[None]]


def _data_url_to_bytes(data_url: str) -> bytes:
    """Extract raw bytes from a data: URL."""
    if "," in data_url:
        return base64.b64decode(data_url.split(",", 1)[1])
    return base64.b64decode(data_url)


class LlmOcrPipeline:
    """Standalone LLM OCR pipeline. No ocrmypdf. No Tesseract."""

    def __init__(
        self,
        endpoint: str = "http://localhost:11434",
        model: str = "",
        api_key: str = "",
        timeout: int = 300,
    ):
        self.aligner = HybridAligner()
        self.client = LlmApiClient(
            endpoint=endpoint, model=model, api_key=api_key, timeout=timeout,
        ) if model else None

    async def run(
        self,
        input_path: str,
        output_path: str,
        *,
        dpi: int = 200,
        concurrency: int = 1,
        refine: bool = True,
        max_image_dim: int = 1024,
        progress: Optional[ProgressCallback] = None,
    ) -> dict[int, list[str]]:
        """Execute the full hybrid OCR pipeline.

        Returns {page_num: [llm_text_lines, ...]} for caller inspection.
        """
        # Phase 1: Convert PDF to page images
        await _emit(progress, "convert", 0, 1, "Converting PDF to images...")
        images_dict = _rasterize_pages(input_path, dpi, max_image_dim)
        page_nums = sorted(images_dict.keys())
        total_pages = len(page_nums)
        await _emit(progress, "convert", 1, 1, f"Converted {total_pages} pages.")

        # Phase 2: Batch Surya detection
        await _emit(progress, "detect", 0, 1, f"Detecting layout for {total_pages} pages...")
        image_bytes = [_data_url_to_bytes(images_dict[p]) for p in page_nums]
        batch_boxes = await asyncio.to_thread(self.aligner.detect_batch, image_bytes)
        pages_data: dict[int, list[tuple[list[float], str]]] = {
            p: [(box, "") for box in batch_boxes[i]]
            for i, p in enumerate(page_nums)
        }
        await _emit(progress, "detect", 1, 1, "Layout detection complete.")

        # Phase 3: LLM OCR + DP alignment per page
        if self.client is None:
            log.warning("No LLM model configured — output will have empty text layer")
            return {p: [] for p in page_nums}

        sem = asyncio.Semaphore(max(1, concurrency))
        pages_text: dict[int, list[str]] = {}
        completed = 0

        async def process_page(p_num: int):
            async with sem:
                text = await self.client.perform_ocr_url(images_dict[p_num])
                await asyncio.sleep(2)  # cooldown between page requests
            if text:
                aligned = await asyncio.to_thread(
                    self.aligner.align, [b for b, _ in pages_data[p_num]], text
                )
            else:
                aligned = pages_data[p_num]
            return p_num, text.split("\n") if text else [], aligned

        await _emit(progress, "ocr", 0, total_pages, f"OCR (0/{total_pages})...")
        for coro in asyncio.as_completed([process_page(p) for p in page_nums]):
            p_num, llm_lines, aligned = await coro
            pages_text[p_num] = llm_lines
            pages_data[p_num] = aligned
            completed += 1
            await _emit(progress, "ocr", completed, total_pages, f"OCR ({completed}/{total_pages})")

        # Phase 4: Per-box crop re-OCR refine
        if refine:
            await refine_uncertain(
                pages_data, images_dict, self.client,
                concurrency=concurrency, progress_cb=progress,
            )

        # Phase 5: Embed text as sandwich PDF
        await _emit(progress, "embed", 0, 1, "Writing output...")
        _embed_sandwich_pdf(input_path, output_path, pages_data, dpi, images_dict)
        await _emit(progress, "embed", 1, 1, "Done.")

        return pages_text


def _rasterize_pages(path: str, dpi: int, max_dim: int) -> dict[int, str]:
    """Render PDF pages to data:image/png;base64,... URLs ready for LLM consumption."""
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        with Image.open(path) as src:
            img = src.convert("RGB").copy()
            img.thumbnail((max_dim, max_dim))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return {0: "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")}

    images: dict[int, str] = {}
    doc = fitz.open(path)
    try:
        for page_num, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img.thumbnail((max_dim, max_dim))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            images[page_num] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("utf-8")
    finally:
        doc.close()
    return images


def _embed_sandwich_pdf(
    input_path: str,
    output_path: str,
    pages_data: dict[int, list[tuple[list[float], str]]],
    dpi: int,
    images_dict: dict[int, str],
) -> None:
    """Build a searchable sandwich PDF: image background + invisible text overlay.

    Each Surya bbox gets one invisible text line with horizontal scaling so
    selection in a PDF viewer covers the full text width."""
    ext = Path(input_path).suffix.lower()
    is_image = ext in IMAGE_EXTENSIONS

    if is_image:
        src_img = Image.open(input_path)
        w_px, h_px = float(src_img.size[0]), float(src_img.size[1])
        doc = fitz.open()
        page = doc.new_page(width=w_px, height=h_px)
        buf = io.BytesIO()
        src_img.convert("RGB").save(buf, format="JPEG", quality=85)
        page.insert_image(page.rect, stream=buf.getvalue())
        _embed_page_text(page, pages_data.get(0, []), w_px, h_px)
        doc.save(output_path)
        doc.close()
        return

    src = fitz.open(input_path)
    dst = fitz.open()
    try:
        for page_num in range(len(src)):
            old = src[page_num]
            w = old.rect.width
            h = old.rect.height
            pix = old.get_pixmap(dpi=dpi)
            img_data = pix.tobytes("jpg", jpg_quality=80)
            new_page = dst.new_page(width=w, height=h)
            new_page.insert_image(new_page.rect, stream=img_data)
            _embed_page_text(new_page, pages_data.get(page_num, []), w, h)
        dst.save(output_path)
    finally:
        dst.close()
        src.close()


def _embed_page_text(
    page,
    page_data: list[tuple[list[float], str]],
    page_w: float,
    page_h: float,
) -> None:
    """Embed invisible text (render_mode=3) with horizontal-scale morph so
    selection covers the full width of each Surya bbox."""
    for box, text in page_data:
        text = (text or "").strip()
        if not text:
            continue

        nx0, ny0, nx1, ny1 = box
        x0 = nx0 * page_w
        y0 = ny0 * page_h
        x1 = nx1 * page_w
        y1 = ny1 * page_h

        box_w = x1 - x0
        box_h = y1 - y0
        if box_w <= 2 or box_h <= 2:
            continue

        font = fitz.Font("helv")
        ascender = getattr(font, "ascender", 1.075)
        descender = getattr(font, "descender", -0.299)
        extent_em = max(0.01, ascender - descender)
        fontsize = max(3.0, min(72.0, box_h / extent_em))

        # Multi-line text: split by newlines and place each sub-line
        if "\n" in text:
            sublines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if len(sublines) > 1:
                slice_h = box_h / len(sublines)
                for i, ln in enumerate(sublines):
                    _draw_one_line(page, x0, y0 + i * slice_h, x1, y0 + (i + 1) * slice_h, ln, font, fontsize)
                continue

        _draw_one_line(page, x0, y0, x1, y1, text, font, fontsize)


def _draw_one_line(page, x0, y0, x1, y1, text, font, fontsize):
    """Draw one invisible text line with horizontal scaling."""
    natural_w = font.text_length(text, fontsize=fontsize)
    if natural_w <= 0:
        return
    w = x1 - x0
    scale_x = max(0.3, min(5.0, w / natural_w * 0.98))
    desc = getattr(font, "descender", -0.299)
    baseline = fitz.Point(x0, y1 + desc * fontsize)
    morph = (baseline, fitz.Matrix(scale_x, 1.0))
    page.insert_text(
        baseline, text,
        fontsize=fontsize, fontname="helv",
        render_mode=3, color=(0, 0, 0),
        morph=morph,
    )


async def _emit(cb, stage, cur, tot, msg):
    if cb:
        await cb(stage, cur, tot, msg)
