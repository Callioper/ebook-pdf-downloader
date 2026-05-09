"""Grounded OCR path — bbox-native VLM (Qwen2.5-VL, Qwen3-VL, MinerU, etc.)
Returns text + coordinates in one call, bypassing Surya + DP + refine entirely."""

import asyncio
import json
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)

GROUNDING_PROMPT = (
    "You are an OCR assistant. For each visual text element in the image, "
    "return exactly one JSON object per element:\n"
    '{"bbox_2d": [x0, y0, x1, y1], "content": "..."}\n'
    "Coordinates must be pixel values relative to the image dimensions.\n"
    "Return a JSON array of these objects, one per visible text region.\n"
    "Output ONLY the JSON array, no other text."
)


class GroundedOcr:
    """OCR via a bbox-native VLM that returns text + coordinates in one call."""

    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    async def process_page(self, image_data_url: str) -> list[dict[str, Any]]:
        """Process one page image, return [{bbox_2d, content}, ...]."""
        endpoint = getattr(self._client, 'endpoint', '')
        timeout = getattr(self._client, 'timeout', 300)
        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                        {"type": "text", "text": GROUNDING_PROMPT},
                    ],
                }
            ],
            "max_tokens": 4096,
            "temperature": 0,
        }
        url = f"{endpoint}/v1/chat/completions"
        return await asyncio.to_thread(self._call_grounded, url, body, timeout)

    def _call_grounded(self, url: str, body: dict, timeout: int) -> list[dict[str, Any]]:
        """Synchronous HTTP call for grounded OCR (runs in thread pool)."""
        with httpx.Client(timeout=timeout) as http:
            try:
                resp = http.post(url, json=body)
                if resp.status_code != 200:
                    log.warning("Grounded OCR HTTP %d: %s", resp.status_code, resp.text[:200])
                    return []
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return _parse_grounded_response(content)
            except Exception as e:
                log.warning("Grounded OCR error: %s", e)
                return []


def _parse_grounded_response(content: str) -> list[dict[str, Any]]:
    """Parse JSON array from LLM response. Handles markdown code fences."""
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                log.warning("Grounded OCR: could not parse JSON: %s", text[:200])
                return []
        else:
            log.warning("Grounded OCR: no JSON array found: %s", text[:200])
            return []

    if not isinstance(data, list):
        return []

    results = []
    for item in data:
        if isinstance(item, dict) and "content" in item:
            bbox = item.get("bbox_2d", [0, 0, 0, 0])
            results.append({"bbox_2d": bbox, "content": item["content"]})
    return results
