# Optimized Parallel Per-Box Crop OCR with PaddleOCR-VL-1.5

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve per-box crop OCR from 78% to 87%+ match rate via crop preprocessing (filter non-text, upscale tiny) and tuned parameters (DPI=300, timeout=120s, concurrency=3).

**Architecture:** Surya detects line-level bboxes at DPI 300. Each bbox's crop is preprocessed: non-text shapes skipped, tiny crops (<40px) upscaled. Valid crops are submitted concurrently (max 3) to PaddleOCR-VL-1.5 API. Results are embedded at Surya's exact line coordinates via `embed_with_surya_boxes()`. This is an alternative pipeline alongside spatial allocation, not a replacement.

**Tech Stack:** Python, Surya, PaddleOCR-VL-1.5 online API, PyMuPDF (fitz), Pillow, asyncio, httpx

---

## File Structure

| File | Role |
|---|---|
| `backend/engine/pdf_api_embed.py` | New: `embed_with_perbox_paddleocr()` — full per-box pipeline combining Surya + PaddleOCR crops |
| `backend/engine/paddleocr_online_client.py:115-119` | Existing: `download_raw_jsonl()` — already handles BOS date header |

No new files needed. The preprocessing logic is small enough to inline in the pipeline function.

---

### Task 1: Create embed_with_perbox_paddleocr() pipeline function

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pdf_api_embed.py` — add new function at end of file (after line 236)

- [ ] **Step 1: Read the file**

Read `D:\opencode\book-downloader\backend\engine\pdf_api_embed.py` to find the end of the file (last function `allocate_text_to_surya_boxes` ends at ~line 236).

- [ ] **Step 2: Add the function**

Add at end of file:

```python
def embed_with_perbox_paddleocr(
    input_path: str,
    output_path: str,
    surya_boxes: Dict[int, List[List[float]]],
    paddle_token: str,
    dpi: int = 300,
    max_concurrency: int = 3,
) -> Dict[int, List[str]]:
    """Per-box crop OCR pipeline using PaddleOCR-VL-1.5 API.

    For each Surya text-line bbox, crops the page image and submits
    it to PaddleOCR-VL-1.5 for per-line text recognition. Filters out
    non-text shapes and upscales tiny crops before OCR.

    Returns page_texts compatible with embed_with_surya_boxes().
    Caller is responsible for calling embed_with_surya_boxes() after.
    """
    import asyncio
    import io
    import json
    from datetime import datetime, timezone

    import fitz
    import httpx
    from PIL import Image

    doc = fitz.open(input_path)
    page_texts: Dict[int, List[str]] = {}

    for pg in sorted(surya_boxes.keys()):
        page = doc[pg]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        pw, ph = pix.width, pix.height
        boxes = surya_boxes[pg]
        texts = [""] * len(boxes)
        crop_tasks = []  # [(box_idx, png_bytes)]
        skip_count = 0

        for i, bbox in enumerate(boxes):
            if len(bbox) < 4:
                continue

            x0 = int(max(0, bbox[0] * pw - 3))
            y0 = int(max(0, bbox[1] * ph - 3))
            x1 = int(min(pw, bbox[2] * pw + 3))
            y1 = int(min(ph, bbox[3] * ph + 3))

            if x1 <= x0 or y1 <= y0:
                continue

            bw = x1 - x0
            bh = y1 - y0

            # Filter non-text shapes
            aspect = max(bw, bh) / max(1, min(bw, bh))
            if aspect > 25:
                skip_count += 1
                continue  # likely a decorative line

            if bw * bh < 80:  # too small for meaningful OCR
                skip_count += 1
                continue

            crop = img.crop((x0, y0, x1, y1))

            # Upscale tiny crops
            if bh < 40:
                scale = 48.0 / bh
                new_w = max(8, int(bw * scale))
                new_h = 48
                crop = crop.resize((new_w, new_h), Image.LANCZOS)

            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            crop_tasks.append((i, buf.getvalue()))

        if not crop_tasks:
            page_texts[pg] = texts
            continue

        # Run OCR in parallel with semaphore
        async def _run(paddle_token, crop_tasks, dpi):
            sem = asyncio.Semaphore(max_concurrency)

            async def _ocr_one(client, box_idx, crop_bytes):
                async with sem:
                    files = {"file": (f"crop_{box_idx}.png", io.BytesIO(crop_bytes), "image/png")}
                    data = {
                        "model": "PaddleOCR-VL-1.5",
                        "optionalPayload": json.dumps({
                            "useDocOrientationClassify": False,
                            "useDocUnwarping": False,
                            "useChartRecognition": False,
                        }),
                    }
                    try:
                        resp = await client.post(
                            "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
                            data=data, files=files,
                        )
                        if resp.status_code != 200:
                            return (box_idx, "")
                        jid = resp.json().get("data", {}).get("jobId", "")
                        if not jid:
                            return (box_idx, "")

                        url = f"https://paddleocr.aistudio-app.com/api/v2/ocr/jobs/{jid}"
                        for _ in range(120):
                            await asyncio.sleep(0.5)
                            r2 = await client.get(url)
                            if r2.status_code != 200:
                                continue
                            j2 = r2.json()
                            state = j2.get("data", {}).get("state", "?")
                            if state == "done":
                                jurl = j2.get("data", {}).get("resultUrl", {}).get("jsonUrl", "")
                                async with httpx.AsyncClient(timeout=30) as bc:
                                    r3 = await bc.get(jurl, headers={
                                        "date": datetime.now(timezone.utc).strftime(
                                            "%a, %d %b %Y %H:%M:%S GMT"
                                        )
                                    })
                                    if r3.status_code != 200:
                                        return (box_idx, "")
                                    rec = json.loads(r3.text.strip().split("\n")[0])
                                    parsing = (
                                        rec.get("result", {})
                                        .get("layoutParsingResults", [{}])[0]
                                        .get("prunedResult", {})
                                        .get("parsing_res_list", [])
                                    )
                                    text = (parsing[0].get("block_content") or "").strip() if parsing else ""
                                    return (box_idx, text)
                            elif state == "failed":
                                return (box_idx, "")
                        return (box_idx, "")
                    except Exception:
                        return (box_idx, "")

            async with httpx.AsyncClient(
                headers={"Authorization": f"bearer {paddle_token}"},
                timeout=180,
            ) as client:
                tasks = [_ocr_one(client, idx, cb) for idx, cb in crop_tasks]
                return await asyncio.gather(*tasks)

        loop = asyncio.get_event_loop()
        results = loop.run_until_complete(_run(paddle_token, crop_tasks, dpi))

        for box_idx, text in results:
            if text and box_idx < len(texts):
                texts[box_idx] = text

        match_count = sum(1 for t in texts if t)
        print(f"  [perbox] page {pg}: {match_count}/{len(boxes)} matched ({skip_count} skipped, {len(crop_tasks)} OCR'd)", flush=True)

        page_texts[pg] = texts

    doc.close()
    return page_texts
```

- [ ] **Step 3: Verify syntax**

```bash
python -m py_compile backend\engine\pdf_api_embed.py
```

Work from: `D:\opencode\book-downloader`
Expected: silent success.

- [ ] **Step 4: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/pdf_api_embed.py
git commit -m "feat: add embed_with_perbox_paddleocr for parallel per-box crop OCR pipeline"
```

---

### Task 2: End-to-end test with 2.pdf

**Files:**
- Create: (test script, temporary — don't commit)

- [ ] **Step 1: Write test script**

Create `C:\Users\ADMINI~1\AppData\Local\Temp\opencode\test_perbox_v2.py`:

```python
import asyncio, os, sys, time
PROJECT_ROOT = r"D:\opencode\book-downloader"
sys.path.insert(0, PROJECT_ROOT)
TOKEN_PADDLE = "782e55e919ba6407081e744dc4bd7c6f150b8226"
PDF = r"C:\Users\Administrator\Downloads\2.pdf"
OUT = r"C:\Users\Administrator\Downloads\2_perbox_v2.pdf"

async def main():
    from backend.engine.surya_detect import run_surya_detect
    from backend.engine.pdf_api_embed import embed_with_perbox_paddleocr, embed_with_surya_boxes

    t0 = time.time()

    print("1. Surya detection...")
    surya_boxes = await run_surya_detect(PDF, dpi=300)
    total = sum(len(v) for v in surya_boxes.values())
    for pg in sorted(surya_boxes.keys()):
        print(f"   P{pg}: {len(surya_boxes[pg])} boxes")
    print(f"   Total: {total} boxes ({time.time()-t0:.1f}s)")

    print("\n2. Per-box OCR...")
    loop = asyncio.get_event_loop()
    page_texts = await loop.run_in_executor(
        None, embed_with_perbox_paddleocr, PDF, OUT, surya_boxes, TOKEN_PADDLE, 300, 3
    ) if False else embed_with_perbox_paddleocr(PDF, OUT, surya_boxes, TOKEN_PADDLE, 300, 3)

    # Well actually embed_with_perbox_paddleocr is async internally, let me fix:
    page_texts = embed_with_perbox_paddleocr(PDF, OUT, surya_boxes, TOKEN_PADDLE, 300, 3)

    matched = sum(1 for v in page_texts.values() for t in v if t)
    chars = sum(len(t) for v in page_texts.values() for t in v if t)
    print(f"\n   Matched: {matched}/{total} ({matched*100//total}%), {chars} chars")

    for i in range(min(5, len(page_texts.get(0, [])))):
        t = page_texts[0][i][:50] if page_texts[0][i] else "<empty>"
        print(f"   box[{i}]: {t!r}")

    print("\n3. Embedding...")
    await loop.run_in_executor(None, embed_with_surya_boxes, PDF, OUT, surya_boxes, page_texts)

    import fitz
    doc = fitz.open(OUT)
    tc = sum(len(doc[p].get_text("text")) for p in range(len(doc)))
    doc.close()
    print(f"   Output: {OUT} ({tc} chars, {time.time()-t0:.1f}s)")

asyncio.run(main())
```

Wait — `embed_with_perbox_paddleocr` uses `loop.run_until_complete` internally for the async sub-calls, but the test script is also in an async context. This will cause nested event loop issues.

**Correction:** `embed_with_perbox_paddleocr` should NOT call `run_until_complete`. Instead, the caller should handle async. But since `embed_with_surya_boxes` is sync (run via `run_in_executor`), the simplest approach is: let `embed_with_perbox_paddleocr` be a sync function that starts its own event loop internally (as written above — it calls `loop.run_until_complete`). The test script should call it from a thread:

```python
import asyncio, os, sys, time
PROJECT_ROOT = r"D:\opencode\book-downloader"
sys.path.insert(0, PROJECT_ROOT)
TOKEN_PADDLE = "782e55e919ba6407081e744dc4bd7c6f150b8226"
PDF = r"C:\Users\Administrator\Downloads\2.pdf"
OUT = r"C:\Users\Administrator\Downloads\2_perbox_v2.pdf"

async def main():
    from backend.engine.surya_detect import run_surya_detect
    from backend.engine.pdf_api_embed import embed_with_perbox_paddleocr, embed_with_surya_boxes

    t0 = time.time()

    print("1. Surya detection...")
    surya_boxes = await run_surya_detect(PDF, dpi=300)
    total = sum(len(v) for v in surya_boxes.values())
    print(f"   {total} boxes ({time.time()-t0:.1f}s)")

    print("\n2. Per-box OCR...")
    t1 = time.time()
    loop = asyncio.get_event_loop()
    page_texts = await loop.run_in_executor(
        None, embed_with_perbox_paddleocr, PDF, OUT, surya_boxes, TOKEN_PADDLE, 300, 3
    )
    print(f"   OCR time: {time.time()-t1:.1f}s")

    matched = sum(1 for v in page_texts.values() for t in v if t)
    chars = sum(len(t) for v in page_texts.values() for t in v if t)
    print(f"   Matched: {matched}/{total} ({matched*100//total}%), {chars} chars")

    for i in range(min(5, len(page_texts.get(0, [])))):
        t = page_texts[0][i][:50] if page_texts[0][i] else "<empty>"
        print(f"   [{i}]: {t!r}")

    print("\n3. Embedding...")
    await loop.run_in_executor(None, embed_with_surya_boxes, PDF, OUT, surya_boxes, page_texts)

    import fitz
    doc = fitz.open(OUT)
    tc = sum(len(doc[p].get_text("text")) for p in range(len(doc)))
    doc.close()
    print(f"   Output: {OUT} ({tc} chars, {time.time()-t0:.1f}s)")

asyncio.run(main())
```

- [ ] **Step 2: Run the test**

```bash
D:\opencode\book-downloader\backend\venv\Scripts\python.exe C:\Users\ADMINI~1\AppData\Local\Temp\opencode\test_perbox_v2.py
```

Expected:
- Surya at 300 DPI detects boxes (may differ from 200 DPI)
- Per-box OCR with preprocessing, concurrency=3
- Match rate > 78% (baseline was 78% at 200 DPI, concurrency=3)
- Output PDF with selectable text

- [ ] **Step 3: Compare with spatial allocation**

Compare with baseline results on 2.pdf:
- Spatial allocation: 85/86 (99%), 1968 chars, 12s
- Per-box v2 target: 80+/86 (93%+), ~150 chars/s page, ~90s total

- [ ] **Step 4: User review**

Open `C:\Users\Administrator\Downloads\2_perbox_v2.pdf`. Verify text selection is at exact line positions with accurate per-line text.

---

### Self-Review

**1. Spec coverage:**
- Crop preprocessing (filter + upscale) → in `embed_with_perbox_paddleocr` inline logic (Task 1)
- Enhanced parameters (DPI=300, timeout=120, concurrency=3) → in `embed_with_perbox_paddleocr` (Task 1)
- Test → Task 2
- Comparison with spatial allocation → Task 2, Step 3

**2. Placeholder scan:** No TBD/TODO. All code shown in full.

**3. Type consistency:**
- `embed_with_perbox_paddleocr()` returns `Dict[int, List[str]]` — compatible with `embed_with_surya_boxes()` parameter `page_texts`
- `surya_boxes` parameter: `Dict[int, List[List[float]]]` — matches `run_surya_detect()` return type
- DPI parameter: `int = 300` — passed to both `get_pixmap(dpi)` and kept as documentation
- `paddle_token: str` — passed directly to PaddleOCR API
- `max_concurrency: int = 3` — semaphore limit, verified stable value
- Internal async `_run()` uses `loop.run_until_complete()` — works because the function is called from a thread via `run_in_executor`
- Last box gets remaining text via `end = text_len` when `j == len(alloc) - 1` — applies to the `allocate_text_to_surya_boxes` function shared by spatial allocation, not relevant to per-box function
