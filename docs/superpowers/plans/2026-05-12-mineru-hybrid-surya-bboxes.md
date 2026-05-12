# MinerU Hybrid: Surya Bboxes + MinerU OCR Text — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Combine Surya's precise per-line bboxes with MinerU API's high-quality OCR text, replacing the current block-level bbox approach that cannot match visual line positions.

**Architecture:** Pipeline calls three discrete steps: (1) `uv run` subprocess for Surya detection → normalized bboxes per page, (2) MinerU API for full-document OCR text (already working), (3) sequential pairing of Surya bboxes with MinerU text items in reading order, embedded using LLM OCR pipeline's `_draw_invisible_text` (tight bboxes + `insert_text` + morph scaling). No DP alignment needed — both data sources are in stable reading order.

**Tech Stack:** PyMuPDF (rasterization), Surya via local-llm-pdf-ocr subprocess, httpx for MinerU API, fitz for PDF text embedding.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `local-llm-pdf-ocr/scripts/detect_boxes.py` | **Create** | Surya detection-only script: PDF → images → bboxes → JSON stdout |
| `backend/engine/surya_detect.py` | **Create** | Wrapper: calls `uv run scripts/detect_boxes.py` subprocess, parses JSON |
| `backend/engine/pipeline.py` | Modify | Rewrite mineru branch: Surya bboxes + MinerU text → pair → embed |
| `backend/engine/pdf_api_embed.py` | Modify | Add `embed_with_surya_boxes()` — per-line `insert_text` + morph for tight Surya bboxes |
| `tests/test_surya_detect.py` | **Create** | Unit tests for subprocess wrapper |
| `tests/test_surya_embed.py` | **Create** | Unit tests for Surya-style embedding |

---

### Task 1: Surya Detection Script

**Files:**
- Create: `local-llm-pdf-ocr/scripts/detect_boxes.py`

- [ ] **Step 1: Write the detection script**

```python
# local-llm-pdf-ocr/scripts/detect_boxes.py
"""CLI: run Surya detection on a PDF, output per-page normalized bboxes as JSON to stdout.

Usage:
    uv run scripts/detect_boxes.py input.pdf [--dpi 200] [--pages 1-5] [--detect-batch-size 20]

Output (stdout):
    {
        "pages": [
            {"page": 0, "width": 595.0, "height": 842.0, "boxes": [[x0,y0,x1,y1], ...]},
            ...
        ]
    }
"""
import argparse
import io
import json
import os
import sys

from PIL import Image

os.environ.setdefault("TQDM_DISABLE", "1")


def main():
    parser = argparse.ArgumentParser(description="Surya detection only — output bbox JSON")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("--dpi", type=int, default=200, help="DPI for rendering (default: 200)")
    parser.add_argument("--pages", type=str, default=None, help="Page range e.g. 1-3,5")
    parser.add_argument("--detect-batch-size", type=int, default=20, help="Pages per batch")
    args = parser.parse_args()

    import fitz
    from pdf_ocr.core.aligner import HybridAligner
    from pdf_ocr.core.pdf import PDFHandler

    doc = fitz.open(args.input)
    total_pages = len(doc)
    pages_arg = args.pages

    # Resolve page range
    if pages_arg:
        indices = set()
        for part in pages_arg.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                a = int(a.strip()) - 1
                b = int(b.strip()) - 1
                indices.update(range(max(0, a), min(total_pages, b + 1)))
            else:
                i = int(part.strip()) - 1
                if 0 <= i < total_pages:
                    indices.add(i)
        page_indices = sorted(indices)
    else:
        page_indices = list(range(total_pages))

    ph = PDFHandler()
    page_images: dict[int, bytes] = {}
    page_sizes: dict[int, tuple] = {}

    for pg in page_indices:
        page = doc[pg]
        pix = page.get_pixmap(dpi=args.dpi)
        img_data = pix.tobytes("png")
        page_images[pg] = img_data
        page_sizes[pg] = (page.rect.width, page.rect.height)

    doc.close()

    # Run Surya detection
    aligner = HybridAligner()
    image_bytes_list = [page_images[pg] for pg in page_indices]

    batch_size = args.detect_batch_size
    all_boxes: dict[int, list] = {}

    for batch_start in range(0, len(image_bytes_list), batch_size):
        batch_end = min(batch_start + batch_size, len(image_bytes_list))
        batch_images = image_bytes_list[batch_start:batch_end]
        batch_pages = page_indices[batch_start:batch_end]

        results = aligner.get_detected_boxes_batch(batch_images)
        for pg, boxes in zip(batch_pages, results):
            all_boxes[pg] = [list(b) for b in boxes] if boxes else []

    # Build output
    output = {"pages": []}
    for pg in sorted(all_boxes.keys()):
        pw, ph = page_sizes[pg]
        output["pages"].append({
            "page": pg,
            "width": pw,
            "height": ph,
            "boxes": all_boxes[pg],
        })

    json.dump(output, sys.stdout, ensure_ascii=False)
    print()  # trailing newline


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test detection script manually**

```bash
cd D:\opencode\book-downloader\local-llm-pdf-ocr
uv run scripts/detect_boxes.py "C:\Users\Administrator\Downloads\新建.pdf" --pages 0-1 --dpi 200 2>&1 | Select-Object -First 30
```

Expected: JSON output with `"pages"` array containing bbox arrays for pages 0 and 1.

- [ ] **Step 3: Commit**

```bash
cd D:\opencode\book-downloader\local-llm-pdf-ocr
git add scripts/detect_boxes.py
git commit -m "feat: add Surya detection-only script (outputs normalized bbox JSON)"
```

---

### Task 2: Surya Detection Wrapper (Backend Subprocess)

**Files:**
- Create: `backend/engine/surya_detect.py`
- Test: `tests/test_surya_detect.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_surya_detect.py
import json
import pytest
from unittest.mock import patch, AsyncMock

from backend.engine.surya_detect import (
    run_surya_detect,
    SuryaDetectError,
    parse_detect_output,
)

def test_parse_detect_output():
    """Parse valid JSON output from detection script."""
    raw = json.dumps({
        "pages": [
            {"page": 0, "width": 595.0, "height": 842.0, "boxes": [[0.1, 0.2, 0.9, 0.25], [0.1, 0.3, 0.9, 0.35]]},
            {"page": 1, "width": 612.0, "height": 792.0, "boxes": [[0.05, 0.1, 0.95, 0.15]]},
        ]
    }) + "\n"

    result = parse_detect_output(raw)
    assert 0 in result
    assert 1 in result
    assert len(result[0]) == 2
    assert result[0][0] == [0.1, 0.2, 0.9, 0.25]
    assert len(result[1]) == 1

def test_parse_detect_output_empty_page():
    raw = json.dumps({
        "pages": [{"page": 0, "width": 595.0, "height": 842.0, "boxes": []}]
    }) + "\n"

    result = parse_detect_output(raw)
    assert 0 in result
    assert result[0] == []

def test_parse_detect_output_invalid_json():
    with pytest.raises(SuryaDetectError):
        parse_detect_output("not json")

@pytest.mark.asyncio
async def test_run_surya_detect_mock():
    """Test subprocess wrapper with mocked subprocess."""
    mock_output = json.dumps({
        "pages": [{"page": 0, "width": 595.0, "height": 842.0, "boxes": [[0.1, 0.2, 0.9, 0.25]]}]
    }) + "\n"

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.stdout.read = AsyncMock(return_value=mock_output.encode())

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await run_surya_detect("test.pdf", dpi=200, pages=None)

    assert 0 in result
    assert result[0] == [[0.1, 0.2, 0.9, 0.25]]

@pytest.mark.asyncio
async def test_run_surya_detect_process_failure():
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.stderr.read = AsyncMock(return_value=b"error message")

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(SuryaDetectError, match="exit code 1"):
            await run_surya_detect("test.pdf")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_surya_detect.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write implementation**

```python
# backend/engine/surya_detect.py
"""Wrapper for calling local-llm-pdf-ocr's Surya detection script as subprocess."""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional


class SuryaDetectError(Exception):
    pass


def _find_uv() -> Optional[str]:
    uv = shutil.which("uv") or shutil.which("uv.exe")
    if not uv:
        candidate = os.path.expanduser(r"~\.local\bin\uv.exe")
        if os.path.exists(candidate):
            uv = candidate
    return uv


def _find_project_root() -> Optional[str]:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        path = str(base / "local-llm-pdf-ocr")
    else:
        base = Path(__file__).resolve().parent.parent.parent
        path = str(base / "local-llm-pdf-ocr")
    return path if os.path.isdir(path) else None


async def run_surya_detect(
    pdf_path: str,
    dpi: int = 200,
    pages: Optional[str] = None,
    detect_batch_size: int = 20,
) -> Dict[int, List[List[float]]]:
    """Run Surya detection on a PDF, return {page_idx: [[x0,y0,x1,y1], ...]} with normalized coords."""

    uv_bin = _find_uv()
    project_root = _find_project_root()

    if not uv_bin or not project_root:
        raise SuryaDetectError(
            f"Surya detection requires uv + local-llm-pdf-ocr. uv={'found' if uv_bin else 'missing'}, project={'found' if project_root else 'missing'}"
        )

    script = os.path.join(project_root, "scripts", "detect_boxes.py")
    if not os.path.exists(script):
        raise SuryaDetectError(f"detect_boxes.py not found at {script}")

    cmd = [uv_bin, "run", "--directory", project_root, script, pdf_path, "--dpi", str(dpi)]
    if pages:
        cmd.extend(["--pages", pages])
    cmd.extend(["--detect-batch-size", str(detect_batch_size)])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise SuryaDetectError(
            f"Surya detection failed with exit code {proc.returncode}: {stderr.decode('utf-8', errors='replace')[:500]}"
        )

    return parse_detect_output(stdout.decode("utf-8", errors="replace"))


def parse_detect_output(raw: str) -> Dict[int, List[List[float]]]:
    """Parse JSON output from detect_boxes.py."""
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        raise SuryaDetectError(f"Invalid JSON from detection script: {e}") from e

    pages = data.get("pages", [])
    result: Dict[int, List[List[float]]] = {}
    for page in pages:
        pg = page["page"]
        result[pg] = page.get("boxes", [])
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_surya_detect.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add backend/engine/surya_detect.py tests/test_surya_detect.py
git commit -m "feat: add Surya detection subprocess wrapper"
```

---

### Task 3: Tight-Bbox Embed (for Surya Boxes)

**Files:**
- Modify: `backend/engine/pdf_api_embed.py` — add new function

- [ ] **Step 1: Add `embed_with_surya_boxes` function**

```python
def embed_with_surya_boxes(
    input_path: str,
    output_path: str,
    surya_boxes: Dict[int, List[List[float]]],
    page_texts: Dict[int, List[str]],
) -> None:
    """Embed text at Surya's precise line-level bbox positions.

    Surya bboxes are tight around individual text lines, so insert_text + morph
    scaling works correctly (unlike MinerU's block-level bboxes).

    Args:
        input_path: Source PDF path
        output_path: Output PDF path with text layer
        surya_boxes: {page_idx: [[x0,y0,x1,y1], ...]} — Surya normalized bboxes
        page_texts: {page_idx: ["line1 text", "line2 text", ...]} — text per line
    """
    import fitz
    from pathlib import Path

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

        # Pair boxes with texts (both in reading order)
        font = fitz.Font(fontfile=_SIMSUN_PATH) if has_sim else fitz.Font("helv")
        fontname = "F1" if has_sim else "helv"

        for bbox, text in zip(boxes, texts):
            text = text.strip()
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

            # LLM OCR pipeline's font sizing + morph scaling
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
```

- [ ] **Step 2: Write test**

```python
# tests/test_surya_embed.py
import io
import os
import pytest
import fitz

from backend.engine.pdf_api_embed import embed_with_surya_boxes


@pytest.fixture
def blank_pdf():
    buf = io.BytesIO()
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def test_embed_surya_boxes_creates_output(tmp_path, blank_pdf):
    input_path = str(tmp_path / "input.pdf")
    output_path = str(tmp_path / "output.pdf")
    with open(input_path, "wb") as f:
        f.write(blank_pdf)

    surya_boxes = {0: [[0.1, 0.2, 0.9, 0.25], [0.1, 0.3, 0.9, 0.35]]}
    page_texts = {0: ["Hello World", "Chapter One"]}

    embed_with_surya_boxes(input_path, output_path, surya_boxes, page_texts)

    assert os.path.exists(output_path)
    doc = fitz.open(output_path)
    assert len(doc) == 1
    doc.close()


def test_embed_surya_boxes_extra_boxes_ok(tmp_path, blank_pdf):
    input_path = str(tmp_path / "input.pdf")
    output_path = str(tmp_path / "output.pdf")
    with open(input_path, "wb") as f:
        f.write(blank_pdf)

    # More boxes than texts — extra boxes ignored
    surya_boxes = {0: [[0.1, 0.2, 0.9, 0.25], [0.1, 0.3, 0.9, 0.35], [0.1, 0.4, 0.9, 0.45]]}
    page_texts = {0: ["Line 1"]}

    embed_with_surya_boxes(input_path, output_path, surya_boxes, page_texts)
    assert os.path.exists(output_path)
```

Run: `pytest tests/test_surya_embed.py -v`

- [ ] **Step 3: Commit**

```bash
git add backend/engine/pdf_api_embed.py tests/test_surya_embed.py
git commit -m "feat: add embed_with_surya_boxes for tight per-line bbox positioning"
```

---

### Task 4: Pipeline Integration — Surya + MinerU Hybrid

**Files:**
- Modify: `backend/engine/pipeline.py` — rewrite mineru branch

- [ ] **Step 1: Rewrite mineru branch**

Replace the mineru branch in `_step_ocr()` (around line 2551) with:

```python
        elif ocr_engine == "mineru":
            mineru_token = config.get("mineru_token", "")
            if not mineru_token:
                task_store.add_log(task_id, "MinerU: no token configured, skipping")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            mineru_model = config.get("mineru_model", "vlm")
            task_store.add_log(task_id, f"MinerU OCR (hybrid): Surya detection + MinerU API (model={mineru_model})")
            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 5, "detail": "Running Surya detection..."})

            try:
                from backend.engine.surya_detect import run_surya_detect
                from backend.engine.mineru_client import MinerUClient, parse_layout_from_zip
                from backend.engine.pdf_api_embed import embed_with_surya_boxes

                # Step 1: Surya detection (subprocess via local-llm-pdf-ocr)
                task_store.add_log(task_id, "MinerU: running Surya detection...")
                surya_boxes = await run_surya_detect(pdf_path, dpi=200)
                total_boxes = sum(len(v) for v in surya_boxes.values())
                task_store.add_log(task_id, f"MinerU: Surya detected {total_boxes} boxes across {len(surya_boxes)} pages")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 20, "detail": f"Surya: {total_boxes} boxes"})

                # Step 2: MinerU API for text content
                task_store.add_log(task_id, "MinerU: calling API for text content...")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 25, "detail": "MinerU API OCR..."})

                client = MinerUClient(token=mineru_token)
                try:
                    with open(pdf_path, "rb") as f:
                        pdf_bytes = f.read()
                    zip_bytes = await client.process_pdf(
                        pdf_bytes, file_name=os.path.basename(pdf_path),
                        model_version=mineru_model,
                    )
                    task_store.add_log(task_id, f"MinerU: API returned {len(zip_bytes)} bytes")

                    # Parse text from content_list.json
                    all_pages_text = parse_layout_from_zip(zip_bytes)
                finally:
                    await client.close()

                # Step 3: Pair Surya boxes with MinerU text by page
                page_texts = {}
                for pg in sorted(surya_boxes.keys()):
                    boxes = surya_boxes[pg]
                    mineru_items = all_pages_text.get(pg, [])
                    mineru_texts = [item["text"].strip() for item in mineru_items if item.get("text", "").strip()]

                    # Both are in reading order — just pair sequentially
                    paired = []
                    for i, bbox in enumerate(boxes):
                        if i < len(mineru_texts):
                            paired.append(mineru_texts[i])
                        else:
                            paired.append("")  # unmatched box

                    page_texts[pg] = paired
                    matched = sum(1 for t in paired if t)
                    task_store.add_log(task_id, f"MinerU: page {pg} — {matched}/{len(boxes)} boxes matched")

                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 90, "detail": "Embedding text layer..."})

                # Step 4: Embed
                output_pdf = pdf_path + ".mineru.pdf"
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    embed_with_surya_boxes,
                    pdf_path, output_pdf, surya_boxes, page_texts,
                )

                if os.path.exists(output_pdf) and os.path.getsize(output_pdf) > 0:
                    os.replace(output_pdf, pdf_path)
                    report["ocr_done"] = True
                    task_store.add_log(task_id, "MinerU OCR complete (hybrid: Surya boxes + MinerU text)")
                else:
                    raise RuntimeError("MinerU: embedding produced empty file")

            except asyncio.TimeoutError:
                task_store.add_log(task_id, "MinerU OCR timed out")
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                last_lines = "\n".join(tb.split(chr(10))[-5:])
                task_store.add_log(task_id, f"MinerU OCR error: {e} | {last_lines}"[:500])
```

- [ ] **Step 2: Keep existing embed_api_text_layer as fallback**

The existing `embed_api_text_layer` function (insert_textbox approach) should be kept for PaddleOCR-VL-1.5 and as a fallback. Add `embed_with_surya_boxes` as an additional export in `__init__.py`.

- [ ] **Step 3: Verify imports**

Run: `python -c "from backend.engine.surya_detect import run_surya_detect; from backend.engine.pdf_api_embed import embed_with_surya_boxes; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add backend/engine/pipeline.py backend/engine/__init__.py
git commit -m "feat: integrate Surya bbox detection + MinerU API text in hybrid pipeline"
```

---

### Task 5: End-to-End Verification

- [ ] **Step 1: Verify Surya detection works standalone**

```bash
cd D:\opencode\book-downloader
# Start engine, test detection on a PDF
```

- [ ] **Step 2: Run full end-to-end with 新建.pdf**

Set mineru engine, run task, verify:
1. "Surya detected X boxes across Y pages" appears in log
2. "MinerU API returned N bytes" appears
3. "MinerU OCR complete (hybrid)" appears
4. Output PDF has searchable text layer with correct per-line positioning

- [ ] **Step 3: Clean up and final commit**

```bash
git add -A
git commit -m "chore: final cleanup and verification for mineru hybrid pipeline"
```

---

## Self-Review

1. **Spec coverage**: All 5 tasks cover detect script → wrapper → embed → pipeline → verification
2. **No placeholders**: All code blocks are complete, testable implementations
3. **Type consistency**: `surya_boxes: Dict[int, List[List[float]]]` used consistently across Tasks 2, 3, 4; `page_texts: Dict[int, List[str]]` same
