"""Build sandwich PDF with Surya OCR (detection + recognition).

Uses Surya's full OCR pipeline which outputs text_lines with text+bbox+confidence.
Writes a fresh sandwich PDF with re-rendered page images and invisible text layer.
Uses china-t (PyMuPDF built-in CJK font) for minimal file bloat.
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
        images = []
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            images.append(Image.open(io.BytesIO(pix.tobytes("png"))))

        foundation = FoundationPredictor()
        rec = RecognitionPredictor(foundation)
        det = DetectionPredictor()
        results = rec(images, det_predictor=det)

        new_doc = fitz.open()
        for page_num, result in enumerate(results):
            pix = doc[page_num].get_pixmap(dpi=dpi)
            img_data = pix.tobytes("jpg", jpg_quality=45)  # low quality = small
            width = doc[page_num].rect.width
            height = doc[page_num].rect.height
            new_page = new_doc.new_page(width=width, height=height)
            new_page.insert_image(new_page.rect, stream=img_data)

            # Use built-in CJK font (china-t = SimHei, no external file needed)
            cjk_font = fitz.Font("china-t")

            iw, ih = result.image_bbox[2], result.image_bbox[3]
            for line in result.text_lines:
                text = line.text.strip()
                if not text:
                    continue
                x0, y0, x1, y1 = line.bbox
                nx0 = x0 / iw * width
                ny0 = y0 / ih * height
                nx1 = x1 / iw * width
                ny1 = y1 / ih * height

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
