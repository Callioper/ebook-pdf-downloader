"""Build sandwich PDF with Surya-detected bboxes + LLM-extracted text.

After LLM-OCR via ocrmypdf plugin produces a PDF (possibly with garbled CJK
due to font encoding), this module re-extracts text by calling the LLM API
directly, then places it into Surya-detected bbox positions using a proper
CJK font (NotoSansSC-VF.ttf).
"""
import os
import io
import base64
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


def _llm_ocr_page(
    image_b64: str,
    api_base: str,
    model: str,
    api_key: str = "",
    timeout: int = 120,
) -> str:
    """Call LLM API to OCR a single page image. Returns extracted text."""
    import requests

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Normalize endpoint URL
    url = api_base.rstrip("/")
    if not url.endswith("/chat/completions"):
        if url.endswith("/v1"):
            url += "/chat/completions"
        else:
            url += "/v1/chat/completions"

    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": "Extract all visible text from this scanned book page. Preserve line structure, paragraph breaks, and reading order. Output ONLY the text, without any commentary, prefixes, or markdown formatting."},
            ]
        }],
        "max_tokens": 4096,
        "temperature": 0,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"LLM API error {resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]


def _render_pages_to_images(pdf_path: str, dpi: int = 200) -> List[str]:
    """Render PDF pages to base64 PNG images."""
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        images.append(base64.b64encode(pix.tobytes("png")).decode())
    doc.close()
    return images


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
    api_base: str = "http://127.0.0.1:12345/v1",
    model: str = "glm-ocr",
    api_key: str = "",
) -> bool:
    """
    Build searchable sandwich PDF with Surya bboxes + LLM text.

    Steps:
    1. Render pages to images
    2. Run Surya detection to get line bboxes
    3. Call LLM API directly to get text per page (NOT from ocrmypdf output)
    4. Align LLM lines to Surya bboxes
    5. Write sandwich PDF with CJK-capable font

    Returns True if successful.
    """
    try:
        images = _render_pages_to_images(input_pdf_path, dpi)
        pages_bboxes = _get_surya_bboxes(input_pdf_path, dpi)

        src_doc = fitz.open(input_pdf_path)
        new_doc = fitz.open()

        for page_num in range(src_doc.page_count):
            old_page = src_doc[page_num]
            width = old_page.rect.width
            height = old_page.rect.height

            # Background image
            pix = old_page.get_pixmap(dpi=dpi)
            img_data = pix.tobytes("jpg", jpg_quality=85)
            new_page = new_doc.new_page(width=width, height=height)
            new_page.insert_image(new_page.rect, stream=img_data)

            # Register CJK font for this page
            if os.path.exists(font_path):
                new_page.insert_font(fontname="CJK", fontfile=font_path)
                use_cjk = True
            else:
                use_cjk = False

            # LLM OCR this page directly
            try:
                llm_text = _llm_ocr_page(
                    images[page_num], api_base, model, api_key,
                    timeout=120,
                )
            except Exception:
                llm_text = ""

            bboxes = pages_bboxes[page_num] if page_num < len(pages_bboxes) else []
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

                new_page.insert_text(
                    fitz.Point(x0, y1 - 2),
                    text,
                    fontname="CJK" if use_cjk else "china-t",
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
