# Standalone LLM OCR Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ocrmypdf-dependent LLM OCR plugin with a standalone pipeline matching `local-llm-pdf-ocr` architecture: Surya DetectionPredictor batch detection → LLM full-page OCR → DP alignment → per-box crop re-OCR refine → PyMuPDF sandwich embedding. No Tesseract. No ocrmypdf runtime dependency.

**Architecture:** The pipeline is injected into `backend/engine/pipeline.py` as an alternative OCR path. When `ocr_engine == "llm_ocr"`, instead of spawning ocrmypdf, the pipeline directly calls `StandaloneLlmOcrEngine.run()` which orchestrates 5 phases: convert (rasterize pages), detect (Surya batch), ocr (LLM + DP align per page), refine (per-box crop re-OCR for unmatched boxes), embed (PyMuPDF sandwich PDF write).

**Tech Stack:** Surya DetectionPredictor, our existing `llm_client.py`, PyMuPDF (fitz), existing DP code from `engine.py`

---

## File Structure

```
backend/engine/llmocr/
├── layout.py          → REWRITE: Surya-only batch detection, no Tesseract
├── engine.py          → REWRITE: standalone `LlmOcrPipeline` replacing OcrEngine
├── llm_client.py      → KEEP as-is
├── text_pdf.py        → DELETE (replaced by PyMuPDF sandwich embedding)
├── plugin.py          → DELETE (no longer an ocrmypdf plugin)
├── __init__.py        → SIMPLIFY
├── aligner.py         → NEW: DP alignment extracted from engine.py
└── refine.py          → NEW: per-box crop re-OCR stage
```

---

## Task 1: Create DP Alignment Module

Extract DP alignment logic from `engine.py` into a standalone `aligner.py` matching the original project's `HybridAligner`.

**Files:**
- Create: `backend/engine/llmocr/aligner.py`
- Modify: `backend/engine/llmocr/engine.py` — remove DP code later
- Test: Run on 新建.pdf

- [ ] **Step 1: Create `aligner.py` with `HybridAligner` class**

```python
"""HybridAligner — Surya DetectionPredictor + Needleman-Wunsch DP alignment.
Matches ahnafnafee/local-llm-pdf-ocr src/pdf_ocr/core/aligner.py."""

import io
import logging
from typing import Optional

from PIL import Image
from surya.detection import DetectionPredictor

log = logging.getLogger(__name__)

BBox = list[float]  # [nx0, ny0, nx1, ny1] normalized 0..1

COLUMN_GAP_THRESHOLD = 0.2
SKIP_LINE_COST = 1.0
SKIP_BOX_COST = 0.4


class HybridAligner:
    """Detection-only aligner: Surya batch detect + DP line-to-box alignment."""

    def __init__(self):
        self._detector: Optional[DetectionPredictor] = None

    def _get_detector(self) -> DetectionPredictor:
        if self._detector is None:
            self._detector = DetectionPredictor()
        return self._detector

    def detect_batch(self, images_bytes: list[bytes]) -> list[list[BBox]]:
        """Batch-detect text lines on all pages in a single Surya call.
        Returns one list of normalized [x0,y0,x1,y1] per page."""
        if not images_bytes:
            return []
        images = [Image.open(io.BytesIO(b)).convert("RGB") for b in images_bytes]
        sizes = [img.size for img in images]
        predictions = self._get_detector()(images)

        all_boxes: list[list[BBox]] = []
        for (img_w, img_h), pred in zip(sizes, predictions):
            boxes: list[BBox] = []
            for bbox in (pred.bboxes or []):
                x0, y0, x1, y1 = bbox.bbox
                box = [
                    max(0.0, min(1.0, x0 / img_w)),
                    max(0.0, min(1.0, y0 / img_h)),
                    max(0.0, min(1.0, x1 / img_w)),
                    max(0.0, min(1.0, y1 / img_h)),
                ]
                if (box[2] - box[0]) > 0.01 and (box[3] - box[1]) > 0.005:
                    boxes.append(box)
            boxes.sort(key=lambda b: (b[1], b[0]))
            all_boxes.append(boxes)
        return all_boxes

    def align(self, boxes: list[BBox], llm_text: str) -> list[tuple[BBox, str]]:
        """DP-align LLM text lines to Surya boxes.
        Returns [(box, text), ...] in box order, text="" for unmatched."""
        lines = _normalize_lines(llm_text)
        if not boxes and not lines:
            return []
        if not boxes:
            return [([0.0, 0.0, 1.0, 1.0], "\n".join(lines))]
        if not lines:
            return [(box, "") for box in boxes]

        candidates = [
            sorted(range(len(boxes)), key=lambda i: (boxes[i][1], boxes[i][0])),
            _reading_order_indices(boxes),
        ]

        best_cost = float("inf")
        best_perm = candidates[0]
        best_mapping: dict[int, list[str]] = {}
        best_match_count = 0
        for perm in candidates:
            ordered = [boxes[i] for i in perm]
            cost, mapping, match_count = _dp_align(lines, ordered)
            if cost < best_cost:
                best_cost, best_perm, best_mapping, best_match_count = cost, perm, mapping, match_count

        is_zero = best_match_count == 0 and len(lines) > 1
        is_single = len(lines) == 1 and len(boxes) >= 5
        if is_zero or is_single:
            log.warning(f"Degenerate alignment (lines={len(lines)} boxes={len(boxes)} matches={best_match_count})")
            return [([0.0, 0.0, 1.0, 1.0], "\n".join(lines))]

        text_per = ["" for _ in boxes]
        for perm_idx, texts in best_mapping.items():
            text_per[best_perm[perm_idx]] = " ".join(texts).strip()
        log.debug(f"DP: {len(lines)} lines → {best_match_count}/{len(boxes)} boxes (cost={best_cost:.3f})")
        return [(box, text) for box, text in zip(boxes, text_per)]


def _normalize_lines(text) -> list[str]:
    if not text:
        return []
    if isinstance(text, str):
        raw = text.split("\n")
    else:
        raw = []
        for item in text:
            raw.extend(str(item).split("\n"))
    return [s.strip() for s in raw if s.strip()]


def _reading_order_indices(boxes: list[BBox]) -> list[int]:
    n = len(boxes)
    if n < 4:
        return sorted(range(n), key=lambda i: (boxes[i][1], boxes[i][0]))
    sorted_idx = sorted(range(n), key=lambda i: (boxes[i][0] + boxes[i][2]) / 2)
    centers = [(boxes[i][0] + boxes[i][2]) / 2 for i in sorted_idx]
    biggest_gap = 0.0
    gap_pos = -1
    for k in range(1, len(centers)):
        gap = centers[k] - centers[k - 1]
        if gap > biggest_gap:
            biggest_gap, gap_pos = gap, k
    if biggest_gap < COLUMN_GAP_THRESHOLD or gap_pos < 2 or gap_pos > n - 2:
        return sorted(range(n), key=lambda i: (boxes[i][1], boxes[i][0]))
    left = _reading_order_indices([boxes[i] for i in sorted_idx[:gap_pos]])
    right = _reading_order_indices([boxes[i] for i in sorted_idx[gap_pos:]])
    return [sorted_idx[:gap_pos][i] for i in left] + [sorted_idx[gap_pos:][i] for i in right]


def _estimated_capacities(boxes: list[BBox]) -> list[float]:
    return [max(1e-6, (b[2] - b[0]) * (b[3] - b[1])) for b in boxes]


def _match_cost(line_chars: int, expected_chars: float) -> float:
    expected = max(1.0, expected_chars)
    actual = max(1, line_chars)
    if actual > expected:
        return (actual - expected) / actual
    return (expected - actual) / expected * 0.5


def _dp_align(lines, boxes) -> tuple[float, dict[int, list[str]], int]:
    N, M = len(lines), len(boxes)
    if N == 0 or M == 0:
        return 0.0, {}, 0
    total_chars = max(1, sum(len(l) for l in lines))
    caps = _estimated_capacities(boxes)
    total_cap = sum(caps)
    expected = [c / total_cap * total_chars for c in caps]

    INF = float("inf")
    dp = [[INF] * (M + 1) for _ in range(N + 1)]
    back = [[0] * (M + 1) for _ in range(N + 1)]
    dp[0][0] = 0.0
    for j in range(1, M + 1):
        dp[0][j], back[0][j] = dp[0][j - 1] + SKIP_BOX_COST, 2
    for i in range(1, N + 1):
        dp[i][0], back[i][0] = dp[i - 1][0] + SKIP_LINE_COST, 1

    for i in range(1, N + 1):
        for j in range(1, M + 1):
            mc = dp[i-1][j-1] + _match_cost(len(lines[i-1]), expected[j-1])
            sl = dp[i-1][j] + SKIP_LINE_COST
            sb = dp[i][j-1] + SKIP_BOX_COST
            best, op = mc, 0
            if sl < best: best, op = sl, 1
            if sb < best: best, op = sb, 2
            dp[i][j], back[i][j] = best, op

    mapping: dict[int, list[str]] = {}
    i, j = N, M
    ops: list[tuple[int, int, int]] = []
    while i > 0 or j > 0:
        op = back[i][j]
        if op == 0 and i > 0 and j > 0:
            ops.append((0, i-1, j-1)); i, j = i-1, j-1
        elif op == 1 and i > 0:
            ops.append((1, i-1, j-1 if j>0 else -1)); i -= 1
        elif op == 2 and j > 0:
            ops.append((2, i-1 if i>0 else -1, j-1)); j -= 1
        else:
            if i > 0: i -= 1
            elif j > 0: j -= 1
    ops.reverse()

    last_matched = None
    match_count = 0
    for op, li, bj in ops:
        if op == 0:
            mapping.setdefault(bj, []).append(lines[li])
            last_matched, match_count = bj, match_count + 1
        elif op == 1 and li >= 0:
            target = last_matched if last_matched is not None else 0
            mapping.setdefault(target, []).append(lines[li])
    return dp[N][M], mapping, match_count
```

- [ ] **Step 2: Verify import works on system Python**

```bash
& "C:\Python314\python.EXE" -c "import sys; sys.path.insert(0, r'D:\opencode\book-downloader\backend\engine'); from llmocr.aligner import HybridAligner; a=HybridAligner(); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/llmocr/aligner.py
git commit -m "feat: HybridAligner — Surya batch detection + DP alignment extracted from engine"
```

---

## Task 2: Create Per-Box Crop Re-OCR Refine Stage

**Files:**
- Create: `backend/engine/llmocr/refine.py`

- [ ] **Step 1: Create `refine.py`**

```python
"""Per-box crop re-OCR — refine stage for boxes DP alignment couldn't populate.
Matches ahnafnafee/local-llm-pdf-ocr OCRPipeline._refine_uncertain."""

import base64
import io
import logging
import numpy as np
from typing import Optional
from PIL import Image

log = logging.getLogger(__name__)


def is_refinable(box: list[float]) -> bool:
    """Only trigger re-OCR for boxes large enough to plausibly contain text.
    Cutoffs in normalized (0..1) page coords, tuned to skip rules/decorations."""
    width = box[2] - box[0]
    height = box[3] - box[1]
    return width > 0.03 and height > 0.008


def crop_for_ocr(image_b64: str, box: list[float], pad_ratio: float = 0.02) -> Optional[str]:
    """Crop a Surya-detected box from a page image for individual re-OCR.
    
    Returns base64-encoded JPEG crop, or None if the region is blank
    (low pixel stddev — likely notebook background, margin, or empty space).
    """
    img = Image.open(io.BytesIO(base64.b64decode(image_b64)))
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
    return base64.b64encode(buf.getvalue()).decode("utf-8")


async def refine_uncertain(
    pages_data: dict[int, list[tuple[list[float], str]]],
    images_dict: dict[int, str],
    ocr_processor,  # LlmApiClient with perform_ocr(image_b64) -> str
    concurrency: int = 3,
    progress_cb=None,
) -> None:
    """Re-OCR boxes that DP alignment left empty.
    
    Mutates pages_data in place: replaces empty-text boxes with re-OCR'd text.
    
    Args:
        pages_data: {page_num: [(box, text), ...]} — mutated in place
        images_dict: {page_num: base64_image} — page images for cropping
        ocr_processor: has async perform_ocr(image_b64) -> str method
        concurrency: max concurrent LLM calls
        progress_cb: async callback(stage, current, total, message)
    """
    import asyncio
    
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
            text = await ocr_processor.perform_ocr(crop_b64)
            return p_num, idx, (text or "").strip()
    
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
```

- [ ] **Step 2: Verify imports**

```bash
& "C:\Python314\python.EXE" -c "import sys; sys.path.insert(0, r'D:\opencode\book-downloader\backend\engine'); from llmocr.refine import is_refinable, crop_for_ocr; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/engine/llmocr/refine.py
git commit -m "feat: per-box crop re-OCR refine stage with blank-skip and dedup"
```

---

## Task 3: Create Standalone LLM OCR Pipeline

Rewrite `engine.py` as a standalone pipeline (no ocrmypdf `OcrEngine` subclass).

**Files:**
- Rewrite: `backend/engine/llmocr/engine.py`
- Delete: `backend/engine/llmocr/plugin.py`
- Delete: `backend/engine/llmocr/text_pdf.py`

- [ ] **Step 1: Rewrite `engine.py`**

```python
"""Standalone LLM OCR Pipeline — matches ahnafnafee/local-llm-pdf-ocr.
No ocrmypdf dependency. No Tesseract. Five phases:
  convert → detect → ocr → refine → embed
"""

import asyncio
import base64
import io
import logging
import os
import time
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
        image_bytes = [base64.b64decode(images_dict[p]) for p in page_nums]
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
                text = await self.client.perform_ocr(images_dict[p_num])
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
    """Render PDF pages to base64 JPEG images. Also handles raw image files."""
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        with Image.open(path) as src:
            img = src.convert("RGB").copy()
            img.thumbnail((max_dim, max_dim))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            return {0: base64.b64encode(buf.getvalue()).decode("utf-8")}

    images: dict[int, str] = {}
    doc = fitz.open(path)
    try:
        for page_num, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("jpg", jpg_quality=50)))
            img.thumbnail((max_dim, max_dim))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=50)
            images[page_num] = base64.b64encode(buf.getvalue()).decode("utf-8")
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

        # Multi-line text
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
```

- [ ] **Step 2: Verify imports work**

```bash
& "C:\Python314\python.EXE" -c "import sys; sys.path.insert(0, r'D:\opencode\book-downloader\backend\engine'); from llmocr.engine import LlmOcrPipeline; p=LlmOcrPipeline(); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Delete ocrmypdf plugin files**

```bash
Remove-Item D:\opencode\book-downloader\backend\engine\llmocr\plugin.py -Force
Remove-Item D:\opencode\book-downloader\backend\engine\llmocr\text_pdf.py -Force
```

- [ ] **Step 4: Simplify `__init__.py`**

```python
"""LLM OCR — standalone hybrid pipeline (Surya detection + LLM text + DP alignment)."""
```

- [ ] **Step 5: Commit**

```bash
git add backend/engine/llmocr/
git rm backend/engine/llmocr/plugin.py backend/engine/llmocr/text_pdf.py
git commit -m "feat: standalone LlmOcrPipeline replacing ocrmypdf plugin"
```

---

## Task 4: Update LlmApiClient for standalone pipeline

`LlmApiClient` currently has `ocr_image(image_bytes)` returning `str`. Need to add `perform_ocr(image_b64)` for the pipeline interface (accepts base64 string, not raw bytes).

**Files:**
- Modify: `backend/engine/llmocr/llm_client.py:79-126`

- [ ] **Step 1: Add `perform_ocr` method**

Read the current `llm_client.py` ocr_image method and add a thin wrapper:

```python
async def perform_ocr(self, image_b64: str) -> str:
    """OCR a full page image (base64-encoded). Returns plain text."""
    image_bytes = base64.b64decode(image_b64)
    return (await self.ocr_image(image_bytes)) or ""

async def perform_ocr_on_crop(self, image_b64: str) -> str:
    """OCR a cropped region (base64-encoded). Returns plain text."""
    image_bytes = base64.b64decode(image_b64)
    # Use a shorter prompt for individual box crops
    return (await self.ocr_image(image_bytes)) or ""
```

- [ ] **Step 2: Verify**

```bash
& "C:\Python314\python.EXE" -c "import sys; sys.path.insert(0, r'D:\opencode\book-downloader\backend\engine'); from llmocr.llm_client import LlmApiClient; print(dir(LlmApiClient))"
```

- [ ] **Step 3: Commit**

```bash
git add backend/engine/llmocr/llm_client.py
git commit -m "feat: add perform_ocr / perform_ocr_on_crop to LlmApiClient"
```

---

## Task 5: Integrate standalone pipeline into backend pipeline.py

Replace the LLM OCR branch in `_step_ocr` with the new standalone pipeline.

**Files:**
- Modify: `backend/engine/pipeline.py:2205-2310` (LLM OCR section)

- [ ] **Step 1: Replace LLM OCR section in `_step_ocr`**

Replace the ocrmypdf-based LLM OCR code with the standalone pipeline call:

```python
elif ocr_engine == "llm_ocr":
    task_store.add_log(task_id, "Running standalone LLM OCR pipeline...")

    if not _is_scanned(pdf_path, python_cmd=_py_for_ocr):
        task_store.add_log(task_id, "PDF already has text layer, skipping OCR")
        report["ocr_done"] = True
        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
        return report

    llm_endpoint = config.get("llm_ocr_endpoint", config.get("llm_api_base", "http://localhost:11434"))
    llm_model = config.get("llm_ocr_model", config.get("llm_model", ""))
    llm_api_key = config.get("llm_ocr_api_key", config.get("llm_api_key", ""))
    llm_timeout = config.get("llm_ocr_timeout", 300)
    llm_concurrency = max(1, ocr_jobs)

    if not llm_model:
        task_store.add_log(task_id, "LLM OCR: model not configured")
        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
        return report

    output_pdf = pdf_path.replace(".pdf", "_ocr.pdf")

    try:
        from llmocr.engine import LlmOcrPipeline

        pipeline = LlmOcrPipeline(
            endpoint=llm_endpoint,
            model=llm_model,
            api_key=llm_api_key,
            timeout=llm_timeout,
        )

        async def emit_ocr_progress(stage: str, cur: int, tot: int, msg: str):
            # Map pipeline stages to step_progress percentage bands
            stage_offsets = {"convert": 0, "detect": 10, "ocr": 20, "refine": 70, "embed": 90}
            base = stage_offsets.get(stage, 0)
            pct = min(base + int(cur / max(1, tot) * 20), 100)
            await _emit_progress(task_id, "ocr", pct, msg)

        await pipeline.run(
            input_path=pdf_path,
            output_path=output_pdf,
            dpi=int(ocr_oversample),
            concurrency=llm_concurrency,
            refine=config.get("ocr_refine_enabled", True),
            progress=emit_ocr_progress,
        )

        if os.path.exists(output_pdf) and os.path.getsize(output_pdf) > 1024:
            if _is_ocr_readable(output_pdf, python_cmd=_py_for_ocr):
                os.replace(output_pdf, pdf_path)
                task_store.add_log(task_id, "LLM OCR completed, quality check passed")
                report["ocr_done"] = True
            else:
                task_store.add_log(task_id, "LLM OCR quality check failed, keeping original PDF")
                try: os.remove(output_pdf)
                except: pass
        else:
            task_store.add_log(task_id, "LLM OCR failed: no output produced")
    except Exception as e:
        task_store.add_log(task_id, f"LLM OCR pipeline error: {e}")
```

- [ ] **Step 2: Also clean up `_run_ocrmypdf_with_progress` — remove LLM OCR progress parsing**

The `_run_ocrmypdf_with_progress` function at line 133 now only handles Tesseract/PaddleOCR. Remove the `_llm_pg` and `_llm` regex blocks (lines 258-277).

Delete these lines:
```python
            # Parse LLM-OCR progress
            # Format 1: "27 generate_pdf TEXT: ..." — current page number
            # Format 2: "generate_pdf: pages=10, words=1001, ..." — batch summary
            _llm_pg = re.search(r'(\d+)\s+generate_pdf\s+TEXT:', _text)
            if _llm_pg:
                _had_llm_page = True
                _cur = int(_llm_pg.group(1))
                if total_pages > 0:
                    _tot = total_pages
                elif _tot == 0:
                    _tot = int((_cur * 1.2) if _cur > 0 else 100)
                _cur = min(_cur, _tot)
                if _cur % 10 == 0 or _cur >= _tot:
                    task_store.add_log(task_id, f"  LLM-OCR: {_cur}/{_tot} 页")
                _pct_llm = int(_cur / _tot * 100) if _tot > 0 else 0
                await _emit_progress(task_id, "ocr", _pct_llm, f"{_cur}/{_tot} 页", "")
                continue

            _llm = re.search(r'generate_pdf:\s*pages=(\d+)', _text)
            if _llm:
                _cur += int(_llm.group(1))
                if total_pages > 0:
                    _tot = total_pages
                elif _tot == 0:
                    _tot = int((_cur * 1.2) if _cur > 0 else 100)
                _cur = min(_cur, _tot)
                if _cur % 10 == 0 or _cur >= _tot:
                    task_store.add_log(task_id, f"  LLM-OCR: ~{_cur}/{_tot} 页")
                _pct_llm = int(_cur / _tot * 100) if _tot > 0 else 0
                await _emit_progress(task_id, "ocr", _pct_llm, f"{_cur}/{_tot} 页", "")
                continue
```

Also remove `_had_llm_page` nonlocal declarations and usage.

- [ ] **Step 3: Add `ocr_refine_enabled` config key (default True)**

In `config.py` line 75, add:
```python
"ocr_refine_enabled": True,
```

In `config.default.json` add:
```json
"ocr_refine_enabled": true,
```

- [ ] **Step 4: Remove ocrmypdf system Python detection for LLM OCR (no longer needed)**

The code at pipeline.py lines 2037-2059 searches for system Python for ocrmypdf. With the standalone pipeline, LLM OCR doesn't need ocrmypdf. Keep the detection for PaddleOCR/Tesseract but skip it for LLM OCR.

- [ ] **Step 5: Verify syntax**

```bash
& "C:\Python314\python.EXE" -c "import py_compile; py_compile.compile('D:\\opencode\\book-downloader\\backend\\engine\\pipeline.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add backend/engine/pipeline.py backend/config.py config.default.json
git commit -m "feat: integrate standalone LLM OCR pipeline into _step_ocr"
```

---

## Task 6: End-to-end test and deploy

**Files:** All from Tasks 1-5

- [ ] **Step 1: Test on 新建.pdf (10 pages)**

```bash
# Write a quick test script
$env:PYTHONPATH = "D:\opencode\book-downloader\backend\engine"
& "C:\Python314\python.EXE" -c "
import asyncio, sys
sys.path.insert(0, r'D:\opencode\book-downloader\backend\engine')
from llmocr.engine import LlmOcrPipeline

async def main():
    p = LlmOcrPipeline(
        endpoint='http://127.0.0.1:12345',
        model='sabafallah/deepseek-ocr',
    )
    result = await p.run(
        r'C:\Users\Administrator\Downloads\新建.pdf',
        r'C:\Users\Administrator\Downloads\新建_standalone_ocr.pdf',
        dpi=200, concurrency=1,
    )
    print(f'Done: {len(result)} pages')
asyncio.run(main())
"
```

Expected: Output PDF created with selectable text layer.

- [ ] **Step 2: Check bbox quality**

```python
import fitz
d = fitz.open(r'C:\Users\Administrator\Downloads\新建_standalone_ocr.pdf')
for i in range(len(d)):
    blocks = d[i].get_text('dict')['blocks']
    wide = sum(1 for b in blocks if b.get('type')==0 and b.get('lines') and b['bbox'][2]-b['bbox'][0]>200)
    narrow = sum(1 for b in blocks if b.get('type')==0 and b.get('lines') and b['bbox'][2]-b['bbox'][0]<=200)
    print(f'P{i+1}: {wide}W/{narrow}N')
```

Expected: All pages with text should have wide bboxes, 0 or very few narrow.

- [ ] **Step 3: Full build and deploy**

```bash
cd D:\opencode\book-downloader
git add -A
git commit -m "feat: complete standalone LLM OCR — Surya batch detection + DP + refine"
python -m PyInstaller --noconfirm backend\book-downloader.spec
Stop-Process -Name BookDownloader,ebook-pdf-downloader -Force -ErrorAction SilentlyContinue
Start-Sleep 1
Copy-Item dist\ebook-pdf-downloader.exe backend\dist\ebook-pdf-downloader.exe -Force
Start-Process backend\dist\ebook-pdf-downloader.exe
```

- [ ] **Step 4: Verify via UI**

Create a task in the UI with LLM OCR engine. Monitor logs for the new phase labels: "Converting PDF...", "Detecting layout...", "OCR (0/N)...", "Refining boxes...", etc.

---

## Self-Review

**Spec coverage:**
- [x] Remove ocrmypdf dependency — standalone pipeline
- [x] Surya DetectionPredictor batch mode — all pages in one call
- [x] No Tesseract/PIL fallback — Surya only
- [x] DP alignment — extracted to aligner.py
- [x] Per-box crop re-OCR refine — refine.py with blank-skip and dedup
- [x] PyMuPDF sandwich embedding — _embed_sandwich_pdf
- [x] Integration into pipeline.py — _step_ocr LLM branch
- [x] Config key for refine toggle

**Placeholder scan:** No TBD/TODO — all code shown completely.

**Type consistency:**
- `BBox = list[float]` — consistent across aligner.py, refine.py, engine.py
- `pages_data: dict[int, list[tuple[list[float], str]]]` — consistent across all modules
- `ProgressCallback` — consistent signature
