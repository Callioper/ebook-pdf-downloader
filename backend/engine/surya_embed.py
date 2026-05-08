"""Build sandwich PDF with Surya OCR (detection + recognition).

Uses Surya's full OCR pipeline which outputs text_lines with text+bbox+confidence
in one step. No LLM alignment needed — each line comes with its own bbox.
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
    font_path: str = r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
    languages: Optional[List[str]] = None,
) -> bool:
    """
    Use Surya full OCR (detection + recognition) to produce a searchable
    sandwich PDF with text lines placed at their detected bbox positions.

    Args:
        input_pdf_path: Source PDF
        output_pdf_path: Where to write sandwich PDF
        dpi: Rasterization DPI
        font_path: CJK-capable font for invisible text layer
        languages: Language codes (e.g. ['zh', 'en']). Auto-detect if None.

    Returns True if successful.
    """
    try:
        from surya.foundation import FoundationPredictor
        from surya.recognition import RecognitionPredictor
        from surya.detection import DetectionPredictor

        if languages is None:
            languages = ["zh", "en"]

        doc = fitz.open(input_pdf_path)
        new_doc = fitz.open()

        images = []
        widths = []
        heights = []
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            images.append(Image.open(io.BytesIO(pix.tobytes("png"))))
            widths.append(page.rect.width)
            heights.append(page.rect.height)

        # Run Surya full OCR
        foundation = FoundationPredictor()
        rec = RecognitionPredictor(foundation)
        det = DetectionPredictor()
        results = rec(images, det_predictor=det)

        for page_num, result in enumerate(results):
            width = widths[page_num]
            height = heights[page_num]

            # Background image
            pix = doc[page_num].get_pixmap(dpi=dpi)
            img_data = pix.tobytes("jpg", jpg_quality=85)
            new_page = new_doc.new_page(width=width, height=height)
            new_page.insert_image(new_page.rect, stream=img_data)

            # Register CJK font
            if os.path.exists(font_path):
                new_page.insert_font(fontname="CJK", fontfile=font_path)

            # Place each text line at its detected bbox
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

                box_h = max(1, ny1 - ny0)
                fontsize = min(72, max(4, box_h * 0.8))

                if os.path.exists(font_path):
                    new_page.insert_text(
                        fitz.Point(nx0, ny1 - 2),
                        text,
                        fontname="CJK",
                        fontsize=fontsize,
                        render_mode=3,
                    )
                else:
                    new_page.insert_text(
                        fitz.Point(nx0, ny1 - 2),
                        text,
                        fontname="china-t",
                        fontsize=fontsize,
                        render_mode=3,
                    )

        new_doc.save(output_pdf_path)
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
