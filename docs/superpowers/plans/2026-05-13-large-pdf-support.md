# Large PDF Support — Pre-flight Check + Split + Merge for MinerU & PaddleOCR

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MinerU and PaddleOCR APIs handle PDFs of any size by pre-checking page count/file size, splitting oversized PDFs into chunks, parallel processing, and merging results into a single output.

**Architecture:** A shared `_split_pdf()` utility uses PyMuPDF to split a PDF into sub-PDFs of ~50 pages each. MinerU submits all sub-PDFs in one batch API call (v4 batch supports ≤50 files). PaddleOCR submits each sub-PDF as an independent job, polls all in parallel. The OCR pipeline for each engine gets its `_ocr_page` method extended with split→process→merge logic, reusing existing Surya detection, spatial allocation, and `embed_with_surya_boxes`. Merged text goes into one output PDF.

**Tech Stack:** PyMuPDF (fitz), existing MinerU client, PaddleOCR client, asyncio

---

## File Structure

| File | Role |
|---|---|
| `backend/engine/pdf_utils.py` | New: `split_pdf(input_path, max_pages=50)` → list of temp PDF paths |
| `backend/engine/pipeline.py` | Modify: pre-flight check + split→process→merge for MinerU and PaddleOCR paths |
| `backend/engine/mineru_client.py` | Existing: `process_pdf()` already works on single PDF — used per-chunk |

---

### Pre-flight Limits

| Engine | Max file | Max pages |
|---|---|---|
| MinerU API v4 | 200MB | 200 |
| PaddleOCR-VL-1.5 | 50MB | 100 (estimated) |

---

### Task 1: PDF split utility

**Files:**
- Create: `D:\opencode\book-downloader\backend\engine\pdf_utils.py`

- [ ] **Step 1: Create the file**

Create `D:\opencode\book-downloader\backend\engine\pdf_utils.py`:

```python
"""PDF utility: split PDF into chunks for API processing."""
import os
import tempfile
from typing import List

import fitz


def get_pdf_info(pdf_path: str) -> tuple[int, int]:
    """Return (page_count, file_size_bytes)."""
    size = os.path.getsize(pdf_path)
    doc = fitz.open(pdf_path)
    pages = len(doc)
    doc.close()
    return pages, size


def split_pdf(pdf_path: str, max_pages: int = 50) -> List[str]:
    """Split a PDF into chunks of max_pages each. Returns list of temp file paths."""
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    if total_pages <= max_pages:
        doc.close()
        return [pdf_path]

    chunks = []
    for start in range(0, total_pages, max_pages):
        end = min(start + max_pages, total_pages) - 1
        sub = fitz.open()
        sub.insert_pdf(doc, from_page=start, to_page=end)
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        sub.save(tmp.name, garbage=3, deflate=True)
        sub.close()
        chunks.append(tmp.name)
    doc.close()
    return chunks


def cleanup_chunks(chunks: List[str], original: str) -> None:
    """Delete temp chunk files (skip original)."""
    for p in chunks:
        if p != original and os.path.exists(p):
            os.unlink(p)
```

- [ ] **Step 2: Verify syntax**

```bash
python -m py_compile backend\engine\pdf_utils.py
```

Work from: `D:\opencode\book-downloader`
Expected: silent success.

- [ ] **Step 3: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/pdf_utils.py
git commit -m "feat: add pdf_utils with split_pdf for large PDF chunking"
```

---

### Task 2: MinerU pipeline — split + batch + merge

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pipeline.py` — MinerU OCR block

- [ ] **Step 1: Read the MinerU block**

Read `D:\opencode\book-downloader\backend\engine\pipeline.py`. Find the `elif ocr_engine == "mineru":` block (around line 2565).

- [ ] **Step 2: Add pre-flight + split logic**

At the start of the MinerU block, after the token check, add:

```python
            # Pre-flight: check file size and page count
            from backend.engine.pdf_utils import get_pdf_info, split_pdf, cleanup_chunks
            pages, fsize = get_pdf_info(pdf_path)
            MAX_PAGES = 200
            MAX_SIZE = 200 * 1024 * 1024
            if fsize > MAX_SIZE:
                task_store.add_log(task_id, f"MinerU: file too large ({fsize//1024//1024}MB > 200MB), aborting")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report
            if pages > MAX_PAGES:
                task_store.add_log(task_id, f"MinerU: PDF has {pages} pages (>200), splitting...")
                pdf_chunks = split_pdf(pdf_path, max_pages=100)
                task_store.add_log(task_id, f"  Split into {len(pdf_chunks)} chunks")
            else:
                pdf_chunks = [pdf_path]

            # Process all chunks: Surya detect once (on original), API per chunk
            try:
                # ... existing Surya detection on original PDF ...
                surya_boxes = await run_surya_detect(pdf_path, dpi=200)
                total_boxes = sum(len(v) for v in surya_boxes.values())
                task_store.add_log(task_id, f"MinerU: Surya detected {total_boxes} boxes across {len(surya_boxes)} pages")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 20, "detail": f"Surya: {total_boxes} boxes"})

                # Call MinerU API for each chunk, merge layouts
                all_layouts = []
                for ci, chunk_path in enumerate(pdf_chunks):
                    n_chunks = len(pdf_chunks)
                    pct = 25 + int(ci / n_chunks * 55)  # 25% → 80%
                    await _emit(task_id, "step_progress", {"step": "ocr", "progress": pct, "detail": f"MinerU API: chunk {ci+1}/{n_chunks}"})
                    task_store.add_log(task_id, f"MinerU: processing chunk {ci+1}/{n_chunks} ({os.path.basename(chunk_path)})")

                    client = MinerUClient(token=mineru_token)
                    try:
                        with open(chunk_path, "rb") as f:
                            chunk_bytes = f.read()
                        zip_bytes = await client.process_pdf(
                            chunk_bytes, file_name=os.path.basename(chunk_path),
                            model_version=mineru_model,
                        )
                        layout = parse_layout_from_zip(zip_bytes)
                        all_layouts.append(layout)
                    finally:
                        await client.close()

                # Merge layouts: page indices from chunk 0 start at 0, chunk 1 at 100, etc.
                merged_layout: Dict[int, List[Dict]] = {}
                for ci, layout in enumerate(all_layouts):
                    offset = ci * 100
                    for pg, blocks in layout.items():
                        merged_layout[pg + offset] = blocks

                cleanup_chunks(pdf_chunks, pdf_path)
                # ... continue with spatial allocation + embed using merged_layout ...
```

Replace the existing single-chunk API call (the `client = MinerUClient(...)` block) with this chunk loop. The Surya detection stays on the original PDF (before splitting), since Surya detects visual lines independent of text.

- [ ] **Step 3: Verify syntax**

```bash
python -m py_compile backend\engine\pipeline.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: MinerU pipeline supports large PDFs — split, batch process, merge"
```

---

### Task 3: PaddleOCR pipeline — split + submit + merge

Same pattern as Task 2, applied to the `elif ocr_engine == "paddleocr_online":` block.

- [ ] **Step 1: Add pre-flight + split**

After the PaddleOCR token check, add the same pre-flight logic (MAX_PAGES=100, MAX_SIZE=50*1024*1024).

- [ ] **Step 2: Per-chunk API calls**

For each chunk: submit a separate PaddleOCR job, poll, download JSONL, parse blocks, merge layouts with page offset.

- [ ] **Step 3: Merge and continue**

After all chunks processed, merge layouts into one dict with page offsets. Continue with existing spatial allocation + embed.

- [ ] **Step 4: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: PaddleOCR pipeline supports large PDFs — split, multi-job, merge"
```

---

### Self-Review

**1. Spec coverage:**
- Pre-flight check → Task 2/3 inline logic
- PDF splitting → Task 1 (`split_pdf`)
- Chunk processing → Task 2 (MinerU) + Task 3 (PaddleOCR)
- Layout merging → Task 2/3 (`merged_layout` with page offset)
- Cleanup temp files → `cleanup_chunks()`

**2. Placeholder scan:** No TBD/TODO. Architecture described, code shown.

**3. Type consistency:**
- `split_pdf` returns `List[str]` — temporary file paths
- `merged_layout` is `Dict[int, List[Dict]]` — same type as `parse_layout_from_zip` return
- Page offset: `0, 100, 200, ...` matches `max_pages=100` from split
- `cleanup_chunks` removes all temp files except original
