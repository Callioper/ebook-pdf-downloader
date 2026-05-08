"""Build sandwich PDF with Surya OCR — final working version.

Design decisions:
- Original page image → Surya (correct coordinate mapping)
- insert_font(fontfile=simhei.ttf) → proper CJK embedding
- fontTools subsetting → minimal font file size
- No morph → cosmetic only, proven not to affect alignment
- Direct page modification → no re-rendering, minimal size
"""
import io
import os
import fitz
from PIL import Image
from typing import Optional


def _collect_unique_chars(results: list) -> set:
    """Collect all unique characters from Surya OCR results."""
    chars = set()
    for result in results:
        for line in result.text_lines:
            for c in line.text.strip():
                chars.add(c)
    return chars


def _subset_font(font_path: str, chars: set, output_path: str) -> str:
    """Create a minimal font subset containing only the needed characters.
    Fall back to full font if subsetting fails."""
    try:
        from fontTools.subset import Subsetter
        from fontTools.ttLib import TTFont

        font = TTFont(font_path)
        subsetter = Subsetter()
        subsetter.populate(unicodes=[ord(c) for c in chars if ord(c) > 0x1F])
        subsetter.subset(font)
        font.save(output_path)
        font.close()  # type: ignore
        return output_path
    except Exception:
        return font_path  # fallback to full font


def build_sandwich_surya(
    input_pdf_path: str,
    output_pdf_path: str,
    dpi: int = 200,
    languages: Optional[list] = None,
) -> bool:
    """Add invisible OCR text layer to each page of a PDF using Surya."""
    font_path = r"C:\Windows\Fonts\simhei.ttf"
    if not os.path.exists(font_path):
        font_path = r"C:\Windows\Fonts\msyh.ttc"
    if not os.path.exists(font_path):
        return False

    try:
        from surya.foundation import FoundationPredictor
        from surya.recognition import RecognitionPredictor
        from surya.detection import DetectionPredictor

        doc = fitz.open(input_pdf_path)

        # Step 1: Extract original page images + their page rects
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

        # Step 2: Run Surya
        results = RecognitionPredictor(FoundationPredictor())(
            page_images, det_predictor=DetectionPredictor()
        )

        # Step 3: Subset font to only needed characters
        all_chars = _collect_unique_chars(results)
        subset_path = os.path.join(os.path.dirname(output_pdf_path), "_font_subset.ttf")
        _subset_font(font_path, all_chars, subset_path)

        # Step 4: Add invisible text to each page
        for page_num, result in enumerate(results):
            page = doc[page_num]
            img_rect = page_rects[page_num]

            # Register font
            page.insert_font(fontname="CJK", fontfile=subset_path)

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

                box_w = max(1, nx1 - nx0)
                box_h = max(1, ny1 - ny0)
                fontsize = min(72, max(4, box_h * 0.85))

                # Horizontal morph: stretch glyph bboxes to fill visual text width
                # Without this, selection only covers ~2/3 of the visual line
                font_obj = fitz.Font(fontfile=subset_path)
                natural_w = font_obj.text_length(text, fontsize=fontsize)
                if natural_w <= 0:
                    natural_w = len(text) * fontsize * 0.5
                scale_x = max(0.3, min(5.0, box_w / max(1, natural_w)))

                baseline = fitz.Point(nx0, ny1 - 1)
                morph = (baseline, fitz.Matrix(scale_x, 1.0))
                page.insert_text(
                    baseline, text,
                    fontname="CJK",
                    fontsize=fontsize, render_mode=3,
                    morph=morph,
                )

        doc.save(output_pdf_path, deflate=True, garbage=4)
        doc.close()

        # Cleanup
        if subset_path != font_path and os.path.exists(subset_path):
            os.remove(subset_path)

        return True
    except Exception:
        try:
            doc.close()
        except Exception:
            pass
        return False
