# PaddleOCR-VL-1.5 Spatial Text Allocation to Surya Line Bboxes

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PaddleOCR-VL-1.5 online API with Surya line-level bbox positioning + spatial text allocation, reusing the same `allocate_text_to_surya_boxes()` + `embed_with_surya_boxes()` pipeline built for MinerU.

**Architecture:** PaddleOCR-VL-1.5 online API (Baidu AI Studio) returns `prunedResult.parsing_res_list[]` — an array of blocks each containing `block_bbox` (pixel coordinates) and `block_content` (OCR text). A new parser extracts normalized blocks into the existing `PageTextBlocks` format. The pipeline reuses Surya detection → spatial allocation → embed, identical flow to MinerU.

**Tech Stack:** Python, Surya, PaddleOCR-VL-1.5 online API, PyMuPDF (fitz), asyncio, httpx

---

## File Structure

| File | Role |
|---|---|
| `backend/engine/paddleocr_online_client.py:124-141` | Extend `parse_jsonl_result` to also return parsed block-level data from `prunedResult` |
| `backend/engine/pipeline.py:2653+` | Update `paddleocr_online` OCR path to use Surya detect + spatial embed |

---

### Data Format

**PaddleOCR JSONL `prunedResult` (per page):**

```json
{
  "width": 1191,
  "height": 1679,
  "parsing_res_list": [
    {
      "block_label": "text",
      "block_content": "图书在版编目(CIP)数据",
      "block_bbox": [181, 152, 432, 182],
      "block_id": 0,
      "block_order": 1,
      "group_id": 0,
      "block_polygon_points": [[181.0,152.0],[432.0,152.0],[432.0,182.0],[181.0,182.0]]
    }
  ]
}
```

`block_bbox` is `[x0, y0, x1, y1]` in **pixel coordinates**. Page dimensions are `width` × `height` pixels. Normalize by dividing coordinates by page dimensions.

---

### Task 1: Add `parse_paddleocr_blocks()` to extract blocks with normalized bboxes

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\paddleocr_online_client.py` — add new function after `parse_jsonl_result` (after line 141)

- [ ] **Step 1: Read the file and add the function**

Read `D:\opencode\book-downloader\backend\engine\paddleocr_online_client.py`. Add this function after the last line of the file (after `parse_jsonl_result`):

```python
def parse_paddleocr_blocks(jsonl_text: str) -> Dict[int, List[Dict[str, Any]]]:
    """Parse PaddleOCR JSONL prunedResult into per-page blocks with normalized bboxes.

    Each block = {"text": str, "bbox": [nx0,ny0,nx1,ny1], "type": str}
    Coordinates normalized to [0..1] from pixel space.

    Returns format compatible with PageTextBlocks (Dict[int, List[Dict[str, Any]]])
    so allocate_text_to_surya_boxes() can consume it directly.
    """
    layout: Dict[int, List[Dict[str, Any]]] = {}

    for line in jsonl_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        result = record.get("result", {})
        layout_results = result.get("layoutParsingResults", [])

        for item in layout_results:
            pruned = item.get("prunedResult", {})
            if not pruned:
                # Fallback to markdown page index from parse_jsonl_result
                continue

            width = float(pruned.get("width", 1))
            height = float(pruned.get("height", 1))
            if width <= 0 or height <= 0:
                width, height = 1.0, 1.0

            parsing_list = pruned.get("parsing_res_list", [])
            if not parsing_list:
                continue

            blocks = []
            for entry in parsing_list:
                text = (entry.get("block_content") or "").strip()
                bbox = entry.get("block_bbox")
                label = entry.get("block_label", "")

                if not text or not bbox or len(bbox) != 4:
                    continue

                nx0 = float(bbox[0]) / width
                ny0 = float(bbox[1]) / height
                nx1 = float(bbox[2]) / width
                ny1 = float(bbox[3]) / height

                blocks.append({
                    "text": text,
                    "bbox": [nx0, ny0, nx1, ny1],
                    "type": label,
                })

            if blocks:
                # PaddleOCR returns one layoutParsingResult per page; use cardinal index as page number
                page_idx = len(layout)
                layout[page_idx] = blocks

    return layout
```

Note: The import for `Dict, List, Any` from typing already exists at line 7. `json` is imported at line 4. No new imports needed.

- [ ] **Step 2: Verify syntax**

```bash
python -m py_compile backend\engine\paddleocr_online_client.py
```

Work from: `D:\opencode\book-downloader`

Expected: silent success.

- [ ] **Step 3: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/paddleocr_online_client.py
git commit -m "feat: add parse_paddleocr_blocks to extract normalized block bboxes from prunedResult"
```

---

### Task 2: Update PaddleOCR pipeline to use Surya detection + spatial embed

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pipeline.py` — replace the `elif ocr_engine == "paddleocr_online":` block

- [ ] **Step 1: Read the file and find the PaddleOCR block**

Read `D:\opencode\book-downloader\backend\engine\pipeline.py`. Find the `elif ocr_engine == "paddleocr_online":` block. It starts after the MinerU block (around line 2653) and ends at the next `elif` or the end of the if/elif chain.

- [ ] **Step 2: Replace the block**

Replace the entire `elif ocr_engine == "paddleocr_online":` block with:

```python
        elif ocr_engine == "paddleocr_online":
            paddle_token = config.get("paddleocr_online_token", "")
            if not paddle_token:
                task_store.add_log(task_id, "PaddleOCR online: no token configured, skipping")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            task_store.add_log(task_id, "PaddleOCR online (hybrid): Surya detection + PaddleOCR-VL-1.5 API spatial")
            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 5, "detail": "Running Surya detection..."})

            try:
                from backend.engine.surya_detect import run_surya_detect, SuryaDetectError
                from backend.engine.paddleocr_online_client import PaddleOCRClient, parse_paddleocr_blocks
                from backend.engine.pdf_api_embed import allocate_text_to_surya_boxes, embed_with_surya_boxes

                # Step 1: Surya line detection
                try:
                    surya_boxes = await run_surya_detect(pdf_path, dpi=200)
                except SuryaDetectError as e:
                    task_store.add_log(task_id, f"PaddleOCR: Surya detection failed — {e}. Falling back to markdown-only embed.")
                    client = PaddleOCRClient(token=paddle_token)
                    try:
                        with open(pdf_path, "rb") as f:
                            pdf_bytes = f.read()
                        pages_data = await client.process_pdf(pdf_bytes, file_name=os.path.basename(pdf_path))
                    finally:
                        await client.close()
                    task_store.add_log(task_id, f"PaddleOCR fallback: {len(pages_data)} pages with markdown")
                    await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100, "detail": "Fallback: markdown only"})
                    return report

                total_boxes = sum(len(v) for v in surya_boxes.values())
                task_store.add_log(task_id, f"PaddleOCR: Surya detected {total_boxes} boxes across {len(surya_boxes)} pages")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 20, "detail": f"Surya: {total_boxes} boxes"})

                # Step 2: PaddleOCR-VL-1.5 API
                task_store.add_log(task_id, "PaddleOCR: calling API...")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 25, "detail": "PaddleOCR-VL-1.5 API..."})

                client = PaddleOCRClient(token=paddle_token)
                try:
                    with open(pdf_path, "rb") as f:
                        pdf_bytes = f.read()
                    # Get raw JSONL text for block parsing
                    job_id = await client.submit_job_file(pdf_path, pdf_bytes)
                    result_data = await client.poll_job(job_id, progress_callback=None)
                    jsonl_url = result_data.get("resultUrl", {}).get("jsonUrl", "")
                    import httpx
                    async with httpx.AsyncClient(timeout=120) as http:
                        r = await http.get(jsonl_url)
                        raw_jsonl = r.text
                finally:
                    await client.close()

                layout = parse_paddleocr_blocks(raw_jsonl)
                total_blocks = sum(len(v) for v in layout.values())
                task_store.add_log(task_id, f"PaddleOCR: API returned {len(layout)} pages, {total_blocks} text blocks")

                # Step 3: Spatial allocation
                page_texts = allocate_text_to_surya_boxes(surya_boxes, layout)
                total_text = sum(len(t) for v in page_texts.values() for t in v if t)
                all_boxes_count = sum(len(v) for v in page_texts.values())
                matched = sum(1 for v in page_texts.values() for t in v if t)
                task_store.add_log(task_id, f"PaddleOCR: spatial allocation: {matched}/{all_boxes_count} boxes received text ({total_text} chars)")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 85, "detail": f"{matched} boxes matched"})

                # Step 4: Embed with Surya bboxes
                output_pdf = pdf_path + ".paddleocr.pdf"
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, embed_with_surya_boxes,
                    pdf_path, output_pdf, surya_boxes, page_texts,
                )

                if os.path.exists(output_pdf) and os.path.getsize(output_pdf) > 0:
                    os.replace(output_pdf, pdf_path)
                    report["ocr_done"] = True
                    task_store.add_log(task_id, "PaddleOCR online complete (hybrid: Surya boxes + PaddleOCR text, spatial allocation)")
                else:
                    raise RuntimeError("PaddleOCR: embedding produced empty file")

                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})

            except asyncio.TimeoutError:
                task_store.add_log(task_id, "PaddleOCR online timed out")
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                last_lines = "\n".join(tb.split(chr(10))[-5:])
                task_store.add_log(task_id, f"PaddleOCR online error: {e} | {last_lines}"[:500])
```

- [ ] **Step 3: Verify syntax**

```bash
python -m py_compile backend\engine\pipeline.py
```

Work from: `D:\opencode\book-downloader`

Expected: silent success.

- [ ] **Step 4: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/pipeline.py
git commit -m "feat: PaddleOCR online pipeline uses Surya line bboxes + spatial text allocation from prunedResult"
```

---

### Task 3: End-to-end test with 2.pdf

**Files:**
- Create: (test script, temporary — don't commit)

- [ ] **Step 1: Write test script**

Create `C:\Users\ADMINI~1\AppData\Local\Temp\opencode\test_paddleocr_spatial.py`:

```python
import asyncio
import os
import sys
import time

PROJECT_ROOT = r"D:\opencode\book-downloader"
sys.path.insert(0, PROJECT_ROOT)

TOKEN = "782e55e919ba6407081e744dc4bd7c6f150b8226"
PDF_PATH = r"C:\Users\Administrator\Downloads\2.pdf"
OUT_PATH = r"C:\Users\Administrator\Downloads\2_paddleocr_spatial.pdf"


async def main():
    from backend.engine.surya_detect import run_surya_detect
    from backend.engine.paddleocr_online_client import PaddleOCRClient, parse_paddleocr_blocks
    from backend.engine.pdf_api_embed import allocate_text_to_surya_boxes, embed_with_surya_boxes
    import httpx

    t0 = time.time()

    # Step 1: Surya detection
    print("[test] Running Surya detection...")
    surya_boxes = await run_surya_detect(PDF_PATH, dpi=200)
    total_boxes = sum(len(v) for v in surya_boxes.values())
    print(f"[test] Surya: {total_boxes} boxes on {len(surya_boxes)} pages ({time.time()-t0:.1f}s)")

    # Step 2: PaddleOCR API
    print("[test] Calling PaddleOCR-VL-1.5 API...")
    client = PaddleOCRClient(token=TOKEN)
    try:
        with open(PDF_PATH, "rb") as f:
            pdf_bytes = f.read()
        job_id = await client.submit_job_file(PDF_PATH, pdf_bytes)
        print(f"[test] Job ID: {job_id}")
        result_data = await client.poll_job(job_id)
        jsonl_url = result_data.get("resultUrl", {}).get("jsonUrl", "")
        async with httpx.AsyncClient(timeout=120) as http:
            r = await http.get(jsonl_url)
            raw_jsonl = r.text
    finally:
        await client.close()

    layout = parse_paddleocr_blocks(raw_jsonl)
    total_blocks = sum(len(v) for v in layout.values())
    print(f"[test] PaddleOCR: {total_blocks} blocks on {len(layout)} pages ({time.time()-t0:.1f}s)")

    # Show sample blocks
    for pg in sorted(layout.keys())[:2]:
        blocks = layout[pg]
        print(f"  Page {pg}: {len(blocks)} blocks")
        for i, b in enumerate(blocks[:3]):
            bb = b.get("bbox", [])
            txt = (b.get("text") or "")[:40]
            print(f"    [{b.get('type','')}] bbox=[{bb[0]:.3f},{bb[1]:.3f},{bb[2]:.3f},{bb[3]:.3f}] text={txt!r}")

    # Step 3: Spatial allocation
    page_texts = allocate_text_to_surya_boxes(surya_boxes, layout)
    matched = sum(1 for v in page_texts.values() for t in v if t)
    all_boxes = sum(len(v) for v in page_texts.values())
    total_chars = sum(len(t) for v in page_texts.values() for t in v if t)
    print(f"\n[test] Allocation: {matched}/{all_boxes} boxes matched, {total_chars} chars")

    # Step 4: Embed
    print("[test] Embedding text layer...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, embed_with_surya_boxes, PDF_PATH, OUT_PATH, surya_boxes, page_texts
    )
    out_size = os.path.getsize(OUT_PATH)
    print(f"[test] Output: {OUT_PATH} ({out_size} bytes)")
    print(f"[test] Total: {time.time()-t0:.1f}s")

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
D:\opencode\book-downloader\backend\venv\Scripts\python.exe C:\Users\ADMINI~1\AppData\Local\Temp\opencode\test_paddleocr_spatial.py
```

Expected:
- Surya detects ~86 boxes
- PaddleOCR API returns ~32+6 blocks
- Spatial allocation: high match rate (>90%)
- Output: `2_paddleocr_spatial.pdf` with selectable text

- [ ] **Step 3: User review**

Open `C:\Users\Administrator\Downloads\2_paddleocr_spatial.pdf` in a PDF reader. Verify text selection positions match Surya's red box annotations.

---

### Self-Review

**1. Spec coverage:**
- Parse `prunedResult.parsing_res_list` into normalized blocks → Task 1
- Pipeline uses Surya detect + PaddleOCR API + spatial embed + fallback → Task 2
- End-to-end test → Task 3

**2. Placeholder scan:** No TBD/TODO. All code shown in full.

**3. Type consistency:**
- `parse_paddleocr_blocks()` returns `Dict[int, List[Dict[str, Any]]]` = `PageTextBlocks` → compatible with `allocate_text_to_surya_boxes()`
- `allocate_text_to_surya_boxes()` returns `Dict[int, List[str]]` → compatible with `embed_with_surya_boxes()`
- Pipeline imports match function names: `parse_paddleocr_blocks`, `allocate_text_to_surya_boxes`, `embed_with_surya_boxes`
- Page indexing: `parse_paddleocr_blocks` uses `page_idx = len(layout)` (sequential 0,1,2...) which matches `run_surya_detect()` page indices
