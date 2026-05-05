# backend/engine/llm_ocr.py
"""LLM-based OCR engine using OpenAI-compatible vision API (Ollama, LM Studio, etc.)"""

import asyncio
import base64
import io
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def encode_image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def extract_page_images(pdf_path: str, dpi: int = 200) -> List[bytes]:
    """Extract each PDF page as a PNG image. Returns list of image bytes."""
    import fitz
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


async def verify_llm_model(
    endpoint: str,
    model_name: str,
    api_key: str = "",
    timeout: int = 30,
) -> Tuple[bool, str]:
    """
    Verify a model is OCR-capable by sending a tiny test image.
    Returns (is_ocr_capable, message).
    """
    import httpx
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (200, 40), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font = ImageFont.load_default()
    draw.text((10, 10), "Test123", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = encode_image_to_base64(buf.getvalue())

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                    {
                        "type": "text",
                        "text": "Read the text in this image. Reply with ONLY the text, nothing else.",
                    },
                ],
            }
        ],
        "max_tokens": 50,
        "temperature": 0,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{endpoint.rstrip('/')}/v1/chat/completions",
                json=body,
                headers=headers,
            )
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return False, "OCR 验证失败: 响应中没有 choices"
            content = choices[0].get("message", {}).get("content", "").strip()
            if not content:
                return False, "OCR 验证失败: 响应中无内容"
            if "test123" in content.lower():
                return True, f"OCR 验证通过: 识别到 '{content}'"
            return False, f"OCR 验证失败: 返回了 '{content[:50]}' 但不包含 Test123"
    except Exception as e:
        return False, f"连接失败: {str(e)[:100]}"


async def ocr_page(
    endpoint: str,
    model_name: str,
    image_bytes: bytes,
    api_key: str = "",
    language: str = "chi_sim+eng",
    timeout: int = 60,
) -> Optional[str]:
    """Send a single page image to the LLM and return recognized text."""
    import httpx

    img_b64 = encode_image_to_base64(image_bytes)
    lang_hint = "Chinese and English" if "chi_sim" in language else "English"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Extract ALL text from this image. This is a scanned book page in {lang_hint}. "
                            "Preserve the original text layout, line breaks, and structure. "
                            "Do not add commentary. Output ONLY the extracted text."
                        ),
                    },
                ],
            }
        ],
        "max_tokens": 4096,
        "temperature": 0,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{endpoint.rstrip('/')}/v1/chat/completions",
                json=body,
                headers=headers,
            )
            if resp.status_code != 200:
                logger.warning(f"LLM OCR page failed: HTTP {resp.status_code}")
                return None
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content", "")
            if not content:
                return None
            return content
    except Exception as e:
        logger.warning(f"LLM OCR page error: {e}")
        return None


def build_searchable_pdf(
    original_pdf: str,
    output_pdf: str,
    ocr_results: List[Optional[str]],
) -> bool:
    """
    Overlay OCR text onto each page of the PDF as an invisible text layer.
    ocr_results[i] is the text for page i (0-indexed).
    Returns True on success.
    """
    import fitz

    try:
        doc = fitz.open(original_pdf)
        for i, text in enumerate(ocr_results):
            if not text or not text.strip():
                continue
            if i >= len(doc):
                break
            page = doc[i]
            rect = page.rect
            page.insert_textbox(
                rect,
                text,
                fontname="helv",
                fontsize=8,
                color=(0, 0, 0),
                render_mode=3,  # invisible but selectable/searchable
            )
        doc.save(output_pdf, garbage=4, deflate=True)
        doc.close()
        return True
    except Exception as e:
        logger.error(f"build_searchable_pdf failed: {e}")
        return False


async def run_llm_ocr(
    task_id: str,
    pdf_path: str,
    output_pdf: str,
    endpoint: str,
    model_name: str,
    api_key: str = "",
    language: str = "chi_sim+eng",
    timeout: int = 7200,
    emit_progress=None,
    add_log=None,
) -> int:
    """
    Run LLM-based OCR on a PDF. Returns exit code (0 = success).
    Emits progress updates via the callbacks.
    """
    if add_log is None:
        add_log = lambda msg: None

    try:
        add_log("LLM OCR: extracting page images...")
        images = await asyncio.to_thread(extract_page_images, pdf_path, 200)
        total = len(images)
        add_log(f"LLM OCR: {total} pages to process")

        ocr_results: List[Optional[str]] = []
        start_time = time.time()

        for i, img_bytes in enumerate(images):
            page_num = i + 1
            add_log(f"LLM OCR: processing page {page_num}/{total}...")

            text = await ocr_page(endpoint, model_name, img_bytes, api_key, language, timeout=min(120, max(30, timeout // max(total, 1))))
            ocr_results.append(text)

            if emit_progress:
                await emit_progress(
                    step="ocr",
                    progress=int((i + 1) / total * 100),
                    detail=f"{page_num}/{total} 页",
                    eta=_compute_eta(start_time, page_num, total),
                )

        add_log("LLM OCR: building searchable PDF...")
        ok = await asyncio.to_thread(build_searchable_pdf, pdf_path, output_pdf, ocr_results)
        if ok:
            add_log("LLM OCR: searchable PDF created successfully")
            return 0
        else:
            add_log("LLM OCR: failed to build output PDF")
            return 1
    except Exception as e:
        if add_log:
            add_log(f"LLM OCR fatal error: {e}")
        return 1


def _compute_eta(start: float, current: int, total: int) -> str:
    """Format ETA string from elapsed time."""
    elapsed = time.time() - start
    if current <= 1 or elapsed <= 5:
        return ""
    sec_per_page = elapsed / current
    remaining = (total - current) * sec_per_page
    if remaining <= 0:
        return ""
    if remaining < 60:
        return f"约{int(remaining)}秒"
    m = int(remaining // 60)
    s = int(remaining % 60)
    if m < 60:
        return f"约{m}分{s}秒"
    h = m // 60
    m = m % 60
    return f"约{h}时{m}分"
