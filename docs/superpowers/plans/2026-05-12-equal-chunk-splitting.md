# Equal-Chunk Line Splitting for Spatial Text Allocation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace width-proportional text splitting with equal-chunk splitting guided by estimated line count from block height, so each Surya box gets a complete text line instead of a width-scaled fragment.

**Architecture:** The current `allocate_text_to_surya_boxes()` splits MinerU/PaddleOCR block text across matching Surya boxes proportionally by box width — a wide box gets more characters regardless of actual line boundaries. The fix: estimate the number of text lines from `block_bbox.height / avg_line_height`, split the block text into that many equal character chunks, and assign one chunk per matching Surya box in reading order. This produces more natural line breaks aligned with visual text lines.

**Tech Stack:** Python, existing `pdf_api_embed.py` function

---

## File Structure

| File | Role |
|---|---|
| `backend/engine/pdf_api_embed.py:152-227` | Rewrite inner text-splitting logic in `allocate_text_to_surya_boxes()` |

---

### Task 1: Rewrite text splitting in allocate_text_to_surya_boxes()

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pdf_api_embed.py:206-218` — replace the width-proportional split with equal-chunk split

- [ ] **Step 1: Read the file**

Read `D:\opencode\book-downloader\backend\engine\pdf_api_embed.py`. Find the `allocate_text_to_surya_boxes` function. Note the current text-splitting block (around lines 206-218).

- [ ] **Step 2: Replace the text-splitting logic**

Replace the width-proportional splitting block:

```python
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
```

With equal-chunk splitting based on estimated line count:

```python
            # Estimate number of lines from block height
            block_h = by1 - by0
            est_lines = max(1, round(block_h / avg_line_h)) if avg_line_h > 0 else len(matching)

            # Use matching box count as upper bound on chunks
            n_chunks = min(len(matching), est_lines)
            text_len = len(block_text)
            chars_per_chunk = text_len // n_chunks
            remainder = text_len % n_chunks

            cursor = 0
            for j, (idx, box_w) in enumerate(matching):
                if j >= n_chunks:
                    break
                chars = chars_per_chunk + (1 if j < remainder else 0)
                end = min(text_len, cursor + chars)
                if idx == matching[-1][0]:
                    end = text_len  # last box gets remaining
                chunk = block_text[cursor:end]
                if chunk:
                    if texts[idx]:
                        texts[idx] = texts[idx] + " " + chunk
                    else:
                        texts[idx] = chunk
                cursor = end
```

- [ ] **Step 3: Add avg_line_h computation**

The function now needs `avg_line_h` — the average Surya line height for the page. Add this BEFORE the block iteration loop, after computing `texts = [""] * len(boxes)`:

```python
        # Compute average line height for this page
        box_heights = [max(0.001, b[3] - b[1]) for b in boxes if len(b) >= 4]
        avg_line_h = sum(box_heights) / len(box_heights) if box_heights else 0.02
```

This should be inserted after `texts = [""] * len(boxes)` and before `for block in blocks:`.

- [ ] **Step 4: Verify no syntax errors**

```bash
python -m py_compile backend\engine\pdf_api_embed.py
```

Work from: `D:\opencode\book-downloader`
Expected: silent success.

- [ ] **Step 5: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/pdf_api_embed.py
git commit -m "feat: equal-chunk line splitting by block height in allocate_text_to_surya_boxes"
```

---

### Task 2: End-to-end test with 2.pdf

**Files:**
- Create: (test script, temporary — don't commit)

- [ ] **Step 1: Write test script**

Create `C:\Users\ADMINI~1\AppData\Local\Temp\opencode\test_equal_split.py`:

```python
import asyncio, os, sys, time
PROJECT_ROOT = r"D:\opencode\book-downloader"
sys.path.insert(0, PROJECT_ROOT)
TOKEN_MINERU = "YOUR_MINERU_TOKEN"
PDF = r"C:\Users\Administrator\Downloads\2.pdf"
OUT = r"C:\Users\Administrator\Downloads\2_equal_split.pdf"

async def main():
    from backend.engine.surya_detect import run_surya_detect
    from backend.engine.mineru_client import MinerUClient, parse_layout_from_zip
    from backend.engine.pdf_api_embed import allocate_text_to_surya_boxes, embed_with_surya_boxes

    t0 = time.time()

    print("1. Surya detection...")
    surya_boxes = await run_surya_detect(PDF, dpi=200)
    print(f"   {sum(len(v) for v in surya_boxes.values())} boxes")

    print("2. MinerU API...")
    client = MinerUClient(token=TOKEN_MINERU)
    try:
        with open(PDF, "rb") as f:
            pdf_bytes = f.read()
        zip_bytes = await client.process_pdf(pdf_bytes, file_name=os.path.basename(PDF), model_version="vlm")
        layout = parse_layout_from_zip(zip_bytes)
    finally:
        await client.close()
    print(f"   {sum(len(v) for v in layout.values())} blocks")

    print("3. Equal-chunk allocation...")
    page_texts = allocate_text_to_surya_boxes(surya_boxes, layout)
    matched = sum(1 for v in page_texts.values() for t in v if t)
    all_boxes = sum(len(v) for v in page_texts.values())
    print(f"   {matched}/{all_boxes} matched")

    # Show sample
    for i in range(min(5, len(page_texts.get(0, [])))):
        t = page_texts[0][i][:50] if page_texts[0][i] else "<empty>"
        print(f"   box[{i}]: {t!r}")

    print("4. Embedding...")
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, embed_with_surya_boxes, PDF, OUT, surya_boxes, page_texts)
    print(f"   Output: {OUT} ({os.path.getsize(OUT)} bytes)")

    import fitz
    doc = fitz.open(OUT)
    for p in range(len(doc)):
        print(f"   P{p}: {len(doc[p].get_text('text'))} chars")
    doc.close()
    print(f"\nDONE {time.time()-t0:.1f}s — Open: {OUT}")

asyncio.run(main())
```

- [ ] **Step 2: Run the test**

```bash
D:\opencode\book-downloader\backend\venv\Scripts\python.exe C:\Users\ADMINI~1\AppData\Local\Temp\opencode\test_equal_split.py
```

Expected: matched box count, sample text shown per box, output PDF.

- [ ] **Step 3: User review**

Open `C:\Users\Administrator\Downloads\2_equal_split.pdf`. Compare text line breaks with `2_page0_surya.png` red boxes. Verify each selected line contains a complete text chunk (not a width-scaled fragment).

---

### Self-Review

**1. Spec coverage:**
- Replace width-proportional with line-count-based equal splitting → Task 1
- Test → Task 2

**2. Placeholder scan:** No TBD/TODO. All code shown in full.

**3. Type consistency:**
- `avg_line_h` is `float`, computed from normalized Surya box heights
- `est_lines` is `int` from `round()`
- `matching` type unchanged: `list[tuple[int, float]]`
- Return type unchanged: `Dict[int, List[str]]`
- All existing callers (MinerU pipeline, PaddleOCR pipeline) use the same function signature — no breaking changes
