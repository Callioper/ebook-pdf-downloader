"""Build sandwich PDF with Surya OCR (detection + recognition).

Uses Surya's full OCR pipeline which outputs text_lines with text+bbox+confidence
in one step. Embeds text onto original PDF pages — no re-rendering, small file size.
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
    font_path: str = r"C:\Windows\Fonts\simhei.ttf",
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

        for page_num, result in enumerate(results):
            page = doc[page_num]
            width = page.rect.width
            height = page.rect.height

            use_cjk = os.path.exists(font_path)
            if use_cjk:
                page.insert_font(fontname="CJK", fontfile=font_path)
                cjk_font = fitz.Font(fontfile=font_path)
            else:
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
                page.insert_text(
                    baseline, text,
                    fontname="CJK" if use_cjk else "china-t",
                    fontsize=fontsize, render_mode=3,
                    morph=morph,
                )

        doc.save(output_pdf_path, deflate=True, garbage=4)
        doc.close()
        return True
    except Exception as e:
        try:
            doc.close()
        except Exception:
            pass
        raise e
