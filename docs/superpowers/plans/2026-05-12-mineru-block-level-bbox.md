# MinerU Block-Level Bbox + Surya Chinese Debug

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MinerU pipeline use its own reliable block-level bboxes (skip broken Surya hybrid), and create debug tooling to diagnose Surya Chinese detection quality.

**Architecture:** Two independent changes: (A) `pipeline.py` MinerU path skips Surya detection entirely, always uses MinerU API `_model.json` bboxes + `embed_api_text_layer()`. (B) New `scripts/visualize_surya.py` renders Surya bboxes overlaid on page images for visual inspection, plus threshold parameter plumbing.

**Tech Stack:** Python 3.12, PyMuPDF (fitz), Surya, Pillow

---

## File Structure

| File | Role |
|---|---|
| `backend/engine/pipeline.py:2553-2661` | MinerU OCR pipeline — will simplify to skip Surya |
| `backend/engine/surya_detect.py` | Surya subprocess wrapper — add threshold/DPI params |
| `local-llm-pdf-ocr/scripts/detect_boxes.py` | Surya detection CLI — add threshold/DPI args |
| `local-llm-pdf-ocr/scripts/visualize_surya.py` | NEW: render detected bboxes on page images |
| `local-llm-pdf-ocr/src/pdf_ocr/core/aligner.py:38-39` | HybridAligner — add threshold param support |

---

### Task 1: MinerU pipeline skips Surya, always uses block-level bboxes

**Files:**
- Modify: `backend/engine/pipeline.py:2553-2661`

**Background:** The current MinerU pipeline tries Surya line detection first, then pairs Surya bboxes 1:1 with MinerU paragraph text by array index. This is broken: Surya detects ~20 tight line boxes per page while MinerU returns ~5 paragraph-level text blocks. The fallback path (when Surya fails) uses MinerU's own `_model.json` block-level bboxes with `insert_textbox()` and works correctly.

**Change:** Remove the try/except Surya step. Call MinerU API directly, parse `_model.json`, embed with `embed_api_text_layer()`.

- [ ] **Step 1: Replace the MinerU pipeline block**

Replace lines 2540-2661 (the `elif ocr_engine == "mineru":` block in `_ocr_page`) with the simplified version below.

```python
        elif ocr_engine == "mineru":
            mineru_token = config.get("mineru_token", "")
            if not mineru_token:
                task_store.add_log(task_id, "MinerU: no token configured, skipping")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            mineru_model = config.get("mineru_model", "vlm")
            task_store.add_log(task_id, f"MinerU OCR: API (model={mineru_model}), block-level layout")
            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 5, "detail": "MinerU API OCR..."})

            try:
                from backend.engine.mineru_client import MinerUClient, parse_layout_from_zip
                from backend.engine.pdf_api_embed import embed_api_text_layer

                client = MinerUClient(token=mineru_token)
                try:
                    with open(pdf_path, "rb") as f:
                        pdf_bytes = f.read()
                    zip_bytes = await client.process_pdf(
                        pdf_bytes, file_name=os.path.basename(pdf_path),
                        model_version=mineru_model,
                    )
                    layout = parse_layout_from_zip(zip_bytes)
                finally:
                    await client.close()

                total_blocks = sum(len(v) for v in layout.values())
                task_store.add_log(task_id, f"MinerU: parsed {len(layout)} pages, {total_blocks} text blocks")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 80, "detail": f"{total_blocks} blocks"})

                output_pdf = pdf_path + ".mineru.pdf"
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, embed_api_text_layer, pdf_path, output_pdf, layout)

                if os.path.exists(output_pdf) and os.path.getsize(output_pdf) > 0:
                    os.replace(output_pdf, pdf_path)
                    report["ocr_done"] = True
                    task_store.add_log(task_id, "MinerU OCR complete")
                else:
                    raise RuntimeError("MinerU: embedding produced empty file")

                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})

            except asyncio.TimeoutError:
                task_store.add_log(task_id, "MinerU OCR timed out")
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                last_lines = "\n".join(tb.split(chr(10))[-5:])
                task_store.add_log(task_id, f"MinerU OCR error: {e} | {last_lines}"[:500])
```

- [ ] **Step 2: Remove unused Surya imports in the MinerU path**

The old code imported `run_surya_detect`, `SuryaDetectError`, `embed_with_surya_boxes` — these are no longer used in the MinerU path. They are removed in the replacement above.

- [ ] **Step 3: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "fix: MinerU pipeline skips Surya, uses own block-level bboxes via embed_api_text_layer"
```

---

### Task 2: Create Surya bbox visualization debug script

**Files:**
- Create: `local-llm-pdf-ocr/scripts/visualize_surya.py`
- Test: run on a Chinese PDF

**Background:** Before tuning Surya thresholds for Chinese, we need to see what bboxes Surya produces. This script renders a PDF page, runs Surya detection, draws bounding boxes over the image, and saves the result as a PNG for visual inspection.

- [ ] **Step 1: Write the visualization script**

Create `local-llm-pdf-ocr/scripts/visualize_surya.py`:

```python
"""Visualize Surya text-detection bboxes overlaid on rendered PDF pages.

Usage:
    uv run scripts/visualize_surya.py input.pdf [--dpi 200] [--page 0] [--output out.png]
    uv run scripts/visualize_surya.py input.pdf --all  (visualize every page)

Output: PNG image(s) with Surya bboxes drawn in red over the page render.
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description="Visualize Surya bboxes on PDF pages")
    parser.add_argument("input", help="Path to PDF file")
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--page", type=int, default=0, help="Page index (0-based) to visualize")
    parser.add_argument("--all", action="store_true", help="Visualize every page")
    parser.add_argument("--output", help="Output PNG path (for single page)")
    parser.add_argument("--out-dir", help="Output directory (for --all)")
    parser.add_argument("--text-threshold", type=float, default=None, help="Override DETECTOR_TEXT_THRESHOLD (default 0.6)")
    parser.add_argument("--blank-threshold", type=float, default=None, help="Override DETECTOR_BLANK_THRESHOLD (default 0.35)")
    parser.add_argument("--detect-batch-size", type=int, default=20)
    args = parser.parse_args()

    os.environ.setdefault("TQDM_DISABLE", "1")

    # Apply threshold overrides before importing Surya
    if args.text_threshold is not None or args.blank_threshold is not None:
        from surya.settings import settings
        if args.text_threshold is not None:
            settings.DETECTOR_TEXT_THRESHOLD = args.text_threshold
            print(f"[surya] DETECTOR_TEXT_THRESHOLD = {args.text_threshold}", file=sys.stderr)
        if args.blank_threshold is not None:
            settings.DETECTOR_BLANK_THRESHOLD = args.blank_threshold
            print(f"[surya] DETECTOR_BLANK_THRESHOLD = {args.blank_threshold}", file=sys.stderr)

    import fitz
    from surya.detection import DetectionPredictor

    doc = fitz.open(args.input)
    total_pages = len(doc)

    if args.all:
        page_indices = list(range(total_pages))
    else:
        if args.page < 0 or args.page >= total_pages:
            print(f"ERROR: page {args.page} out of range (0-{total_pages - 1})", file=sys.stderr)
            sys.exit(1)
        page_indices = [args.page]

    # Render pages to images
    page_images: dict[int, Image.Image] = {}
    page_sizes: dict[int, tuple] = {}
    for pg in page_indices:
        pix = doc[pg].get_pixmap(dpi=args.dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        page_images[pg] = img
        page_sizes[pg] = (pix.width, pix.height)
    doc.close()

    # Run Surya detection
    predictor = DetectionPredictor()
    image_list = list(page_images.values())
    pg_list = list(page_images.keys())
    all_boxes: dict[int, list] = {}

    for batch_start in range(0, len(image_list), args.detect_batch_size):
        batch_end = min(batch_start + args.detect_batch_size, len(image_list))
        batch_images = image_list[batch_start:batch_end]
        batch_pages = pg_list[batch_start:batch_end]
        predictions = predictor(batch_images)
        for pg, pred in zip(batch_pages, predictions):
            boxes = []
            for bbox in (pred.bboxes or []):
                boxes.append(list(bbox.bbox))
            boxes.sort(key=lambda b: (b[1], b[0]))
            all_boxes[pg] = boxes

    # Draw bboxes on images
    for pg in sorted(all_boxes.keys()):
        img = page_images[pg].copy()
        draw = ImageDraw.Draw(img)
        pw, ph = page_sizes[pg]
        boxes = all_boxes[pg]

        for i, box in enumerate(boxes):
            draw.rectangle(box, outline="red", width=2)
            # Label box index for spatial reference
            x0, y0 = box[0], box[1]
            draw.text((x0 + 2, y0), str(i), fill="yellow")

        # Write PDF page dimensions in corner
        pdf_pw = pw / args.dpi * 72
        pdf_ph = ph / args.dpi * 72
        draw.text((10, 10), f"Page {pg}  DPI={args.dpi}  {pdf_pw:.0f}x{pdf_ph:.0f}pt  Boxes={len(boxes)}", fill="green")

        if args.all:
            out_dir = args.out_dir or "."
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, f"page_{pg:04d}.png")
        else:
            out_path = args.output or f"page_{pg}.png"

        img.save(out_path)
        print(f"Saved: {out_path} ({len(boxes)} boxes)", file=sys.stderr)

    if args.all:
        print(f"Total pages processed: {len(page_indices)}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify script syntax**

```bash
uv run python -c "import py_compile; py_compile.compile('scripts/visualize_surya.py', doraise=True)" --directory D:\opencode\book-downloader\local-llm-pdf-ocr
```

Expected: silent success (no output).

- [ ] **Step 3: Commit**

```bash
cd D:\opencode\book-downloader
git add local-llm-pdf-ocr/scripts/visualize_surya.py
git commit -m "feat: add Surya bbox visualization debug script for Chinese detection tuning"
```

---

### Task 3: Expose detection threshold parameters in subprocess wrapper

**Files:**
- Modify: `local-llm-pdf-ocr/scripts/detect_boxes.py:27-31` — add CLI args
- Modify: `backend/engine/surya_detect.py:40-45,60-63` — forward new params
- Modify: `backend/engine/pipeline.py` (the LLM OCR & PaddleOCR paths that call `run_surya_detect`) — no changes needed, defaults work

**Background:** The subprocess wrapper `run_surya_detect()` hardcodes DPI=200 and doesn't expose threshold parameters. Adding these lets callers tune detection for Chinese text.

- [ ] **Step 1: Add CLI args to detect_boxes.py**

In `local-llm-pdf-ocr/scripts/detect_boxes.py`, add `--text-threshold` and `--blank-threshold` args:

Replace lines 27-31 (parser.add_argument calls):

```python
    parser.add_argument("--detect-batch-size", type=int, default=20, help="Pages per batch")
    parser.add_argument("--text-threshold", type=float, default=None, help="Override DETECTOR_TEXT_THRESHOLD (default 0.6)")
    parser.add_argument("--blank-threshold", type=float, default=None, help="Override DETECTOR_BLANK_THRESHOLD (default 0.35)")
    args = parser.parse_args()
```

Add after line 31 (`args = parser.parse_args()`), before the import of `fitz` and `HybridAligner`:

```python
    if args.text_threshold is not None or args.blank_threshold is not None:
        from surya.settings import settings
        if args.text_threshold is not None:
            settings.DETECTOR_TEXT_THRESHOLD = args.text_threshold
        if args.blank_threshold is not None:
            settings.DETECTOR_BLANK_THRESHOLD = args.blank_threshold
```

- [ ] **Step 2: Add params to surya_detect.py wrapper**

Modify `backend/engine/surya_detect.py`, update the function signature and command construction:

In `run_surya_detect()` (line 40-44), update signature:

```python
async def run_surya_detect(
    pdf_path: str,
    dpi: int = 200,
    pages: Optional[str] = None,
    detect_batch_size: int = 20,
    text_threshold: Optional[float] = None,
    blank_threshold: Optional[float] = None,
) -> Dict[int, List[List[float]]]:
```

In the command construction (lines 60-63), add threshold args:

```python
    cmd = [uv_bin, "run", "--directory", project_root, script, pdf_path, "--dpi", str(dpi)]
    if pages:
        cmd.extend(["--pages", pages])
    cmd.extend(["--detect-batch-size", str(detect_batch_size)])
    if text_threshold is not None:
        cmd.extend(["--text-threshold", str(text_threshold)])
    if blank_threshold is not None:
        cmd.extend(["--blank-threshold", str(blank_threshold)])
```

- [ ] **Step 3: Commit**

```bash
cd D:\opencode\book-downloader
git add local-llm-pdf-ocr/scripts/detect_boxes.py backend/engine/surya_detect.py
git commit -m "feat: expose Surya detection text/blank threshold params in CLI and subprocess wrapper"
```

---

### Self-Review

**1. Spec coverage:**
- MinerU uses own bboxes (skip Surya) → Task 1
- Surya visual debug tool → Task 2
- Surya threshold exposure → Task 3

**2. Placeholder scan:** No TBD/TODO/placeholder patterns. All code is concrete.

**3. Type consistency:**
- `run_surya_detect()` returns `Dict[int, List[List[float]]]` — consistent with existing usage
- `embed_api_text_layer(input_path, output_path, layout)` — layout is `PageTextBlocks = Dict[int, List[Dict[str, Any]]]`, which is what `parse_layout_from_zip()` returns
- `parse_layout_from_zip()` returns normalized bboxes [0..1], `embed_api_text_layer` multiplies by page width/height — consistent
- Threshold params are `Optional[float]` throughout — None means use Surya default
- `text_threshold`/`blank_threshold` names consistent across detect_boxes.py, surya_detect.py, visualize_surya.py
