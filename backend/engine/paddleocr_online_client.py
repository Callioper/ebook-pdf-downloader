"""PaddleOCR-VL-1.5 online API client — send PDF/image, parse layout response."""

import base64
import logging
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)


class PaddleOCRAPIError(Exception):
    def __init__(self, message: str, code: int = -1):
        super().__init__(message)
        self.code = code


class PaddleOCRClient:
    """Client for PaddleOCR-VL-1.5 online API (Baido AI Studio)."""
    def __init__(self, token: str, endpoint: str, timeout: int = 300):
        self.token = token
        self.endpoint = endpoint.rstrip("/")
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    async def _call_api(self, file_data: bytes, file_type: int) -> List[Dict[str, Any]]:
        url = f"{self.endpoint}/layout-parsing"
        payload = {
            "file": base64.b64encode(file_data).decode("ascii"),
            "fileType": file_type,
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        }
        resp = await self._client.post(url, json=payload)
        data = resp.json()

        if resp.status_code != 200 or data.get("errorCode", 0) != 0:
            raise PaddleOCRAPIError(
                data.get("errorMsg", f"HTTP {resp.status_code}"),
                data.get("errorCode", resp.status_code),
            )

        return parse_paddleocr_result(data)

    async def process_pdf(self, pdf_bytes: bytes) -> List[Dict[str, Any]]:
        return await self._call_api(pdf_bytes, file_type=0)

    async def process_image(self, image_bytes: bytes) -> List[Dict[str, Any]]:
        return await self._call_api(image_bytes, file_type=1)

    async def close(self):
        await self._client.aclose()


def parse_paddleocr_result(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parse PaddleOCR-VL-1.5 API response, return list of page dicts."""
    results = raw.get("result", {}).get("layoutParsingResults", [])
    pages = []
    for item in results:
        md = item.get("markdown", {})
        pages.append({
            "markdown": md.get("text", ""),
            "images": md.get("images", {}),
            "output_images": item.get("outputImages", {}),
        })
    return pages
