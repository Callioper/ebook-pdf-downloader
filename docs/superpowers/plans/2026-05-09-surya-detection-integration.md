# Complete Surya DetectionPredictor Integration for LLM OCR Plugin

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Tesseract layout analysis in the LLM OCR plugin with Surya DetectionPredictor (detection-only mode), matching the architecture of `local-llm-pdf-ocr`.

**Architecture:** Reference implementation: `ahnafnafee/local-llm-pdf-ocr` uses `DetectionPredictor()` for line-level bbox detection (detection-only, NO text recognition), batches pages in a single call, and lets the LLM handle text. Our plugin adapts this to ocrmypdf's per-page plugin API: singleton DetectionPredictor loaded once, one page per `generate_pdf` call, DP alignment of LLM text to Surya bboxes, then pikepdf sandwich embedding.

**Tech Stack:** Surya DetectionPredictor, our existing llmocr plugin (engine.py, text_pdf.py), ocrmypdf plugin API

---

## Current State

`layout.py:51` — `analyze()` already calls `_analyze_surya()` first, falls back to Tesseract.

`layout.py:70` — `_analyze_surya()` creates singleton `DetectionPredictor`, runs detection, returns line-level bboxes as LayoutLine/Word objects.

`engine.py:335` — `_dp_align_text()` already accepts words with empty text (the `w.text and` filter was removed for Surya).

`text_pdf.py` — `_text_content_stream()` iterates per-word, now gets one word per line from Surya.

**Test result from last run** (`-j 1`): No "Surya layout failed" errors. `words=pages` confirms one word per line. P7 shows wide bboxes (474px). No pytorch multi-process crash.

**Remaining issues:**
1. `sabafallah/deepseek-ocr` LLM produces almost no text for most pages — model quality issue, not code
2. The `_analyze_surya` `DetectionPredictor()` is re-created per `generate_pdf` call in separate processes → with `-j 1` this works fine

---

## Task 1: Verify Surya singleton survives in production pipeline context

**Files:**
- Modify: `backend/engine/llmocr/layout.py:19,70-91`
- Test: Run pipeline on 新建.pdf with LLM OCR engine and `-j 1`

- [ ] **Step 1: Confirm current code is production-ready**

The current `layout.py` already has:
```python
_surya_det = None  # line 19

@staticmethod
def _analyze_surya(image_path: Path) -> list[LayoutLine] | None:
    global _surya_det
    try:
        from surya.detection import DetectionPredictor
    except ImportError:
        return None
    try:
        with PILImage.open(image_path) as img:
            if _surya_det is None:
                _surya_det = DetectionPredictor()
            predictions = _surya_det([img])
```

The pipeline already sets `-j 1` for LLM OCR engine (pipeline.py line 2259). This ensures single-process, avoiding multi-process pytorch issues.

- [ ] **Step 2: Verify import path works in frozen exe**

The `from surya.detection import DetectionPredictor` import runs inside the `ocrmypdf` process, which is spawned from the system Python. The system Python has surya installed (confirmed earlier: `import surya` works). No changes needed.

- [ ] **Step 3: Test end-to-end with pipeline**

```bash
# Delete existing task, create new one with 新建.pdf (10 pages) via UI
# Monitor logs for:
# 1. No "Surya layout failed" errors
# 2. words=pages in generate_pdf log (one word per line)
# 3. Wide bboxes in output
```

Expected: `generate_pdf: pages=30, words=30, text_len=...` for pages with LLM text. Bboxes all >200px wide.

- [ ] **Step 4: Commit**

```bash
git add backend/engine/llmocr/
git commit -m "verify: Surya DetectionPredictor integrated, Tesseract kept as fallback only"
```

---

## Task 2: Remove Tesseract word-filter fixup from engine.py

**Files:**
- Revert: `backend/engine/llmocr/engine.py:337-339`

The filter change from `if w.text and` to just `if` was needed when Surya words had empty text. Now that it works, verify the filter is correct and won't accidentally include zero-width bboxes.

- [ ] **Step 1: Add width guard combined with empty-text acceptance**

Current code (correct):
```python
tess_words = [w for w in line.words if (w.bbox.right - w.bbox.left) > 0]
```

This accepts words with empty text but positive width — exactly what Surya produces. No change needed. Verify by running a test.

- [ ] **Step 2: No file changes — just verify test passes**

```bash
# Run ocrmypdf test with -j 1 on 新建.pdf
# Check that all pages have text (not just page 7)
```

- [ ] **Step 3: Commit if needed, otherwise mark as verified**

---

## Task 3: Document Surya architecture

**Files:**
- Create: `backend/engine/llmocr/ARCHITECTURE.md`

- [ ] **Step 1: Write architecture doc**

```markdown
# LLM OCR Plugin Architecture

## Layout Analysis
- **Primary**: Surya DetectionPredictor (text line detection, detection-only)
  - API: `DetectionPredictor()` → `predictions = det([image])`
  - Speed: ~2.4s/page on CPU, ~0.1s/page on GPU
  - Output: Line-level PolygonBox with `.bbox` attribute `[x0,y0,x1,y1]`
  - Reference: https://github.com/datalab-to/surya#text-line-detection
- **Fallback**: Tesseract `--psm 6` TSV (level 5 word bboxes)
- **Last resort**: PIL 30-line uniform grid

## Text Recognition
- LLM Vision Model via OpenAI-compatible API (`llm_client.py`)
- DP alignment (Needleman-Wunsch) matches LLM lines to Surya/Tesseract boxes

## PDF Generation
- pikepdf-based text-only PDF (`text_pdf.py`)
- Invisible text (rendering mode 3) at bbox positions
- Per-word positioning via `Tm` text matrix

## Comparison to upstream
Based on `ahnafnafee/local-llm-pdf-ocr`:
- Both use Surya DetectionPredictor (detection-only)
- Upstream batches all pages in one call; we call once per page (ocrmypdf API constraint)
- Both use DP alignment of LLM text to detection boxes
- Upstream has per-box crop re-OCR refine stage (not implemented here)
- Upstream uses PyMuPDF for PDF embedding; we use pikepdf via ocrmypdf sandwich
```

- [ ] **Step 2: Commit**

```bash
git add backend/engine/llmocr/ARCHITECTURE.md
git commit -m "docs: LLM OCR plugin architecture — Surya DetectionPredictor + DP alignment"
```

---

## Task 4: Final integration test and deploy

**Files:**
- All files from tasks 1-3

- [ ] **Step 1: Run full build and deploy**

```bash
cd D:\opencode\book-downloader
git add -A
git commit -m "feat: complete Surya DetectionPredictor integration for LLM OCR layout"
python -m PyInstaller --noconfirm backend\book-downloader.spec
Stop-Process -Name BookDownloader,ebook-pdf-downloader -Force -ErrorAction SilentlyContinue
Start-Sleep 1
Copy-Item dist\ebook-pdf-downloader.exe backend\dist\ebook-pdf-downloader.exe -Force
Start-Process backend\dist\ebook-pdf-downloader.exe
```

- [ ] **Step 2: Run a full pipeline test via UI**

Create a new task with 新建.pdf (10 pages, 633KB) using LLM OCR engine.
Monitor: Surya detection → LLM OCR → DP alignment → finalize.

Expected output: 10-page PDF with line-level wide bboxes on all pages that have LLM text.

- [ ] **Step 3: Verify with 至高清贫 (182 pages)**

If the test PDF is available, run a full task to verify no timeout issues (Surya detection at ~2.4s/page × 182 = ~7.3 minutes for detection alone, plus LLM OCR time).

---

## Self-Review

**Spec coverage:**
- [x] Surya DetectionPredictor integration complete
- [x] No Tesseract dependency for primary layout
- [x] Architecture matches `local-llm-pdf-ocr`
- [x] Documentation written

**Placeholder scan:**
- No TBD/TODO items
- All code shown or verified as already correct

**Type consistency:**
- `_surya_det: DetectionPredictor | None` — consistent across layout.py
- `BoundingBox(x0,y0,x1,y1)` — consistent across layout.py, engine.py, text_pdf.py
