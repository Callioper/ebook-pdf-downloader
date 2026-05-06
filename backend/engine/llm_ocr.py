# backend/engine/llm_ocr.py
"""LLM-based OCR engine using OpenAI-compatible vision API (Ollama, LM Studio, etc.)"""

import base64
import io
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def encode_image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")



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
                return False, "模型返回空内容 — 该模型可能不是多模态视觉模型，无法处理图片。请使用支持 Vision 的模型（如 llava, llama3.2-vision, minicpm-v）"
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
    max_retries: int = 5,
) -> Optional[str]:
    """Send a single page image to the LLM and return recognized text.
    Retries on model-unloaded errors with exponential backoff."""
    import httpx
    import asyncio as _aio

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

    last_status = 0
    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{endpoint.rstrip('/')}/v1/chat/completions",
                    json=body,
                    headers=headers,
                )
                last_status = resp.status_code
                if resp.status_code == 200:
                    data = resp.json()
                    choices = data.get("choices", [])
                    if not choices:
                        return None
                    content = choices[0].get("message", {}).get("content", "")
                    if not content:
                        return None
                    return content

                err_text = (resp.text or "")[:300].lower()
                if "model" in err_text and (
                    "unloaded" in err_text
                    or "not loaded" in err_text
                    or "canceled" in err_text
                    or "cancelled" in err_text
                ):
                    if attempt < max_retries:
                        delay = min(2 ** attempt, 30)
                        logger.info(
                            f"LLM OCR page: model unloaded, retrying in {delay}s (attempt {attempt}/{max_retries})"
                        )
                        await _aio.sleep(delay)
                        continue
                logger.warning(f"LLM OCR page failed: HTTP {resp.status_code}")
                return None
        except Exception as e:
            last_status = 0
            logger.warning(f"LLM OCR page error (attempt {attempt}): {e}")
            if attempt < max_retries:
                await _aio.sleep(min(2 ** attempt, 30))
                continue
            return None

    return None





