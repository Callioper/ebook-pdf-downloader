"""LLM-based OCR engine using OpenAI-compatible vision API (Ollama, LM Studio, etc.)"""

import base64
import io
import logging
import os
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


async def verify_llm_model(
    endpoint: str,
    model_name: str,
    api_key: str = "",
    timeout: int = 30,
) -> Tuple[bool, str]:
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
    img_bytes = buf.getvalue()

    text = await ocr_page(endpoint, model_name, img_bytes, api_key, "eng", timeout=timeout, max_retries=1)

    if text and "test123" in text.lower():
        return True, f"OCR 验证通过: 识别到 '{text.strip()[:50]}'"
    return False, f"OCR 验证失败: 返回了 '{text[:50] if text else '<empty>'}' 但不包含 Test123"


async def ocr_page(
    endpoint: str,
    model_name: str,
    image_bytes: bytes,
    api_key: str = "",
    language: str = "chi_sim+eng",
    timeout: int = 60,
    max_retries: int = 1,
) -> Optional[str]:
    import httpx

    img_b64 = base64.b64encode(image_bytes).decode("utf-8")
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

    last_error = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    f"{endpoint.rstrip('/')}/v1/chat/completions",
                    json=body,
                    headers=headers,
                )
                if resp.status_code != 200:
                    last_error = f"HTTP {resp.status_code}"
                    if attempt < max_retries - 1:
                        continue
                    logger.warning(f"LLM OCR page failed: HTTP {resp.status_code}")
                    return None
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            last_error = str(e)
            logger.warning(f"LLM OCR page error (attempt {attempt+1}/{max_retries}): {e}")

    logger.error(f"LLM OCR page failed after {max_retries} retries: {last_error}")
    return None
