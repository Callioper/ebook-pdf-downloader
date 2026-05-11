"""MinerU v4 精准解析 API client — batch upload + poll + parse layout."""

import asyncio
import io
import json
import logging
import time
import zipfile
from typing import Any, Dict, List, Tuple

import httpx

logger = logging.getLogger(__name__)

MINERU_BASE = "https://mineru.net"


class MinerUAPIError(Exception):
    def __init__(self, message: str, code: int = -1):
        super().__init__(message)
        self.code = code


class MinerUTimeoutError(Exception):
    pass


class MinerUClient:
    def __init__(self, token: str, timeout: int = 120):
        self.token = token
        self._client = httpx.AsyncClient(
            base_url=MINERU_BASE,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=timeout,
        )

    async def submit_batch(
        self,
        file_names: List[str],
        model_version: str = "vlm",
        language: str = "ch",
        enable_table: bool = True,
        is_ocr: bool = True,
        enable_formula: bool = True,
    ) -> Tuple[str, List[str]]:
        payload = {
            "files": [{"name": name, "is_ocr": is_ocr} for name in file_names],
            "model_version": model_version,
            "language": language,
            "enable_table": enable_table,
            "enable_formula": enable_formula,
        }
        logger.info(f"submit_batch: files={file_names}, model={model_version}")
        try:
            resp = await self._client.post("/api/v4/file-urls/batch", json=payload)
            data = resp.json()
            logger.info(f"submit_batch response: code={data.get('code')}, batch_id={data.get('data',{}).get('batch_id','?')}")
            if data.get("code") != 0:
                raise MinerUAPIError(data.get("msg", "unknown error"), data.get("code", -1))
            return data["data"]["batch_id"], data["data"]["file_urls"]
        except MinerUAPIError:
            raise
        except Exception as e:
            raise MinerUAPIError(f"submit_batch failed: {type(e).__name__}: {e}") from e

    async def upload_file(self, file_url: str, pdf_bytes: bytes):
        """PUT raw bytes to OSS signed URL. Uses bare client — URL has embedded signature."""
        logger.info(f"upload_file: url_host={file_url.split('/')[2] if '//' in file_url else '?'}, size={len(pdf_bytes)}")
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30)) as up:
                    resp = await up.put(file_url, content=pdf_bytes)
                    logger.info(f"upload_file response: HTTP {resp.status_code}")
                    if resp.status_code in (200, 201):
                        return
                    if resp.status_code >= 500 and attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise MinerUAPIError(f"upload failed: HTTP {resp.status_code}")
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as e:
                logger.warning(f"upload_file attempt {attempt+1} failed: {type(e).__name__}: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise MinerUAPIError(f"upload failed after 3 attempts: {type(e).__name__}: {e}") from e

    async def poll_until_done(
        self,
        batch_id: str,
        timeout: int = 1800,
        poll_interval: float = 5.0,
        progress_callback=None,
    ) -> Dict[str, Any]:
        url = f"/api/v4/extract-results/batch/{batch_id}"
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            resp = await self._client.get(url)
            data = resp.json()
            if data.get("code") != 0:
                raise MinerUAPIError(data.get("msg", "query failed"))

            extract = data.get("data", {})
            items = extract.get("extract_result", [])

            if not items:
                await asyncio.sleep(poll_interval)
                continue

            if isinstance(items, dict):
                items = [items]

            file_result = items[0]
            state = file_result.get("state", "unknown")

            if state == "done":
                full_zip = file_result.get("full_zip_url", "")
                if not full_zip:
                    raise MinerUAPIError(f"done but no full_zip_url in response: {json.dumps(file_result)[:300]}")
                return file_result
            if state == "failed":
                raise MinerUAPIError(file_result.get("err_msg", "parse failed"))
            if state in ("running", "pending", "waiting-file") and progress_callback:
                progress = file_result.get("extract_progress", {})
                extracted = progress.get("extracted_pages", 0)
                total = progress.get("total_pages", 0)
                progress_callback(extracted, total, state)

            await asyncio.sleep(poll_interval)

        raise MinerUTimeoutError(f"batch {batch_id} did not complete within {timeout}s")

    async def download_zip(self, zip_url: str) -> bytes:
        logger.info(f"download_zip: {zip_url[:80]}...")
        resp = await self._client.get(zip_url)
        resp.raise_for_status()
        logger.info(f"download_zip: {len(resp.content)} bytes")
        return resp.content

    async def close(self):
        await self._client.aclose()

    async def process_pdf(
        self,
        pdf_bytes: bytes,
        file_name: str = "book.pdf",
        model_version: str = "vlm",
        progress_callback=None,
    ) -> bytes:
        logger.info(f"process_pdf: file={file_name}, size={len(pdf_bytes)}, model={model_version}")
        batch_id, file_urls = await self.submit_batch([file_name], model_version=model_version)
        await self.upload_file(file_urls[0], pdf_bytes)
        logger.info(f"process_pdf: polling batch_id={batch_id}")
        result = await self.poll_until_done(batch_id, progress_callback=progress_callback)
        return await self.download_zip(result["full_zip_url"])


def parse_layout_from_zip(zip_bytes: bytes) -> Dict[int, List[Dict[str, Any]]]:
    pages: Dict[int, List[Dict]] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        name_list = zf.namelist()

        layout_name = None
        content_name = None
        for name in name_list:
            basename = name.split("/")[-1]
            if basename.endswith("_layout.json") or basename == "layout.json":
                layout_name = name
            if basename.endswith("_content_list.json") or basename == "content_list.json":
                content_name = name

        if layout_name:
            layout_data = json.loads(zf.read(layout_name))
            for item in layout_data:
                text = (item.get("text") or "").strip()
                poly = item.get("poly", [])
                cat_id = item.get("category_id", -1)
                page_idx = item.get("page_idx", 0)

                if not text:
                    continue

                if poly and len(poly) >= 4:
                    xs = [poly[i] for i in range(0, len(poly), 2)]
                    ys = [poly[i] for i in range(1, len(poly), 2)]
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                else:
                    bbox = None

                pages.setdefault(page_idx, []).append({
                    "text": text,
                    "bbox": bbox,
                    "category_id": cat_id,
                })

        if not layout_name and content_name:
            content_data = json.loads(zf.read(content_name))
            for item in content_data:
                text = item.get("text", "").strip()
                page_idx = item.get("page_idx", 0)
                if not text:
                    continue
                pages.setdefault(page_idx, []).append({
                    "text": text,
                    "bbox": None,
                    "category_id": -1,
                })

    return dict(sorted(pages.items()))
