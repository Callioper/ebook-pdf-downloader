# MinerU Spatial Text Allocation to Surya Line Bboxes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use Surya's accurate line-level bboxes for text positioning, with MinerU API text content spatially allocated by matching Surya boxes to MinerU block regions.

**Architecture:** MinerU pipeline runs two phases in parallel: (1) Surya line detection for precise bbox positions, (2) MinerU API for text content with block-level bboxes. A spatial allocation function maps each MinerU block's text to the Surya line boxes whose centers fall within that block's region. `embed_with_surya_boxes()` then embeds the allocated text at Surya's tight line-level positions via `insert_text()` + morph.

**Tech Stack:** Python, Surya (DetectionPredictor), MinerU API v4, PyMuPDF (fitz), asyncio

---

## File Structure

| File | Role |
|---|---|
| `backend/engine/pdf_api_embed.py` | New: `allocate_text_to_surya_boxes()` spatial allocator. Existing `embed_with_surya_boxes()` unchanged (reused as-is). |
| `backend/engine/pipeline.py:2553-2603` | MinerU pipeline path: Surya detect + MinerU API + spatial allocator + embed |

---

### Task 1: Create spatial text allocation function

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pdf_api_embed.py` — add `allocate_text_to_surya_boxes()` at end of file

**Background:** Given MinerU's block-level items (each with a bbox and text) and Surya's line-level bboxes (both in reading order), this function distributes MinerU text to individual Surya boxes. For each MinerU block, it finds all Surya boxes whose center point falls within the block's bbox, then splits the block text proportionally by box width.

- [ ] **Step 1: Write the function**

Add to the end of `D:\opencode\book-downloader\backend\engine\pdf_api_embed.py` (after line 150, after `embed_with_surya_boxes`):

```python
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
                chars = max(1, round(text_len * ratio))
                end = min(text_len, cursor + chars)
                # Last box in group gets remaining text to avoid truncation
                if idx == matching[-1][0]:
                    end = text_len
                texts[idx] = block_text[cursor:end]
                cursor = end

        page_texts[pg] = texts

    return page_texts
```

- [ ] **Step 2: Verify syntax**

```bash
python -m py_compile backend\engine\pdf_api_embed.py
```

Work from: `D:\opencode\book-downloader`

Expected: silent success (no output).

- [ ] **Step 3: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/pdf_api_embed.py
git commit -m "feat: add allocate_text_to_surya_boxes spatial text distribution for MinerU hybrid"
```

---

### Task 2: Update MinerU pipeline to use Surya detection + spatial embed

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pipeline.py:2553-2603`

**Background:** The current MinerU pipeline (from Task 1 of the previous plan) skips Surya and uses MinerU's block-level bboxes directly. We now restore Surya detection for precise positioning, but use the spatial allocator to correctly distribute text across line boxes.

- [ ] **Step 1: Replace the MinerU pipeline block**

Read `D:\opencode\book-downloader\backend\engine\pipeline.py` to find the `elif ocr_engine == "mineru":` block. Replace the entire block (from `elif ocr_engine == "mineru":` through to the next `elif`, currently `elif ocr_engine == "paddleocr_online":`) with:

```python
        elif ocr_engine == "mineru":
            mineru_token = config.get("mineru_token", "")
            if not mineru_token:
                task_store.add_log(task_id, "MinerU: no token configured, skipping")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            mineru_model = config.get("mineru_model", "vlm")
            task_store.add_log(task_id, f"MinerU OCR (hybrid): Surya detection + MinerU API spatial (model={mineru_model})")
            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 5, "detail": "Running Surya detection..."})

            try:
                from backend.engine.surya_detect import run_surya_detect, SuryaDetectError
                from backend.engine.mineru_client import MinerUClient, parse_layout_from_zip
                from backend.engine.pdf_api_embed import allocate_text_to_surya_boxes, embed_with_surya_boxes

                # Step 1: Surya line detection
                try:
                    surya_boxes = await run_surya_detect(pdf_path, dpi=200)
                except SuryaDetectError as e:
                    task_store.add_log(task_id, f"MinerU: Surya detection failed — {e}. Falling back to block-level layout.")
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
                    task_store.add_log(task_id, f"MinerU fallback: parsed {len(layout)} pages")
                    output_pdf = pdf_path + ".mineru.pdf"
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, embed_api_text_layer, pdf_path, output_pdf, layout)
                    if os.path.exists(output_pdf) and os.path.getsize(output_pdf) > 0:
                        os.replace(output_pdf, pdf_path)
                        report["ocr_done"] = True
                        task_store.add_log(task_id, "MinerU OCR complete (fallback: block-level layout)")
                    await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                    return report

                total_boxes = sum(len(v) for v in surya_boxes.values())
                task_store.add_log(task_id, f"MinerU: Surya detected {total_boxes} boxes across {len(surya_boxes)} pages")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 20, "detail": f"Surya: {total_boxes} boxes"})

                # Step 2: MinerU API for text
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
                    layout = parse_layout_from_zip(zip_bytes)
                finally:
                    await client.close()

                total_blocks = sum(len(v) for v in layout.values())
                task_store.add_log(task_id, f"MinerU: API returned {len(layout)} pages, {total_blocks} text blocks")

                # Step 3: Spatial allocation — map MinerU block text to Surya line boxes
                page_texts = allocate_text_to_surya_boxes(surya_boxes, layout)
                total_text = sum(len(t) for v in page_texts.values() for t in v if t)
                all_boxes_count = sum(len(v) for v in page_texts.values())
                matched = sum(1 for v in page_texts.values() for t in v if t)
                task_store.add_log(task_id, f"MinerU: spatial allocation: {matched}/{all_boxes_count} boxes received text ({total_text} chars)")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 85, "detail": f"{matched} boxes matched"})

                # Step 4: Embed with Surya bboxes
                output_pdf = pdf_path + ".mineru.pdf"
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, embed_with_surya_boxes,
                    pdf_path, output_pdf, surya_boxes, page_texts,
                )

                if os.path.exists(output_pdf) and os.path.getsize(output_pdf) > 0:
                    os.replace(output_pdf, pdf_path)
                    report["ocr_done"] = True
                    task_store.add_log(task_id, "MinerU OCR complete (hybrid: Surya boxes + MinerU text, spatial allocation)")
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

- [ ] **Step 2: Verify no syntax errors**

```bash
python -m py_compile backend\engine\pipeline.py
```

Work from: `D:\opencode\book-downloader`

Expected: silent success.

- [ ] **Step 3: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/pipeline.py
git commit -m "feat: MinerU pipeline uses Surya line bboxes + spatial text allocation from MinerU blocks"
```

---

### Task 3: End-to-end test with 2.pdf

**Files:**
- Create: (test script, temporary — don't commit)

**Background:** Verify the full pipeline works: Surya detects line bboxes, MinerU API returns text, spatial allocation distributes text to line boxes, embedding produces selectable PDF with text at correct positions.

- [ ] **Step 1: Write test script**

Create `C:\Users\ADMINI~1\AppData\Local\Temp\opencode\test_spatial.py`:

```python
import asyncio
import os
import sys
import time

PROJECT_ROOT = r"D:\opencode\book-downloader"
sys.path.insert(0, PROJECT_ROOT)

TOKEN = "YOUR_MINERU_TOKEN"
PDF_PATH = r"C:\Users\Administrator\Downloads\2.pdf"
OUT_PATH = r"C:\Users\Administrator\Downloads\2_spatial_ocr.pdf"


async def main():
    from backend.engine.surya_detect import run_surya_detect
    from backend.engine.mineru_client import MinerUClient, parse_layout_from_zip
    from backend.engine.pdf_api_embed import allocate_text_to_surya_boxes, embed_with_surya_boxes

    t0 = time.time()

    # Step 1: Surya detection
    print("[test] Running Surya detection...")
    surya_boxes = await run_surya_detect(PDF_PATH, dpi=200)
    total_boxes = sum(len(v) for v in surya_boxes.values())
    print(f"[test] Surya: {total_boxes} boxes on {len(surya_boxes)} pages ({time.time()-t0:.1f}s)")

    # Step 2: MinerU API
    print("[test] Calling MinerU API...")
    client = MinerUClient(token=TOKEN)
    try:
        with open(PDF_PATH, "rb") as f:
            pdf_bytes = f.read()
        zip_bytes = await client.process_pdf(
            pdf_bytes,
            file_name=os.path.basename(PDF_PATH),
            model_version="vlm",
        )
        layout = parse_layout_from_zip(zip_bytes)
        print(f"[test] MinerU: {sum(len(v) for v in layout.values())} blocks on {len(layout)} pages ({time.time()-t0:.1f}s)")
    finally:
        await client.close()

    # Step 3: Spatial allocation
    page_texts = allocate_text_to_surya_boxes(surya_boxes, layout)
    total_text = sum(len(t) for v in page_texts.values() for t in v if t)
    all_boxes = sum(len(v) for v in page_texts.values())
    matched = sum(1 for v in page_texts.values() for t in v if t)
    print(f"[test] Allocation: {matched}/{all_boxes} boxes received text, {total_text} chars total")

    # Show sample allocation for page 0
    pg0_boxes = surya_boxes.get(0, [])
    pg0_texts = page_texts.get(0, [])
    print(f"\n[test] Page 0 sample ({len(pg0_boxes)} boxes):")
    for i in range(min(8, len(pg0_boxes))):
        by = pg0_boxes[i][1] if len(pg0_boxes[i]) >= 2 else 0
        txt = (pg0_texts[i] if i < len(pg0_texts) else "")[:50]
        match = "MATCH" if txt else "EMPTY"
        print(f"  box[{i}] y={by:.3f} [{match}] text={txt!r}")

    # Step 4: Embed
    print("\n[test] Embedding text layer...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, embed_with_surya_boxes, PDF_PATH, OUT_PATH, surya_boxes, page_texts
    )
    out_size = os.path.getsize(OUT_PATH)
    print(f"[test] Output: {OUT_PATH} ({out_size} bytes)")
    print(f"[test] Total: {time.time()-t0:.1f}s")

    # Quick verify
    import fitz
    doc = fitz.open(OUT_PATH)
    for pg in range(len(doc)):
        text = doc[pg].get_text("text")
        print(f"  Page {pg}: {len(text)} chars selectable")
    doc.close()


asyncio.run(main())
```

- [ ] **Step 2: Run the test**

```bash
D:\opencode\book-downloader\backend\venv\Scripts\python.exe C:\Users\ADMINI~1\AppData\Local\Temp\opencode\test_spatial.py
```

Expected:
- Surya detects ~53 boxes on page 0, ~N on page 1
- MinerU API returns ~37+7 blocks
- Spatial allocation: most boxes get text (high match ratio)
- Output: `2_spatial_ocr.pdf` with selectable text
- Page 0 and 1 have selectable text characters

- [ ] **Step 3: Verify user review**

Open `C:\Users\Administrator\Downloads\2_spatial_ocr.pdf` in a PDF reader. Compare text selection positions with `2_page0_surya.png` red boxes. Text should be selectable at the positions marked by Surya's red boxes — this is the user's acceptance criteria.

---

### Self-Review

**1. Spec coverage:**
- Spatial allocation function with center-point matching → Task 1
- MinerU pipeline uses Surya detect + spatial embed + fallback → Task 2
- End-to-end test with 2.pdf → Task 3

**2. Placeholder scan:**
- No TBD/TODO/placeholder patterns
- All code shown in full (no "write the rest" or "similar to above")
- Error handling: Surya failure falls back to block-level embed (existing path)

**3. Type consistency:**
- `allocate_text_to_surya_boxes(surya_boxes, mineru_blocks)` returns `Dict[int, List[str]]`
- `embed_with_surya_boxes(pdf, output, surya_boxes, page_texts)` expects `Dict[int, List[str]]` for page_texts — consistent
- `surya_boxes` type: `Dict[int, List[List[float]]]` → consistent with `run_surya_detect()` return type
- `mineru_blocks` type: `PageTextBlocks = Dict[int, List[Dict[str, Any]]]` → consistent with `parse_layout_from_zip()` return type
- Pipeline imports match function names exactly: `allocate_text_to_surya_boxes` in both Task 1 definition and Task 2 import
