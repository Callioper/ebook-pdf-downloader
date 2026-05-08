"""Synchronous HTTP client for OpenAI-compatible vision LLM APIs (Ollama, LM Studio)."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)

_MAX_IMAGE_DIM = 2048
"""Maximum pixel dimension (width or height) for images sent to the LLM.

Larger images are downscaled before encoding to reduce latency and payload size.
"""


class LlmApiClient:
    """Synchronous client for an OpenAI-compatible chat completions endpoint.

    Args:
        endpoint: Base URL (e.g. ``http://localhost:11434`` or ``http://localhost:1234/v1``).
        model: Model name (e.g. ``llava:13b``, ``noctrex/paddleocr-vl-1.5``).
        api_key: Optional API key for authenticated endpoints.
        timeout: Request timeout in seconds. Default 120.
        max_retries: Max retries on transient errors. Default 2.
    """

    def __init__(
        self,
        endpoint: str = "http://localhost:11434",
        model: str = "",
        api_key: str = "",
        timeout: float = 120,
        max_retries: int = 2,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=30, read=timeout),
            limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=60),
        )

    def close(self):
        self._client.close()

    @staticmethod
    def _prepare_image(image_bytes: bytes) -> str:
        """Downscale and JPEG-compress image, return base64 data URI."""
        from PIL import Image as PILImage, UnidentifiedImageError
        import io

        try:
            img = PILImage.open(io.BytesIO(image_bytes))
            img.load()
        except (UnidentifiedImageError, Exception):
            # Fallback: encode raw bytes as PNG data URI
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            return f"data:image/png;base64,{b64}"

        w, h = img.size
        scale = min(_MAX_IMAGE_DIM / w, _MAX_IMAGE_DIM / h, 1.0)
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

    def ocr_image(self, image_bytes: bytes, lang_hint: str = "English") -> str | None:
        """Send a page image to the LLM and return recognized text.

        Args:
            image_bytes: Raw image bytes (PNG or other format).
            lang_hint: Language description for the prompt (e.g. "Chinese and English").

        Returns:
            Recognized text, or None on failure.
        """
        data_url = self._prepare_image(image_bytes)
        body = self._build_body(data_url, lang_hint)
        url = f"{self.endpoint}/v1/chat/completions"

        # Attempt 1: primary request
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._client.post(url, json=body)
                if resp.status_code == 200:
                    return self._parse_response(resp.json())
                if self._is_retryable(resp):
                    delay = min(2**attempt, 30)
                    log.info(
                        "Model unloaded, retrying in %ds (attempt %d/%d)",
                        delay, attempt, self.max_retries,
                    )
                    time.sleep(delay)
                    continue
                log.warning("LLM API error: HTTP %d", resp.status_code)
                return None
            except httpx.TimeoutException:
                # Timeout means model is too slow — retrying won't help
                log.warning("LLM API timeout after %ds", self.timeout)
                return None
            except httpx.ConnectError:
                # Connection error: back off briefly and retry
                log.warning("LLM API connection refused (attempt %d/%d)", attempt, self.max_retries)
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 5))
                    continue
                return None
            except Exception as e:
                log.warning("LLM API error (attempt %d/%d): %s", attempt, self.max_retries, e)
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 5))
                    continue
                return None
        return None

    async def perform_ocr(self, image_b64: str) -> str:
        """OCR a full page image (base64-encoded). Returns plain text."""
        import base64
        image_bytes = base64.b64decode(image_b64)
        result = await asyncio.to_thread(self.ocr_image, image_bytes)
        return (result or "").strip()

    async def perform_ocr_on_crop(self, image_b64: str) -> str:
        """OCR a cropped region (base64-encoded). Returns plain text."""
        import base64
        image_bytes = base64.b64decode(image_b64)
        result = await asyncio.to_thread(self.ocr_image, image_bytes)
        return (result or "").strip()

    async def perform_ocr_on_crop(self, image_b64: str) -> str:
        """OCR a cropped region (base64-encoded). Returns plain text."""
        image_bytes = base64.b64decode(image_b64)
        result = await asyncio.to_thread(self.ocr_image, image_bytes)
        return (result or "").strip()

    def _build_body(self, data_url: str, lang_hint: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                        {
                            "type": "text",
                            "text": (
                                f"Extract ALL text from this image. "
                                f"This is a scanned book page in {lang_hint}. "
                                "Preserve the original text layout, line breaks, and structure. "
                                "Do not add commentary. Output ONLY the extracted text."
                            ),
                        },
                    ],
                }
            ],
            "max_tokens": 2048,
            "temperature": 0,
        }

    def _parse_response(self, data: dict[str, Any]) -> str | None:
        choices = data.get("choices", [])
        if not choices:
            return None
        content = choices[0].get("message", {}).get("content", "")
        return content if content else None

    @staticmethod
    def _is_retryable(resp: httpx.Response) -> bool:
        err = (resp.text or "")[:300].lower()
        return "model" in err and any(
            kw in err for kw in ("unloaded", "not loaded", "canceled", "cancelled")
        )
