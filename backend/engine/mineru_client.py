"""MinerU v4 精准解析 API client — batch upload + poll + parse layout."""

import asyncio
import io
import json
import time
import zipfile
from typing import Any, Dict, List, Tuple

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
        self._timeout = timeout

    async def close(self):
        pass

    async def submit_batch(
        self,
        file_names: List[str],
        model_version: str = "vlm",
        language: str = "ch",
        enable_table: bool = True,
        is_ocr: bool = True,
        enable_formula: bool = True,
    ) -> Tuple[str, List[str]]:
        import httpx
        payload = {
            "files": [{"name": name, "is_ocr": is_ocr} for name in file_names],
            "model_version": model_version,
            "language": language,
            "enable_table": enable_table,
            "enable_formula": enable_formula,
        }
        try:
            async with httpx.AsyncClient(
                base_url=MINERU_BASE,
                headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
                timeout=30,
                trust_env=False,
            ) as client:
                resp = await client.post("/api/v4/file-urls/batch", json=payload)
                data = resp.json()
                if data.get("code") != 0:
                    raise MinerUAPIError(data.get("msg", "unknown error"), data.get("code", -1))
                return data["data"]["batch_id"], data["data"]["file_urls"]
        except MinerUAPIError:
            raise
        except Exception as e:
            raise MinerUAPIError(f"submit_batch failed: {type(e).__name__}: {e}") from e

    async def upload_file(self, file_url: str, pdf_bytes: bytes):
        import httpx
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30), trust_env=False) as up:
                    resp = await up.put(file_url, content=pdf_bytes)
                    if resp.status_code in (200, 201):
                        return
                    if resp.status_code >= 500 and attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    raise MinerUAPIError(f"upload failed: HTTP {resp.status_code}")
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException) as e:
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
        import httpx
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            async with httpx.AsyncClient(
                base_url=MINERU_BASE,
                headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
                timeout=30,
                trust_env=False,
            ) as client:
                resp = await client.get(f"/api/v4/extract-results/batch/{batch_id}")
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
                    raise MinerUAPIError(f"done but no full_zip_url: {json.dumps(file_result)[:300]}")
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
        import httpx
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.get(zip_url)
            resp.raise_for_status()
            return resp.content

    async def process_pdf(
        self,
        pdf_bytes: bytes,
        file_name: str = "book.pdf",
        model_version: str = "vlm",
        progress_callback=None,
    ) -> bytes:
        batch_id, file_urls = await self.submit_batch([file_name], model_version=model_version)
        await self.upload_file(file_urls[0], pdf_bytes)
        result = await self.poll_until_done(batch_id, progress_callback=progress_callback)
        return await self.download_zip(result["full_zip_url"])


def parse_layout_from_zip(zip_bytes: bytes) -> Dict[int, List[Dict[str, Any]]]:
    pages: Dict[int, List[Dict]] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        name_list = zf.namelist()

        content_name = None
        for name in name_list:
            basename = name.split("/")[-1]
            if basename.endswith("_model.json"):
                content_name = name
                break

        if not content_name:
            for name in name_list:
                basename = name.split("/")[-1]
                if basename.endswith("_content_list.json") and not basename.endswith("_v2.json"):
                    content_name = name
                    break
        if not content_name:
            for name in name_list:
                basename = name.split("/")[-1]
                if basename.endswith("_content_list_v2.json"):
                    content_name = name
                    break

        if content_name:
            data = json.loads(zf.read(content_name))

            # model.json: [[page0_items], [page1_items], ...] — bbox values are normalized 0..1
            is_model = content_name.endswith("_model.json")
            if is_model and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                for page_idx, page_items in enumerate(data):
                    for item in page_items:
                        text = _extract_text_from_item(item)
                        if not text:
                            continue
                        bbox = _extract_bbox_from_item(item)
                        pages.setdefault(page_idx, []).append({"text": text, "bbox": bbox, "category_id": 0})
                return dict(sorted(pages.items()))
            if isinstance(data, list):
                for item in data:
                    text = _extract_text_from_item(item)
                    if not text:
                        continue
                    page_idx = item.get("page_idx", 0)
                    bbox_arr = item.get("bbox", [])
                    bbox = _normalize_bbox(bbox_arr)
                    pages.setdefault(page_idx, []).append({"text": text, "bbox": bbox, "category_id": 0})
                return dict(sorted(pages.items()))

    for name in name_list:
        if name.endswith("full.md") or name == "full.md":
            md_text = zf.read(name).decode("utf-8", errors="replace")
            lines = [l.strip() for l in md_text.split("\n") if l.strip()]
            pages[0] = [{"text": l, "bbox": None, "category_id": 0} for l in lines]
            return pages
    return pages


def _extract_text_from_item(item: Dict) -> str:
    for key in ("text", "content"):
        val = item.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    content = item.get("content")
    if isinstance(content, dict):
        for sub_key in ("paragraph_content", "title_content", "page_header_content", "page_footer_content"):
            sub = content.get(sub_key)
            if isinstance(sub, list):
                parts = [c.get("text") or c.get("content") or "" for c in sub if isinstance(c, dict)]
                if parts:
                    return "".join(parts)
    return ""


def _extract_bbox_from_item(item: Dict):
    bbox = item.get("bbox", [])
    return _normalize_bbox(bbox)


def _normalize_bbox(bbox) -> tuple:
    if bbox and isinstance(bbox, list) and len(bbox) == 4:
        return tuple(bbox)
    return None
