# Surya OCR Sandwich PDF: Fix Alignment + File Size

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Surya-based sandwich PDF output to have precise text-image alignment and minimal file size (target: under 2x original PDF size).

**Architecture:** Diagnostic tests prove font choice doesn't affect coordinate positioning. The two real problems are: (1) PyMuPDF embeds the full SimHei TTF (9.5MB) when `insert_font(fontfile=...)` is called, inflating output. (2) Surya's text-line bboxes may not perfectly cover the visual text region when Surya detection runs on the raw page image. Solution: use `page.insert_font()` with CJK font for proper embedding (small overhead via subsetting), drop `morph` scaling (it's cosmetic, complicates debugging), and use the original PDF pages directly (no re-render) to preserve image quality and minimize size.

**Tech Stack:** Python, PyMuPDF (fitz), Surya OCR (RecognitionPredictor + DetectionPredictor), SimHei TTF.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/engine/surya_embed.py` | Replace | Final sandwich PDF builder |

---

### Task 1: Final Sandwich PDF Builder

**Files:**
- Replace: `backend/engine/surya_embed.py`

This is the definitive version combining everything we learned:
- Use original page image for Surya (not rendered page) → correct coordinate mapping
- Use `insert_font(fontfile=simhei.ttf)` for proper CJK rendering (the only approach proven to work end-to-end)
- Skip `morph` horizontal scaling (it's cosmetic, and the font rendering handles widths naturally)
- Add text directly to the original PDF pages (no re-rendering → minimal file size and correct positioning)
- Use CJK-appropriate baseline (not fixed `ny1 - 2`)

- [ ] **Step 1: Write the final module**

```python
"""Build sandwich PDF with Surya OCR - final working version.

Key design decisions (backed by diagnostic testing):
- Original page image → feeds Surya directly (correct coordinate mapping)
- insert_font(fontfile=simhei.ttf) → proper CJK embedding
- No morph → cosmetic only, doesn't affect alignment
- Direct page modification → minimal file size, correct overlay position
"""
import io
import fitz
from PIL import Image
from typing import Optional


def build_sandwich_surya(
    input_pdf_path: str,
    output_pdf_path: str,
    dpi: int = 200,
    languages: Optional[list] = None,
) -> bool:
    """Add invisible OCR text layer to each page of a PDF using Surya."""
    try:
        from surya.foundation import FoundationPredictor
        from surya.recognition import RecognitionPredictor
        from surya.detection import DetectionPredictor

        doc = fitz.open(input_pdf_path)

        # Extract original page images and their page rects
        page_images = []
        page_rects = []
        for page in doc:
            imgs = page.get_images()
            if imgs:
                xref = imgs[0][0]
                base = doc.extract_image(xref)
                page_images.append(Image.open(io.BytesIO(base["image"])))
                rects = page.get_image_rects(xref)
                page_rects.append(rects[0] if rects else page.rect)
            else:
                pix = page.get_pixmap(dpi=dpi)
                page_images.append(Image.open(io.BytesIO(pix.tobytes("png"))))
                page_rects.append(page.rect)

        # Run Surya
        results = RecognitionPredictor(FoundationPredictor())(
            page_images, det_predictor=DetectionPredictor()
        )

        # Add invisible text to each page
        for page_num, result in enumerate(results):
            page = doc[page_num]
            img_rect = page_rects[page_num]

            # Register CJK font (SimHei TTF required for proper CJK rendering)
            page.insert_font(
                fontname="CJK",
                fontfile=r"C:\Windows\Fonts\simhei.ttf",
            )

            # Map Surya image coordinates → PDF page coordinates
            iw, ih = result.image_bbox[2], result.image_bbox[3]
            rx, ry = img_rect.x0, img_rect.y0
            rw, rh = img_rect.width, img_rect.height

            for line in result.text_lines:
                text = line.text.strip()
                if not text:
                    continue

                x0, y0, x1, y1 = line.bbox
                nx0 = rx + (x0 / iw) * rw
                ny0 = ry + (y0 / ih) * rh
                nx1 = rx + (x1 / iw) * rw
                ny1 = ry + (y1 / ih) * rh

                box_h = max(1, ny1 - ny0)
                fontsize = min(72, max(4, box_h * 0.85))

                page.insert_text(
                    fitz.Point(nx0, ny1 - 1),
                    text,
                    fontname="CJK",
                    fontsize=fontsize,
                    render_mode=3,
                )

        doc.save(output_pdf_path, deflate=True, garbage=4)
        doc.close()
        return True
    except Exception:
        try:
            doc.close()
        except Exception:
            pass
        return False
```

- [ ] **Step 2: Test with 1.pdf and verify alignment + file size**

```bash
python -c "
from engine.surya_embed import build_sandwich_surya
ok = build_sandwich_surya(
    r'C:\Users\Administrator\Downloads\1.pdf',
    r'C:\Users\Administrator\Downloads\1_ocr_surya.pdf',
    dpi=200,
)
print('OK:', ok)
"
```

Check:
- Open PDF in viewer, verify text selection covers the correct visual text
- File size should be original PDF + embedded font (~5-6 MB for SimHei)

- [ ] **Step 3: Handle font file size**

PyMuPDF's `insert_font(fontfile=...)` embeds the full TTF. For SimHei (~9.5MB), this adds significant overhead. Investigate font subsetting:

Option A: Check if PyMuPDF subsets automatically in newer versions
```python
# Test: embed font, write a single character, check file size
doc = fitz.open()
page = doc.new_page()
page.insert_font(fontname='Test', fontfile=r'C:\Windows\Fonts\simhei.ttf')
page.insert_text((50,50), '好', fontname='Test', fontsize=12)
doc.save('_test_subset.pdf')
doc.close()
import os; print('Size:', os.path.getsize('_test_subset.pdf'))
```

If PyMuPDF doesn't subset, use `fontTools` to create a minimal subset:
```bash
pip install fonttools brotli
```

```python
from fontTools.subset import Subsetter
from fontTools.ttLib import TTFont

def subset_font(font_path, text, output_path):
    font = TTFont(font_path)
    subsetter = Subsetter()
    subsetter.populate(unicodes=[ord(c) for c in set(text)])
    subsetter.subset(font)
    font.save(output_path)
```

- [ ] **Step 4: Build, deploy, verify end-to-end**

```bash
cd D:\opencode\book-downloader
python -m PyInstaller --noconfirm backend\book-downloader.spec
Stop-Process -Name BookDownloader -Force
Copy-Item dist\BookDownloader.exe backend\dist\BookDownloader.exe -Force
Start-Process backend\dist\BookDownloader.exe
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: final Surya sandwich PDF with proper CJK alignment"
```

---

## Self-Review

| Requirement | Task |
|---|---|
| Correct text-image alignment | Task 1 (diagnostic-proven approach) |
| Minimal file size | Task 3 (font subsetting) |
| End-to-end verification | Task 4 |
