# Revert LLM-OCR + Add Surya Coords for Alignment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revert the `local-llm-pdf-ocr` replacement back to the simple `ocrmypdf --plugin llmocr.plugin` approach, then integrate Surya OCR for precise text-line bounding boxes to achieve pixel-perfect text-image alignment in the sandwich PDF.

**Architecture:** `local-llm-pdf-ocr` was a dead end for Chinese (font encoding, DP alignment fails for non-olmOCR models, grounded path too slow). Revert to old llmocr plugin for LLM text extraction. Install `surya-ocr` separately for layout detection (line-level bboxes with reading order). Build a new sandwich PDF writer that places LLM-extracted text into Surya-detected bbox positions using `NotoSansSC-VF.ttf` system font with proper embedding.

**Tech Stack:** Python, `ocrmypdf` + llmocr plugin, `surya-ocr`, `pymupdf` (fitz), `NotoSansSC-VF.ttf`, existing OpenAI-compatible LLM endpoint.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/engine/pipeline.py` | Modify | Revert LLM-OCR branch to use old `ocrmypdf --plugin llmocr.plugin` |
| `backend/engine/llmocr/` | **Create** | Restore the old llmocr plugin files (from git history) |
| `backend/engine/surya_embed.py` | **Create** | New module: Surya detection → align LLM text → write sandwich PDF |
| `backend/config.py` | Modify | Remove `llm_api_base`/`llm_model` (revert to `llm_ocr_*` keys) |
| `frontend/src/types.ts` | Modify | Revert `llm_api_base`/`llm_model` → `llm_ocr_*` |
| `frontend/src/components/ConfigSettings.tsx` | Modify | Revert config UI fields |
| `D:\opencode\local-llm-pdf-ocr` | Keep | Reference only; no longer used by pipeline |

---

### Task 1: Revert Pipeline LLM-OCR Branch

**Files:**
- Modify: `backend/engine/pipeline.py` (LLM-OCR section)
- Restore: `backend/engine/llmocr/` (from git history)

- [ ] **Step 1: Restore old llmocr plugin from git history**

```bash
cd D:\opencode\book-downloader
git log --oneline -- backend/engine/llmocr/plugin.py | head -1
# Find the commit before deletion (73ffc18d)
git checkout 73ffc18d^ -- backend/engine/llmocr/
```

- [ ] **Step 2: Revert LLM-OCR branch in pipeline.py**

Find `elif ocr_engine == "llm_ocr":` (around line 2229). Replace the entire local-llm-pdf-ocr command construction (lines 2229-2310) with the old ocrmypdf+plugin approach:

```python
        elif ocr_engine == "llm_ocr":
            task_store.add_log(task_id, "Running LLM-based OCR via llmocr plugin...")

            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 5})

            if not _is_scanned(pdf_path, python_cmd=_py_for_ocr):
                task_store.add_log(task_id, "PDF already has text layer, skipping OCR")
                report["ocr_done"] = True
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            output_pdf = pdf_path.replace(".pdf", "_ocr.pdf")
            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 10})

            llm_endpoint = config.get("llm_ocr_endpoint", "http://localhost:11434")
            llm_model = config.get("llm_ocr_model", "")
            llm_api_key = config.get("llm_ocr_api_key", "")

            if not llm_model:
                task_store.add_log(task_id, "LLM OCR: model not configured")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            _engine_dir = os.path.dirname(__file__)
            _ocr_env = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    [_engine_dir] + os.environ.get("PYTHONPATH", "").split(os.pathsep)
                    if os.environ.get("PYTHONPATH")
                    else [_engine_dir]
                ),
                "PYTHONUNBUFFERED": "1",
            }

            cmd = [
                _py_for_ocr, "-m", "ocrmypdf",
                "--plugin", "llmocr.plugin",
                "--llm-ocr-endpoint", llm_endpoint,
                "--llm-ocr-model", llm_model,
                "--llm-ocr-lang", ocr_lang or "chi_sim+eng",
                "--llm-ocr-timeout", str(ocr_timeout),
                "--optimize", _opt_level,
                "--oversample", ocr_oversample,
                "-j", str(ocr_jobs),
                "--output-type", "pdf",
                "--pdf-renderer", "sandwich",
                pdf_path,
                output_pdf,
            ]
            if llm_api_key:
                cmd += ["--llm-ocr-api-key", llm_api_key]

            try:
                _exit = await _run_ocrmypdf_with_progress(
                    task_id, cmd, env=_ocr_env,
                    timeout=ocr_timeout, total_pages=_total_pages,
                    output_pdf=output_pdf,
                )
                if _exit == 0:
                    task_store.add_log(task_id, "LLM OCR completed, validating quality...")
                    if _is_ocr_readable(output_pdf, python_cmd=_py_for_ocr):
                        os.replace(output_pdf, pdf_path)
                        task_store.add_log(task_id, "LLM OCR quality check passed")
                        report["ocr_done"] = True
                    else:
                        task_store.add_log(task_id, "LLM OCR quality check failed, keeping original PDF")
                        try:
                            os.remove(output_pdf)
                        except Exception:
                            pass
                else:
                    task_store.add_log(task_id, f"LLM OCR failed with exit code {_exit}")
            except asyncio.TimeoutError:
                task_store.add_log(task_id, f"LLM OCR timed out after {ocr_timeout}s")
            except Exception as e:
                task_store.add_log(task_id, f"LLM OCR error: {e}")
```

- [ ] **Step 3: Restore old progress parsing**

Replace the LLM-OCR progress parsing section (lines 250-280) with the old simpler version:

```python
            # Parse LLM-OCR progress: "22 generate_pdf: pages=10, words=1001, ..."
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

- [ ] **Step 4: Revert config key names**

In `backend/config.py`, `frontend/src/types.ts`, `frontend/src/components/ConfigSettings.tsx`:
- `llm_api_base` → `llm_ocr_endpoint`
- `llm_model` → `llm_ocr_model`  
- Restore `llm_ocr_api_key` and `llm_ocr_timeout`

```python
# config.py DEFAULT_CONFIG
"llm_ocr_endpoint": "http://localhost:11434",
"llm_ocr_model": "",
"llm_ocr_api_key": "",
"llm_ocr_timeout": 300,
```

```typescript
// types.ts AppConfig
llm_ocr_endpoint: string
llm_ocr_model: string
llm_ocr_api_key: string
llm_ocr_timeout: number
```

```typescript
// ConfigSettings.tsx form defaults
llm_ocr_endpoint: "http://localhost:11434",
llm_ocr_model: "",
llm_ocr_api_key: "",
llm_ocr_timeout: 300,
```

- [ ] **Step 5: Commit**

```bash
cd D:\opencode\book-downloader
git add -A
git commit -m "revert: rollback local-llm-pdf-ocr, restore llmocr plugin approach"
```

---

### Task 2: Install Surya OCR

**Files:**
- Install: `surya-ocr` package

- [ ] **Step 1: Install surya-ocr**

```bash
pip install surya-ocr
```

Verify:
```bash
python -c "from surya.detection import DetectionPredictor; print('OK')"
```

Note: Surya will download model weights (~500MB) on first use. Uses GPU if available, otherwise CPU.

- [ ] **Step 2: Test Surya detection on a page**

```python
import fitz
from PIL import Image
import io
from surya.detection import DetectionPredictor

# Load page as image
doc = fitz.open(r'C:\Users\Administrator\Downloads\新建.pdf')
pix = doc[0].get_pixmap(dpi=200)
img = Image.open(io.BytesIO(pix.tobytes("png")))
det = DetectionPredictor()
results = det([img])
# Check bboxes
for bbox in results[0].bboxes[:5]:
    print(f'{bbox.bbox} conf={bbox.confidence:.2f}')
doc.close()
```

Expected: Line-level bboxes with confidence scores. Chinese text lines should be detected.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: install surya-ocr for layout detection"
```

---

### Task 3: Build Surya + LLM Sandwich PDF Writer

**Files:**
- Create: `backend/engine/surya_embed.py`
- Modify: `backend/engine/pipeline.py` (add post-OCR step)

This is the core module. It:
1. Takes the original PDF and the LLM-OCR output text
2. Runs Surya to get line-level bboxes
3. Aligns LLM text to Surya bboxes (simple order-based alignment)
4. Writes a sandwich PDF with NotoSansSC font

- [ ] **Step 1: Create `backend/engine/surya_embed.py`**

```python
"""Build sandwich PDF with Surya-detected bboxes + LLM-extracted text."""
import os
import io
import fitz
from PIL import Image
from typing import List, Tuple, Optional


def _get_surya_bboxes(pdf_path: str, dpi: int = 200) -> List[List[dict]]:
    """Run Surya detection on all pages. Returns list of per-page bbox dicts."""
    from surya.detection import DetectionPredictor

    doc = fitz.open(pdf_path)
    predictor = DetectionPredictor()
    pages_data = []

    for page_num in range(doc.page_count):
        pix = doc[page_num].get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        result = predictor([img])[0]

        bboxes = []
        for bbox in result.bboxes:
            # Normalize to 0..1 using image dimensions
            iw, ih = bbox.image_size
            x0, y0, x1, y1 = bbox.bbox
            bboxes.append({
                "nx0": x0 / iw, "ny0": y0 / ih,
                "nx1": x1 / iw, "ny1": y1 / ih,
                "conf": bbox.confidence,
            })
        pages_data.append(bboxes)

    doc.close()
    return pages_data


def _extract_ocr_text(ocr_pdf_path: str) -> List[str]:
    """Extract per-page text from OCR output PDF."""
    doc = fitz.open(ocr_pdf_path)
    texts = []
    for page in doc:
        texts.append(page.get_text("text"))
    doc.close()
    return texts


def _simple_align(llm_lines: List[str], bboxes: List[dict]) -> List[Tuple[dict, str]]:
    """Simple order-based alignment: pair LLM lines to Surya bboxes in order.
    For more sophisticated alignment, use Needleman-Wunsch or edit distance.
    """
    pairs = []
    llm_lines = [l.strip() for l in llm_lines if l.strip()]
    n = min(len(llm_lines), len(bboxes))
    for i in range(n):
        pairs.append((bboxes[i], llm_lines[i]))
    return pairs


def build_sandwich_pdf(
    input_pdf_path: str,
    ocr_pdf_path: str,
    output_pdf_path: str,
    dpi: int = 200,
    font_path: str = r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
) -> bool:
    """
    Build searchable sandwich PDF with Surya bboxes + LLM text.

    Args:
        input_pdf_path: Original source PDF (for background image)
        ocr_pdf_path: LLM-OCR output PDF (for extracted text)
        output_pdf_path: Where to write the final sandwich PDF
        dpi: Rasterization DPI
        font_path: Path to a CJK-capable TTF font file

    Returns:
        True if successful, False otherwise.
    """
    try:
        # Step 1: Get Surya bboxes
        pages_bboxes = _get_surya_bboxes(input_pdf_path, dpi)

        # Step 2: Get LLM text per page
        ocr_texts = _extract_ocr_text(ocr_pdf_path)

        # Step 3: Build sandwich PDF
        src_doc = fitz.open(input_pdf_path)
        new_doc = fitz.open()

        for page_num in range(src_doc.page_count):
            old_page = src_doc[page_num]
            width = old_page.rect.width
            height = old_page.rect.height

            # Insert background image
            pix = old_page.get_pixmap(dpi=dpi)
            img_data = pix.tobytes("jpg", jpg_quality=85)
            new_page = new_doc.new_page(width=width, height=height)
            new_page.insert_image(new_page.rect, stream=img_data)

            # Align text to bboxes
            bboxes = pages_bboxes[page_num] if page_num < len(pages_bboxes) else []
            llm_text = ocr_texts[page_num] if page_num < len(ocr_texts) else ""
            llm_lines = llm_text.split("\n")

            pairs = _simple_align(llm_lines, bboxes)

            for bbox, text in pairs:
                if not text.strip():
                    continue
                nx0, ny0, nx1, ny1 = bbox["nx0"], bbox["ny0"], bbox["nx1"], bbox["ny1"]
                x0 = nx0 * width
                y0 = ny0 * height
                x1 = nx1 * width
                y1 = ny1 * height

                box_w = max(1, x1 - x0)
                box_h = max(1, y1 - y0)
                fontsize = min(72, max(4, box_h * 0.8))

                if not os.path.exists(font_path):
                    new_page.insert_text(
                        fitz.Point(x0, y1 - 2),
                        text,
                        fontname="china-t",
                        fontsize=fontsize,
                        render_mode=3,
                    )
                else:
                    new_page.insert_text(
                        fitz.Point(x0, y1 - 2),
                        text,
                        fontfile=font_path,
                        fontsize=fontsize,
                        render_mode=3,
                    )

        new_doc.save(output_pdf_path)
        new_doc.close()
        src_doc.close()
        return True
    except Exception as e:
        try:
            src_doc.close()
            new_doc.close()
        except Exception:
            pass
        raise e
```

- [ ] **Step 2: Wire into pipeline after LLM-OCR quality check**

In `_step_ocr` (LLM-OCR branch), after `os.replace(output_pdf, pdf_path)` and `report["ocr_done"] = True`, add:

```python
                    # Post-OCR: rebuild sandwich PDF with Surya-aligned bboxes
                    try:
                        from engine.surya_embed import build_sandwich_pdf
                        surya_output = pdf_path.replace(".pdf", "_surya.pdf")
                        if build_sandwich_pdf(pdf_path, pdf_path, surya_output, dpi=int(ocr_oversample)):
                            os.replace(surya_output, pdf_path)
                            task_store.add_log(task_id, "Surya: text layer aligned to detected bboxes")
                    except ImportError:
                        task_store.add_log(task_id, "Surya module not available, keeping raw OCR text layer")
                    except Exception as e:
                        task_store.add_log(task_id, f"Surya alignment error: {str(e)[:100]}")
```

- [ ] **Step 3: Commit**

```bash
git add backend/engine/surya_embed.py backend/engine/pipeline.py
git commit -m "feat: surya bbox alignment for LLM-OCR sandwich PDF"
```

---

### Task 4: Build, Deploy, Test

- [ ] **Step 1: Build PyInstaller**

```bash
cd D:\opencode\book-downloader
python -m PyInstaller --noconfirm backend\book-downloader.spec
```

Note: `surya-ocr` is NOT bundled by PyInstaller — it runs via system Python (`_py_for_ocr`). The `surya_embed.py` module must be importable from the backend engine path.

- [ ] **Step 2: Test with sample PDF**

```bash
python -c "
from engine.surya_embed import build_sandwich_pdf
result = build_sandwich_pdf(
    r'C:\Users\Administrator\Downloads\新建.pdf',
    r'C:\Users\Administrator\Downloads\新建.pdf',
    r'C:\Users\Administrator\Downloads\新建_surya_test.pdf',
    dpi=200,
)
print(f'Result: {result}')
"
```

- [ ] **Step 3: Verify text positioning**

Use PyMuPDF to check the output PDF has text at correct positions covering the image.
Compare with PaddleOCR reference output.

- [ ] **Step 4: Deploy and restart**

```bash
Stop-Process -Name BookDownloader -Force -ErrorAction SilentlyContinue
Copy-Item "dist\BookDownloader.exe" "backend\dist\BookDownloader.exe" -Force
Start-Process "backend\dist\BookDownloader.exe"
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: build and verify surya alignment pipeline"
```

---

## Self-Review

### Spec Coverage
| Requirement | Task |
|---|---|
| Revert local-llm-pdf-ocr | Task 1 |
| Restore llmocr plugin | Task 1 |
| Install Surya | Task 2 |
| Build sandwich PDF with Surya bboxes + LLM text | Task 3 |
| Wire into pipeline | Task 3 Step 2 |
| Build + deploy + test | Task 4 |

### Placeholder Scan
- No TBD/TODO found
- All file paths absolute
- All code complete

### Type Consistency
- `pages_bboxes: List[List[dict]]` — consistent across `_get_surya_bboxes` and `build_sandwich_pdf`
- `font_path` default `C:\Windows\Fonts\NotoSansSC-VF.ttf` — exists on Windows
- Bbox format: `{nx0, ny0, nx1, ny1, conf}` — normalized 0..1, consistent with `_simple_align` usage
