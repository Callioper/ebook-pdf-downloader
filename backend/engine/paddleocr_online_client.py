"""PaddleOCR-VL-1.5 online API client — async job submission + polling + JSONL parsing."""

import asyncio
import json
import io
import time
from typing import Any, Dict, List, Optional

import httpx

PADDLEOCR_JOB_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
PADDLEOCR_MODEL = "PaddleOCR-VL-1.5"
DEFAULT_POLL_INTERVAL = 5.0


class PaddleOCRAPIError(Exception):
    def __init__(self, message: str, code: int = -1):
        super().__init__(message)
        self.code = code


class PaddleOCRClient:
    """Client for PaddleOCR-VL-1.5 online API (Baidu AI Studio)."""

    def __init__(self, token: str, timeout: int = 600):
        self.token = token
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"bearer {token}"},
            timeout=timeout,
        )

    async def submit_job_file(self, file_path: str, pdf_bytes: bytes) -> str:
        """Submit a local file for OCR processing, returns jobId."""
        files = {"file": ("document.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        data = {
            "model": PADDLEOCR_MODEL,
            "optionalPayload": json.dumps({
                "useDocOrientationClassify": False,
                "useDocUnwarping": False,
                "useChartRecognition": False,
            }),
        }
        resp = await self._client.post(PADDLEOCR_JOB_URL, data=data, files=files)
        if resp.status_code != 200:
            raise PaddleOCRAPIError(
                f"job submission failed: HTTP {resp.status_code} {resp.text[:200]}",
                resp.status_code,
            )
        result = resp.json()
        job_id = result.get("data", {}).get("jobId", "")
        if not job_id:
            raise PaddleOCRAPIError(f"no jobId in response: {resp.text[:200]}")
        return job_id

    async def poll_job(
        self,
        job_id: str,
        timeout: int = 1800,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """Poll job status until done, returns result data dict with jsonl_url."""
        url = f"{PADDLEOCR_JOB_URL}/{job_id}"
        deadline = time.monotonic() + timeout
        last_pct = -1

        while time.monotonic() < deadline:
            resp = await self._client.get(url)
            if resp.status_code != 200:
                raise PaddleOCRAPIError(f"poll failed: HTTP {resp.status_code}")

            result = resp.json()
            data = result.get("data", {})
            state = data.get("state", "unknown")

            if state == "done":
                return data
            if state == "failed":
                raise PaddleOCRAPIError(data.get("errorMsg", "job failed"))

            if progress_callback:
                progress = data.get("extractProgress", {})
                total = progress.get("totalPages", 0)
                extracted = progress.get("extractedPages", 0)
                if total > 0:
                    pct = int(extracted * 100 / total)
                    if pct != last_pct:
                        last_pct = pct
                        progress_callback(extracted, total, state)

            await asyncio.sleep(poll_interval)

        raise PaddleOCRAPIError(f"job {job_id} did not complete within {timeout}s")

    async def download_jsonl(self, jsonl_url: str) -> List[Dict[str, Any]]:
        """Download and parse the JSONL result file."""
        resp = await self._client.get(jsonl_url)
        resp.raise_for_status()
        return parse_jsonl_result(resp.text)

    async def process_pdf(
        self,
        pdf_bytes: bytes,
        file_name: str = "document.pdf",
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """Full flow: submit → poll → download → parse."""
        job_id = await self.submit_job_file(file_name, pdf_bytes)
        result = await self.poll_job(job_id, progress_callback=progress_callback)
        jsonl_url = result.get("resultUrl", {}).get("jsonUrl", "")
        if not jsonl_url:
            raise PaddleOCRAPIError("no jsonl URL in completed job result")
        return await self.download_jsonl(jsonl_url)

    async def test_connectivity(self) -> Dict[str, Any]:
        """Lightweight connectivity check: just ping the API."""
        resp = await self._client.get(PADDLEOCR_JOB_URL, params={"limit": 1})
        return {"ok": resp.status_code == 200, "status": resp.status_code}

    async def close(self):
        await self._client.aclose()


def parse_jsonl_result(jsonl_text: str) -> List[Dict[str, Any]]:
    """Parse PaddleOCR JSONL output, return list of page dicts with markdown."""
    pages = []
    for line in jsonl_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        result = record.get("result", {})
        layout_results = result.get("layoutParsingResults", [])
        for item in layout_results:
            md = item.get("markdown", {})
            pages.append({
                "markdown": md.get("text", ""),
                "images": md.get("images", {}),
                "output_images": item.get("outputImages", {}),
            })
    return pages


def parse_paddleocr_blocks(jsonl_text: str) -> Dict[int, List[Dict[str, Any]]]:
    """Parse PaddleOCR JSONL prunedResult into per-page blocks with normalized bboxes.

    Each block = {"text": str, "bbox": [nx0,ny0,nx1,ny1], "type": str}
    Coordinates normalized to [0..1] from pixel space.

    Returns format compatible with PageTextBlocks (Dict[int, List[Dict[str, Any]]])
    so allocate_text_to_surya_boxes() can consume it directly.
    """
    layout: Dict[int, List[Dict[str, Any]]] = {}

    for line in jsonl_text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        result = record.get("result", {})
        layout_results = result.get("layoutParsingResults", [])

        for item in layout_results:
            pruned = item.get("prunedResult", {})
            if not pruned:
                continue

            width = float(pruned.get("width", 1))
            height = float(pruned.get("height", 1))
            if width <= 0 or height <= 0:
                width, height = 1.0, 1.0

            parsing_list = pruned.get("parsing_res_list", [])
            if not parsing_list:
                continue

            blocks = []
            for entry in parsing_list:
                text = (entry.get("block_content") or "").strip()
                bbox = entry.get("block_bbox")
                label = entry.get("block_label", "")

                if not text or not bbox or len(bbox) != 4:
                    continue

                try:
                    nx0 = float(bbox[0]) / width
                    ny0 = float(bbox[1]) / height
                    nx1 = float(bbox[2]) / width
                    ny1 = float(bbox[3]) / height
                except (TypeError, ValueError):
                    continue

                blocks.append({
                    "text": text,
                    "bbox": [nx0, ny0, nx1, ny1],
                    "type": label,
                })

            if blocks:
                page_idx = len(layout)
                layout[page_idx] = blocks

    return layout
