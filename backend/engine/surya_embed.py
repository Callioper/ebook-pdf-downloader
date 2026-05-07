"""Build sandwich PDF with Surya-detected bboxes + LLM-extracted text."""
import os
import io
import fitz
from PIL import Image
from typing import List, Tuple


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
        iw, ih = img.size
        for bbox in result.bboxes:
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
    """Simple order-based alignment: pair LLM lines to Surya bboxes in order."""
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

    Returns True if successful.
    """
    try:
        pages_bboxes = _get_surya_bboxes(input_pdf_path, dpi)
        ocr_texts = _extract_ocr_text(ocr_pdf_path)

        src_doc = fitz.open(input_pdf_path)
        new_doc = fitz.open()

        for page_num in range(src_doc.page_count):
            old_page = src_doc[page_num]
            width = old_page.rect.width
            height = old_page.rect.height

            pix = old_page.get_pixmap(dpi=dpi)
            img_data = pix.tobytes("jpg", jpg_quality=85)
            new_page = new_doc.new_page(width=width, height=height)
            new_page.insert_image(new_page.rect, stream=img_data)

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

                box_h = max(1, y1 - y0)
                fontsize = min(72, max(4, box_h * 0.8))

                if os.path.exists(font_path):
                    new_page.insert_text(
                        fitz.Point(x0, y1 - 2),
                        text,
                        fontfile=font_path,
                        fontsize=fontsize,
                        render_mode=3,
                    )
                else:
                    new_page.insert_text(
                        fitz.Point(x0, y1 - 2),
                        text,
                        fontname="china-t",
                        fontsize=fontsize,
                        render_mode=3,
                    )

        new_doc.save(output_pdf_path)
        new_doc.close()
        src_doc.close()
        return True
    except Exception:
        try:
            src_doc.close()
            new_doc.close()
        except Exception:
            pass
        return False
