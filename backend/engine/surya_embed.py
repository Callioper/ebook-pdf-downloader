"""Build sandwich PDF with Surya OCR (detection + recognition).

Uses Surya's full OCR pipeline which outputs text_lines with text+bbox+confidence.
Extracts the original page image for Surya input to ensure correct coordinate
mapping when the image has an offset on the PDF page.
"""
import os
import io
import fitz
from PIL import Image
from typing import List, Optional


def build_sandwich_surya(
    input_pdf_path: str,
    output_pdf_path: str,
    dpi: int = 200,
    font_path: str = "",
    languages: Optional[List[str]] = None,
) -> bool:
    """Use Surya full OCR to add invisible searchable text layer to PDF."""
    try:
        from surya.foundation import FoundationPredictor
        from surya.recognition import RecognitionPredictor
        from surya.detection import DetectionPredictor

        doc = fitz.open(input_pdf_path)

        # Extract original page images (match Surya input to actual page content)
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

        foundation = FoundationPredictor()
        rec = RecognitionPredictor(foundation)
        det = DetectionPredictor()
        results = rec(page_images, det_predictor=det)

        new_doc = fitz.open()
        for page_num, result in enumerate(results):
            page = doc[page_num]
            img_rect = page_rects[page_num]

            # Re-render for background
            pix = page.get_pixmap(dpi=dpi)
            img_data = pix.tobytes("jpg", jpg_quality=50)
            width, height = page.rect.width, page.rect.height
            new_page = new_doc.new_page(width=width, height=height)
            new_page.insert_image(new_page.rect, stream=img_data)

            # Font: built-in china-t for minimal file size (no TTF embedding)
            cjk_font = fitz.Font("china-t")

            # Map Surya bboxes → page coordinates using the image's page rect
            iw, ih = result.image_bbox[2], result.image_bbox[3]
            rx, ry = img_rect.x0, img_rect.y0
            rw, rh = img_rect.width, img_rect.height

            for line in result.text_lines:
                text = line.text.strip()
                if not text:
                    continue
                x0, y0, x1, y1 = line.bbox
                # Normalize to image size, then map to page coordinates
                nx0 = rx + (x0 / iw) * rw
                ny0 = ry + (y0 / ih) * rh
                nx1 = rx + (x1 / iw) * rw
                ny1 = ry + (y1 / ih) * rh

                box_w = max(1, nx1 - nx0)
                box_h = max(1, ny1 - ny0)
                fontsize = min(72, max(4, box_h * 0.8))

                natural_w = cjk_font.text_length(text, fontsize=fontsize)
                if natural_w <= 0:
                    natural_w = len(text) * fontsize * 0.5
                scale_x = max(0.3, min(5.0, box_w / max(1, natural_w)))

                baseline = fitz.Point(nx0, ny1 - 2)
                morph = (baseline, fitz.Matrix(scale_x, 1.0))
                new_page.insert_text(
                    baseline, text,
                    fontname="china-t",
                    fontsize=fontsize, render_mode=3,
                    morph=morph,
                )

        new_doc.save(output_pdf_path, deflate=True, garbage=4)
        new_doc.close()
        doc.close()
        return True
    except Exception as e:
        try:
            doc.close()
            new_doc.close()
        except Exception:
            pass
        raise e
