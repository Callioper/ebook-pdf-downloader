# MinerU & PaddleOCR Online API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MinerU (精准解析 v4) and PaddleOCR-VL-1.5 online API support as **additional** OCR engine choices alongside existing Tesseract / PaddleOCR (local) / LLM OCR (Ollama/LMStudio). Existing engines are untouched — these are purely additive options.

**Architecture:** Two **new** `ocr_engine` values (`mineru`, `paddleocr_online`) each with dedicated API client modules in `backend/engine/`. All four existing engines (tesseract, paddleocr, llm_ocr) remain unchanged. MinerU uses batch-upload → poll → download-zip flow with layout.json for precise text positioning. PaddleOCR-VL-1.5 sends the full PDF as base64 and gets back per-page markdown with layout, embedded in reading order. Both bypass local-llm-pdf-ocr subprocess — they implement their own PDF→API→embed pipeline.

**Tech Stack:** Python `httpx` (async HTTP), `pikepdf`, `PIL`, `zipfile`. Reuses existing `bw_compress_pdf_blocking` for post-OCR compression.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/engine/mineru_client.py` | **Create** | MinerU v4 batch-upload API client (submit, poll, download zip, parse layout.json) |
| `backend/engine/paddleocr_online_client.py` | **Create** | PaddleOCR-VL-1.5 API client (send PDF/image, parse layout response) |
| `backend/engine/pdf_api_embed.py` | **Create** | PDF text layer embedding from API layout results (shared by both engines) |
| `backend/config.py` | Modify | Add 4 config keys + defaults for MinerU/PaddleOCR tokens/endpoints |
| `backend/engine/pipeline.py` | Modify | Add `mineru` and `paddleocr_online` branches in `_step_ocr()` |
| `frontend/src/constants.ts` | Modify | Add `mineru`, `paddleocr_online` to `OCR_ENGINES` array |
| `frontend/src/components/ConfigSettings.tsx` | Modify | Add UI panels for MinerU token, PaddleOCR token/endpoint |
| `backend/engine/__init__.py` | Modify | Export new public symbols |
| `tests/test_mineru_client.py` | **Create** | Unit tests for MinerU client (mock HTTP) |
| `tests/test_paddleocr_online_client.py` | **Create** | Unit tests for PaddleOCR client (mock HTTP) |
| `tests/test_pdf_api_embed.py` | **Create** | Unit tests for PDF embedding from API results |

---

## API Reference Summary

### MinerU v4 精准解析 (batch upload)

**Auth:** `Authorization: Bearer <token>`
**Base URL:** `https://mineru.net`

Flow:
1. `POST /api/v4/file-urls/batch` — body: `{"files":[{"name":"book.pdf"}], "model_version":"vlm", "language":"ch", "enable_table":true, "is_ocr":true, "enable_formula":true}` → returns `batch_id` + `file_urls`
2. `PUT <file_url>` — upload raw PDF bytes (no Content-Type header)
3. Poll `GET /api/v4/extract-results/batch/{batch_id}` — state: `done`/`running`/`failed`; when done returns `full_zip_url`
4. Download zip → extract `layout.json` + `{name}_content_list.json` + `full.md`

**Constraints:** ≤200MB, ≤200 pages. China mainland network only (proxy issue).

### PaddleOCR-VL-1.5

**Auth:** `Authorization: token <token>` (NOTE: "token" not "Bearer")
**Endpoint:** User-configurable (obtained from PaddleOCR console)

Flow:
1. `POST <endpoint>/layout-parsing` — body: `{"file":"<base64 PDF>", "fileType":0, "useDocOrientationClassify":false, "useDocUnwarping":false, "useChartRecognition":false}`
2. Response: `{"result":{"layoutParsingResults":[{"markdown":{"text":"...","images":{}}, "outputImages":{}}]}}`

**Constraints:** Files ≤100MB by default. Returns markdown per page, no explicit bbox data — uses reading-order embedding.

---

## Config Keys Added

| Key | Default | Description |
|-----|---------|-------------|
| `mineru_token` | `""` | MinerU v4 API Bearer token |
| `mineru_model` | `"vlm"` | MinerU model version: `pipeline`, `vlm`, or `MinerU-HTML` |
| `paddleocr_online_token` | `""` | PaddleOCR-VL-1.5 API token |
| `paddleocr_online_endpoint` | `""` | PaddleOCR-VL-1.5 serving endpoint URL (e.g. `https://aistudio.baidu.com/serving/xxx`) |

New `ocr_engine` values: `"mineru"`, `"paddleocr_online"`.

---

### Task 1: Config Infrastructure

**Files:**
- Modify: `backend/config.py:44-85`
- Modify: `frontend/src/constants.ts:50-54`
- Modify: `frontend/src/types.ts` (add new config fields)

- [ ] **Step 1: Add config defaults in backend/config.py**

```python
# In DEFAULT_CONFIG dict (around line 63, after llm_ocr_detect_batch):
"mineru_token": "",
"mineru_model": "vlm",
"paddleocr_online_token": "",
"paddleocr_online_endpoint": "",
```

- [ ] **Step 2: Add OCR engine entries in frontend/src/constants.ts**

```typescript
// After llm_ocr entry (line 53):
{ key: 'mineru', name: 'MinerU 线上 API', desc: '上海 AI Lab 精准解析，需 Token' },
{ key: 'paddleocr_online', name: 'PaddleOCR-VL-1.5 线上 API', desc: '百度 PaddleOCR 视觉大模型，需 Token 和端点' },
```

- [ ] **Step 3: Add type fields in frontend/src/types.ts AppConfig interface**

```typescript
mineru_token?: string
mineru_model?: string
paddleocr_online_token?: string
paddleocr_online_endpoint?: string
```

- [ ] **Step 4: Verify config loads correctly**

Run: `python -c "from backend.config import DEFAULT_CONFIG; print(DEFAULT_CONFIG['mineru_token'])"`
Expected: `` (empty string)

- [ ] **Step 5: Commit**

```bash
git add backend/config.py frontend/src/constants.ts frontend/src/types.ts
git commit -m "feat: add MinerU and PaddleOCR online config keys and engine entries"
```

---

### Task 2: MinerU API Client

**Files:**
- Create: `backend/engine/mineru_client.py`
- Test: `tests/test_mineru_client.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_mineru_client.py
import io
import zipfile
import json
import httpx
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.engine.mineru_client import (
    MinerUClient,
    MinerUAPIError,
    MinerUTimeoutError,
)

@pytest.fixture
def client():
    return MinerUClient(token="test-token-123")

@pytest.mark.asyncio
async def test_submit_batch_returns_batch_id(client):
    """POST /api/v4/file-urls/batch should return batch_id and file_url."""
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "code": 0,
        "data": {
            "batch_id": "batch-abc-123",
            "file_urls": ["https://oss.example.com/upload/abc"],
        },
        "msg": "ok",
    }

    with patch.object(client._client, "post", return_value=mock_response):
        batch_id, file_urls = await client.submit_batch(
            file_names=["test.pdf"],
            model_version="vlm",
        )

    assert batch_id == "batch-abc-123"
    assert file_urls == ["https://oss.example.com/upload/abc"]

@pytest.mark.asyncio
async def test_upload_file_sends_raw_bytes(client):
    """PUT to file_url should send raw PDF bytes."""
    mock_response = AsyncMock()
    mock_response.status_code = 200

    pdf_bytes = b"%PDF-1.4 fake pdf content"
    with patch.object(client._client, "put", return_value=mock_response) as mock_put:
        await client.upload_file("https://oss.example.com/upload/abc", pdf_bytes)

    mock_put.assert_called_once()
    call_args = mock_put.call_args
    assert call_args[0][0] == "https://oss.example.com/upload/abc"
    assert call_args[1]["content"] == pdf_bytes

@pytest.mark.asyncio
async def test_poll_until_done_returns_zip_url(client):
    """Polling should return full_zip_url when state=done."""
    pending_resp = AsyncMock()
    pending_resp.status_code = 200
    pending_resp.json.return_value = {
        "code": 0,
        "data": {
            "batch_id": "batch-abc",
            "extract_result": [{"file_name": "test.pdf", "state": "running"}],
        },
    }

    done_resp = AsyncMock()
    done_resp.status_code = 200
    done_resp.json.return_value = {
        "code": 0,
        "data": {
            "batch_id": "batch-abc",
            "extract_result": [{
                "file_name": "test.pdf",
                "state": "done",
                "full_zip_url": "https://cdn.example.com/result.zip",
            }],
        },
    }

    with patch.object(client._client, "get", side_effect=[pending_resp, done_resp]):
        result = await client.poll_until_done("batch-abc", poll_interval=0.01)

    assert result["full_zip_url"] == "https://cdn.example.com/result.zip"

@pytest.mark.asyncio
async def test_poll_raises_on_failed(client):
    """Polling should raise MinerUAPIError when state=failed."""
    failed_resp = AsyncMock()
    failed_resp.status_code = 200
    failed_resp.json.return_value = {
        "code": 0,
        "data": {
            "batch_id": "batch-abc",
            "extract_result": [{
                "file_name": "test.pdf",
                "state": "failed",
                "err_msg": "file too large",
            }],
        },
    }

    with patch.object(client._client, "get", return_value=failed_resp):
        with pytest.raises(MinerUAPIError, match="file too large"):
            await client.poll_until_done("batch-abc", poll_interval=0.01)

@pytest.mark.asyncio
async def test_poll_raises_timeout(client):
    """Polling should raise MinerUTimeoutError after timeout."""
    running_resp = AsyncMock()
    running_resp.status_code = 200
    running_resp.json.return_value = {
        "code": 0,
        "data": {
            "batch_id": "batch-abc",
            "extract_result": [{"file_name": "test.pdf", "state": "running"}],
        },
    }

    with patch.object(client._client, "get", return_value=running_resp):
        with pytest.raises(MinerUTimeoutError):
            await client.poll_until_done("batch-abc", timeout=0.1, poll_interval=0.01)

def test_parse_layout_json_extracts_text_blocks():
    """parse_layout_from_zip should extract text blocks from layout.json."""
    from backend.engine.mineru_client import parse_layout_from_zip

    layout = [
        {
            "category_id": 2,
            "poly": [100, 200, 400, 200, 400, 220, 100, 220],
            "text": "第一章 引言",
        },
        {
            "category_id": 2,
            "poly": [100, 230, 400, 230, 400, 250, 100, 250],
            "text": "",
        },
    ]
    content_list = [
        {"type": "text", "text": "第一章 引言", "page_idx": 0},
        {"type": "text", "text": "", "page_idx": 0},
    ]

    # Create a fake zip in memory
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("test_layout.json", json.dumps(layout))
        zf.writestr("test_content_list.json", json.dumps(content_list))
    zip_buf.seek(0)

    result = parse_layout_from_zip(zip_buf.read())
    assert 0 in result  # page 0
    blocks = result[0]
    assert len(blocks) >= 1
    assert blocks[0]["text"] == "第一章 引言"
    assert "bbox" in blocks[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mineru_client.py -v`
Expected: FAIL — module `backend.engine.mineru_client` not found

- [ ] **Step 3: Write MinerU client implementation**

```python
# backend/engine/mineru_client.py
"""MinerU v4 精准解析 API client — batch upload + poll + parse layout."""

import asyncio
import io
import json
import logging
import time
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

MINERU_BASE = "https://mineru.net"

# Category IDs in MinerU layout.json that represent text
TEXT_CATEGORIES = {2, 4, 5, 6, 7}


class MinerUAPIError(Exception):
    def __init__(self, message: str, code: int = -1):
        super().__init__(message)
        self.code = code


class MinerUTimeoutError(Exception):
    pass


@dataclass
class MinerUProgress:
    extracted_pages: int
    total_pages: int
    start_time: str


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
        url = f"{MINERU_BASE}/api/v4/file-urls/batch"
        payload = {
            "files": [{"name": name} for name in file_names],
            "model_version": model_version,
            "language": language,
            "enable_table": enable_table,
            "is_ocr": is_ocr,
            "enable_formula": enable_formula,
        }
        resp = await self._client.post(url, json=payload)
        data = resp.json()
        if data.get("code") != 0:
            raise MinerUAPIError(data.get("msg", "unknown error"), data.get("code", -1))
        return data["data"]["batch_id"], data["data"]["file_urls"]

    async def upload_file(self, file_url: str, pdf_bytes: bytes):
        resp = await self._client.put(file_url, content=pdf_bytes)
        if resp.status_code not in (200, 201):
            raise MinerUAPIError(f"upload failed: HTTP {resp.status_code}")

    async def poll_until_done(
        self,
        batch_id: str,
        timeout: int = 1800,
        poll_interval: float = 5.0,
        progress_callback=None,
    ) -> Dict[str, Any]:
        url = f"{MINERU_BASE}/api/v4/extract-results/batch/{batch_id}"
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            resp = await self._client.get(url)
            data = resp.json()
            if data.get("code") != 0:
                raise MinerUAPIError(data.get("msg", "query failed"))

            results = data["data"]["extract_result"]
            if not results:
                await asyncio.sleep(poll_interval)
                continue

            file_result = results[0]
            state = file_result["state"]

            if state == "done":
                return file_result
            if state == "failed":
                raise MinerUAPIError(file_result.get("err_msg", "parse failed"))
            if state in ("running", "pending") and progress_callback:
                progress = file_result.get("extract_progress", {})
                extracted = progress.get("extracted_pages", 0)
                total = progress.get("total_pages", 0)
                progress_callback(extracted, total, state)

            await asyncio.sleep(poll_interval)

        raise MinerUTimeoutError(f"batch {batch_id} did not complete within {timeout}s")

    async def download_zip(self, zip_url: str) -> bytes:
        resp = await self._client.get(zip_url)
        resp.raise_for_status()
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
        batch_id, file_urls = await self.submit_batch([file_name], model_version=model_version)
        await self.upload_file(file_urls[0], pdf_bytes)
        result = await self.poll_until_done(batch_id, progress_callback=progress_callback)
        return await self.download_zip(result["full_zip_url"])


def parse_layout_from_zip(zip_bytes: bytes) -> Dict[int, List[Dict[str, Any]]]:
    """Parse MinerU result zip, return {page_index: [text_blocks]}.

    Each text_block has: 'text', 'bbox' (x0,y0,x1,y1 in px), 'category_id'
    """
    pages: Dict[int, List[Dict]] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        name_list = zf.namelist()

        # Find the layout.json and content_list.json
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mineru_client.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/engine/mineru_client.py tests/test_mineru_client.py
git commit -m "feat: add MinerU v4 API client with batch upload and layout parsing"
```

---

### Task 3: PaddleOCR-VL-1.5 Online API Client

**Files:**
- Create: `backend/engine/paddleocr_online_client.py`
- Test: `tests/test_paddleocr_online_client.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_paddleocr_online_client.py
import base64
import pytest
from unittest.mock import AsyncMock, patch

from backend.engine.paddleocr_online_client import (
    PaddleOCRClient,
    PaddleOCRAPIError,
    parse_paddleocr_result,
)

EXAMPLE_MARKDOWN = """# 第一章
这是一段测试文本。
## 1.1 测试节
更多内容在这里。"""

@pytest.fixture
def client():
    return PaddleOCRClient(
        token="test-paddle-token",
        endpoint="https://aistudio.baidu.com/serving/test-endpoint",
    )

def test_parse_paddleocr_result_extracts_pages():
    raw = {
        "result": {
            "layoutParsingResults": [
                {"markdown": {"text": EXAMPLE_MARKDOWN, "images": {}}, "outputImages": {}},
            ]
        }
    }
    pages = parse_paddleocr_result(raw)
    assert len(pages) == 1
    assert pages[0]["markdown"].startswith("# 第一章")

def test_parse_paddleocr_result_multi_page():
    raw = {
        "result": {
            "layoutParsingResults": [
                {"markdown": {"text": "# Page 1\ncontent", "images": {}}, "outputImages": {}},
                {"markdown": {"text": "# Page 2\nmore content", "images": {}}, "outputImages": {}},
            ]
        }
    }
    pages = parse_paddleocr_result(raw)
    assert len(pages) == 2

def test_parse_paddleocr_result_empty():
    pages = parse_paddleocr_result({"result": {"layoutParsingResults": []}})
    assert pages == []

@pytest.mark.asyncio
async def test_process_pdf_sends_base64(client):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "errorCode": 0,
        "errorMsg": "Success",
        "result": {
            "layoutParsingResults": [
                {"markdown": {"text": "# Test\ncontent", "images": {}}, "outputImages": {}}
            ]
        }
    }

    with patch.object(client._client, "post", return_value=mock_response) as mock_post:
        result = await client.process_pdf(b"%PDF-1.4 fake")

    mock_post.assert_called_once()
    call_args = mock_post.call_args
    payload = call_args[1]["json"]
    assert payload["fileType"] == 0
    assert "file" in payload
    # Verify base64 encoding
    decoded = base64.b64decode(payload["file"])
    assert decoded == b"%PDF-1.4 fake"

    assert len(result) == 1
    assert result[0]["markdown"].startswith("# Test")

@pytest.mark.asyncio
async def test_process_pdf_raises_on_error(client):
    mock_response = AsyncMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {
        "errorCode": 400,
        "errorMsg": "Invalid token",
    }

    with patch.object(client._client, "post", return_value=mock_response):
        with pytest.raises(PaddleOCRAPIError, match="Invalid token"):
            await client.process_pdf(b"%PDF-1.4 fake")

@pytest.mark.asyncio
async def test_process_image_sends_filetype_1(client):
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "errorCode": 0,
        "errorMsg": "Success",
        "result": {
            "layoutParsingResults": [
                {"markdown": {"text": "image text", "images": {}}, "outputImages": {}}
            ]
        }
    }

    with patch.object(client._client, "post", return_value=mock_response) as mock_post:
        result = await client.process_image(b"\xff\xd8\xff fake jpeg")

    call_args = mock_post.call_args
    payload = call_args[1]["json"]
    assert payload["fileType"] == 1
    assert len(result) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paddleocr_online_client.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write PaddleOCR client implementation**

```python
# backend/engine/paddleocr_online_client.py
"""PaddleOCR-VL-1.5 online API client — send PDF/image, parse layout response."""

import base64
import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


class PaddleOCRAPIError(Exception):
    def __init__(self, message: str, code: int = -1):
        super().__init__(message)
        self.code = code


class PaddleOCRClient:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_paddleocr_online_client.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/engine/paddleocr_online_client.py tests/test_paddleocr_online_client.py
git commit -m "feat: add PaddleOCR-VL-1.5 online API client"
```

---

### Task 4: PDF Text Layer Embedding from API Layout Results

**Files:**
- Create: `backend/engine/pdf_api_embed.py`
- Test: `tests/test_pdf_api_embed.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_pdf_api_embed.py
import io
import os
import pytest
import pikepdf
from PIL import Image

from backend.engine.pdf_api_embed import (
    embed_api_text_layer,
    PageTextBlocks,
)

@pytest.fixture
def blank_pdf():
    """Create a minimal PDF with one blank page for testing."""
    buf = io.BytesIO()
    with pikepdf.new() as pdf:
        pdf.add_blank_page(page_size=(595, 842))  # A4
        pdf.save(buf)
    return buf.getvalue()

@pytest.fixture
def blank_pdf_two_pages():
    buf = io.BytesIO()
    with pikepdf.new() as pdf:
        pdf.add_blank_page(page_size=(595, 842))
        pdf.add_blank_page(page_size=(595, 842))
        pdf.save(buf)
    return buf.getvalue()

def test_embed_single_page_creates_text_layer(tmp_path, blank_pdf):
    input_path = str(tmp_path / "input.pdf")
    output_path = str(tmp_path / "output.pdf")
    with open(input_path, "wb") as f:
        f.write(blank_pdf)

    layout = {
        0: [
            {"text": "Hello World", "bbox": (100, 700, 200, 720), "category_id": 2},
            {"text": "Chapter One", "bbox": (100, 670, 300, 690), "category_id": 2},
        ]
    }

    embed_api_text_layer(input_path, output_path, layout)

    assert os.path.exists(output_path)
    with pikepdf.open(output_path) as pdf:
        assert len(pdf.pages) == 1

def test_embed_preserves_non_text_pages(tmp_path, blank_pdf_two_pages):
    input_path = str(tmp_path / "input.pdf")
    output_path = str(tmp_path / "output.pdf")
    with open(input_path, "wb") as f:
        f.write(blank_pdf_two_pages)

    layout = {
        0: [{"text": "Page 0 only", "bbox": (100, 700, 200, 720), "category_id": 2}]
    }

    embed_api_text_layer(input_path, output_path, layout)

    with pikepdf.open(output_path) as pdf:
        assert len(pdf.pages) == 2

def test_embed_no_bbox_uses_reading_order(tmp_path, blank_pdf):
    input_path = str(tmp_path / "input.pdf")
    output_path = str(tmp_path / "output.pdf")
    with open(input_path, "wb") as f:
        f.write(blank_pdf)

    layout = {
        0: [
            {"text": "Line 1", "bbox": None, "category_id": 2},
            {"text": "Line 2", "bbox": None, "category_id": 2},
        ]
    }

    embed_api_text_layer(input_path, output_path, layout)

    with pikepdf.open(output_path) as pdf:
        assert len(pdf.pages) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pdf_api_embed.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Write PDF embedding implementation**

```python
# backend/engine/pdf_api_embed.py
"""Embed text layer into PDF from online API layout results (MinerU/PaddleOCR)."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pikepdf

logger = logging.getLogger(__name__)

PageTextBlocks = Dict[int, List[Dict[str, Any]]]

# SimSun font path for embedding CJK text
_SIMSUN_PATH = r"C:\Windows\Fonts\simsun.ttc"

# A4 page dimensions in points (typographic)
A4_WIDTH = 595.0
A4_HEIGHT = 842.0

# Default reading-order line spacing
DEFAULT_FONT_SIZE = 10.0
DEFAULT_LINE_HEIGHT = 14.0
DEFAULT_MARGIN_LEFT = 60.0
DEFAULT_MARGIN_TOP = 60.0


def _load_cjk_font(pdf: pikepdf.Pdf):
    """Ensure a CJK font is available in the PDF for text embedding."""
    if _SIMSUN_PATH and Path(_SIMSUN_PATH).exists():
        try:
            font = pikepdf.Font(pdf, _SIMSUN_PATH)
            return font
        except Exception:
            pass

    try:
        return pikepdf.Font(pdf, "Helvetica")
    except Exception:
        return None


def embed_api_text_layer(
    input_path: str,
    output_path: str,
    layout: PageTextBlocks,
    font_size: float = DEFAULT_FONT_SIZE,
    line_height: float = DEFAULT_LINE_HEIGHT,
) -> None:
    """Embed text from API layout results into PDF as an invisible text layer.

    Args:
        input_path: Path to source PDF
        output_path: Path for output PDF with text layer
        layout: {page_index: [{"text": str, "bbox": (x0,y0,x1,y1) or None, ...}]}
        font_size: Font size in points
        line_height: Line height in points
    """
    with pikepdf.open(input_path) as pdf:
        font = _load_cjk_font(pdf)
        font_name = font.name if font else "F1"

        for page_idx, blocks in sorted(layout.items()):
            if page_idx >= len(pdf.pages):
                continue

            page = pdf.pages[page_idx]
            page_height = float(page.MediaBox[3]) if "/MediaBox" in page else A4_HEIGHT

            gs_name = pikepdf.Name("GS0")
            stream_lines = []

            # Start with graphics state (text rendering mode 3 = invisible)
            stream_lines.append("/GS0 gs")
            stream_lines.append("BT")

            if font:
                stream_lines.append(f"/{font_name} {font_size:.1f} Tf")
            else:
                stream_lines.append(f"/{font_name} {font_size:.1f} Tf")

            if blocks:
                for i, block in enumerate(blocks):
                    text = block.get("text", "")
                    if not text:
                        continue

                    bbox = block.get("bbox")
                    if bbox and len(bbox) == 4:
                        x = bbox[0]
                        y = page_height - bbox[3]  # flip Y
                    else:
                        x = DEFAULT_MARGIN_LEFT
                        y = page_height - DEFAULT_MARGIN_TOP - i * line_height

                    # Escape PDF string special characters
                    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                    stream_lines.append(f"{x:.1f} {y:.1f} Td ({escaped}) Tj")
                    stream_lines.append(f"0 {line_height:.1f} Td")

            stream_lines.append("ET")

            content_stream = pikepdf.Stream(pdf, "\n".join(stream_lines).encode("utf-8"))

            if "/Contents" in page and page.Contents is not None:
                existing = page.Contents
                if isinstance(existing, pikepdf.Array):
                    existing.append(content_stream)
                else:
                    page.Contents = pikepdf.Array([existing, content_stream])
            else:
                page.Contents = content_stream

            # Ensure Resources dictionary exists with ExtGState for invisible text
            if "/Resources" not in page:
                page.Resources = pikepdf.Dictionary()

            resources = page.Resources
            if "/ExtGState" not in resources:
                resources.ExtGState = pikepdf.Dictionary()
            resources.ExtGState.GS0 = pikepdf.Dictionary(
                Type=pikepdf.Name.ExtGState,
                TR=pikepdf.Integer(3),  # Text rendering mode 3 = invisible
            )

            if font and "/Font" not in resources:
                resources.Font = pikepdf.Dictionary()
            if font and "/Font" in resources:
                resources.Font[pikepdf.Name(font_name)] = font

        pdf.save(output_path, compress_streams=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pdf_api_embed.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/engine/pdf_api_embed.py tests/test_pdf_api_embed.py
git commit -m "feat: add PDF text layer embedding from API layout results"
```

---

### Task 5: Pipeline Integration — MinerU Engine

**Files:**
- Modify: `backend/engine/pipeline.py:2295-2538` (add mineru branch)
- Modify: `backend/engine/__init__.py` (export new symbols)

- [ ] **Step 1: Add mineru branch in pipeline _step_ocr()**

In `backend/engine/pipeline.py`, after the `if ocr_engine == "llm_ocr":` block (around line 2294), add:

```python
        elif ocr_engine == "mineru":
            mineru_token = config.get("mineru_token", "")
            if not mineru_token:
                task_store.add_log(task_id, "MinerU: no token configured, skipping")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            mineru_model = config.get("mineru_model", "vlm")
            task_store.add_log(task_id, f"MinerU OCR: uploading to MinerU v4 API (model={mineru_model})")
            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 5, "detail": "Uploading to MinerU..."})

            try:
                from backend.engine.mineru_client import MinerUClient, parse_layout_from_zip
                from backend.engine.pdf_api_embed import embed_api_text_layer

                _mineru_last_progress = [0]
                _mineru_poll_count = [0]

                def _mineru_progress(extracted, total, state):
                    if total > 0:
                        pct = min(5 + int(extracted / total * 85), 90)
                        detail = f"MinerU: {state} ({extracted}/{total} pages)"
                    else:
                        pct = min(5 + _mineru_poll_count[0] * 2, 80)
                        detail = f"MinerU: {state}..."
                    _mineru_poll_count[0] += 1
                    if pct != _mineru_last_progress[0]:
                        _mineru_last_progress[0] = pct
                        asyncio.run_coroutine_threadsafe(
                            _emit(task_id, "step_progress", {"step": "ocr", "progress": pct, "detail": detail}),
                            asyncio.get_event_loop(),
                        )

                client = MinerUClient(token=mineru_token)

                async def _run_mineru():
                    try:
                        with open(pdf_path, "rb") as f:
                            pdf_bytes = f.read()

                        zip_bytes = await client.process_pdf(
                            pdf_bytes,
                            file_name=os.path.basename(pdf_path),
                            model_version=mineru_model,
                            progress_callback=_mineru_progress,
                        )

                        layout = parse_layout_from_zip(zip_bytes)
                        task_store.add_log(task_id, f"MinerU: parsed {len(layout)} pages with text")

                        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 92, "detail": "Embedding text layer..."})

                        output_pdf = pdf_path + ".mineru.pdf"
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            None,
                            embed_api_text_layer,
                            pdf_path,
                            output_pdf,
                            layout,
                        )

                        if os.path.exists(output_pdf) and os.path.getsize(output_pdf) > 0:
                            os.replace(output_pdf, pdf_path + ".ocr.pdf")
                            report["ocr_done"] = True
                            report["pdf_path"] = pdf_path + ".ocr.pdf"
                            task_store.add_log(task_id, "MinerU OCR complete")
                        else:
                            raise RuntimeError("MinerU: embedding produced empty file")
                    finally:
                        await client.close()

                await asyncio.wait_for(_run_mineru(), timeout=config.get("ocr_timeout", 3600))

            except asyncio.TimeoutError:
                task_store.add_log(task_id, "MinerU OCR timed out")
            except Exception as e:
                task_store.add_log(task_id, f"MinerU OCR error: {str(e)[:200]}")

            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})

```

- [ ] **Step 2: Verify syntax and imports**

Run: `python -c "from backend.engine.pipeline import run_pipeline; print('OK')"`
Expected: OK (no syntax errors)

- [ ] **Step 3: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: add MinerU OCR engine branch in pipeline _step_ocr()"
```

---

### Task 6: Pipeline Integration — PaddleOCR-VL-1.5 Engine

**Files:**
- Modify: `backend/engine/pipeline.py:2295-2538` (add paddleocr_online branch after mineru)

- [ ] **Step 1: Add paddleocr_online branch in pipeline _step_ocr()**

After the `mineru` branch added in Task 5, add:

```python
        elif ocr_engine == "paddleocr_online":
            paddle_token = config.get("paddleocr_online_token", "")
            paddle_endpoint = config.get("paddleocr_online_endpoint", "")
            if not paddle_token or not paddle_endpoint:
                task_store.add_log(task_id, "PaddleOCR online: no token/endpoint configured, skipping")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            task_store.add_log(task_id, f"PaddleOCR-VL-1.5 online: sending PDF to {paddle_endpoint}")
            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 5, "detail": "Sending PDF to PaddleOCR..."})

            try:
                from backend.engine.paddleocr_online_client import PaddleOCRClient
                from backend.engine.pdf_api_embed import embed_api_text_layer

                client = PaddleOCRClient(token=paddle_token, endpoint=paddle_endpoint)

                async def _run_paddleocr():
                    try:
                        with open(pdf_path, "rb") as f:
                            pdf_bytes = f.read()

                        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 20, "detail": "PaddleOCR processing PDF..."})

                        pages = await client.process_pdf(pdf_bytes)
                        task_store.add_log(task_id, f"PaddleOCR-VL-1.5: got {len(pages)} pages")

                        # Convert markdown pages to layout format compatible with embed_api_text_layer
                        layout = {}
                        for i, page in enumerate(pages):
                            md_text = page.get("markdown", "")
                            lines = [line.strip() for line in md_text.split("\n") if line.strip()]
                            layout[i] = [
                                {"text": line, "bbox": None, "category_id": 2}
                                for line in lines
                            ]

                        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 85, "detail": "Embedding text layer..."})

                        output_pdf = pdf_path + ".paddleocr.pdf"
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(
                            None,
                            embed_api_text_layer,
                            pdf_path,
                            output_pdf,
                            layout,
                        )

                        if os.path.exists(output_pdf) and os.path.getsize(output_pdf) > 0:
                            os.replace(output_pdf, pdf_path + ".ocr.pdf")
                            report["ocr_done"] = True
                            report["pdf_path"] = pdf_path + ".ocr.pdf"
                            task_store.add_log(task_id, "PaddleOCR-VL-1.5 online OCR complete")
                        else:
                            raise RuntimeError("PaddleOCR: embedding produced empty file")
                    finally:
                        await client.close()

                await asyncio.wait_for(_run_paddleocr(), timeout=config.get("ocr_timeout", 3600))

            except asyncio.TimeoutError:
                task_store.add_log(task_id, "PaddleOCR online timed out")
            except Exception as e:
                task_store.add_log(task_id, f"PaddleOCR online error: {str(e)[:200]}")

            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
```

- [ ] **Step 2: Verify syntax**

Run: `python -c "from backend.engine.pipeline import run_pipeline; print('OK')"`
Expected: OK

- [ ] **Step 3: Add engine labels to config_info block**

Update the engine_labels dict around line 2067 to include:

```python
        engine_labels = {
            "tesseract": "Tesseract OCR",
            "paddleocr": "PaddleOCR",
            "mineru": "MinerU 线上 API",
            "paddleocr_online": "PaddleOCR-VL-1.5 线上 API",
        }
```

- [ ] **Step 4: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: add PaddleOCR-VL-1.5 online engine branch in pipeline _step_ocr()"
```

---

### Task 7: Frontend UI — Provider Selection & Settings

**Files:**
- Modify: `frontend/src/components/ConfigSettings.tsx` (add UI panels near the LLM OCR section, around lines 1753-1874)
- Modify: `frontend/src/constants.ts` (verification in Task 1)

- [ ] **Step 1: Add MinerU settings panel**

In `ConfigSettings.tsx`, find the OCR engine selector section (around where `ocr_engine` radio buttons are rendered) and add after the LLM OCR panel:

```tsx
{/* MinerU Settings */}
{localConfig.ocr_engine === 'mineru' && (
  <div style={{ marginTop: 16, padding: 12, backgroundColor: '#f8f9fa', borderRadius: 8 }}>
    <p style={{ fontWeight: 600, marginBottom: 8 }}>MinerU 设置</p>
    <p style={{ fontSize: 13, color: '#666', marginBottom: 8 }}>
      使用上海 AI Lab MinerU 精准解析 API。文档解析需要将 PDF 上传至 MinerU 服务器，仅限中国大陆网络访问。
    </p>
    <div style={{ marginBottom: 8 }}>
      <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>API Token</label>
      <Input
        value={localConfig.mineru_token || ''}
        onChange={e => setLocalConfig({...localConfig, mineru_token: e.target.value})}
        placeholder="输入 MinerU API Token（Bearer 认证）"
        style={{ fontFamily: 'monospace' }}
      />
    </div>
    <div style={{ marginBottom: 8 }}>
      <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>模型版本</label>
      <Select
        value={localConfig.mineru_model || 'vlm'}
        onChange={v => setLocalConfig({...localConfig, mineru_model: v})}
        options={[
          { value: 'pipeline', label: 'pipeline（传统引擎）' },
          { value: 'vlm', label: 'vlm（推荐，视觉大模型）' },
          { value: 'MinerU-HTML', label: 'MinerU-HTML（仅 HTML 文件）' },
        ]}
        style={{ width: '100%' }}
      />
    </div>
    <div style={{ fontSize: 12, color: '#999' }}>
      限制：≤200MB / ≤200页。需中国大陆网络。<a href="https://mineru.net/apiManage/docs" target="_blank">API 文档</a>
    </div>
  </div>
)}

{/* PaddleOCR-VL-1.5 Online Settings */}
{localConfig.ocr_engine === 'paddleocr_online' && (
  <div style={{ marginTop: 16, padding: 12, backgroundColor: '#f8f9fa', borderRadius: 8 }}>
    <p style={{ fontWeight: 600, marginBottom: 8 }}>PaddleOCR-VL-1.5 设置</p>
    <p style={{ fontSize: 13, color: '#666', marginBottom: 8 }}>
      使用百度 AI Studio 部署的 PaddleOCR-VL-1.5 视觉大模型 API。支持中英文文档版面解析。
    </p>
    <div style={{ marginBottom: 8 }}>
      <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>API 端点</label>
      <Input
        value={localConfig.paddleocr_online_endpoint || ''}
        onChange={e => setLocalConfig({...localConfig, paddleocr_online_endpoint: e.target.value})}
        placeholder="https://aistudio.baidu.com/serving/xxx"
        style={{ fontFamily: 'monospace' }}
      />
    </div>
    <div style={{ marginBottom: 8 }}>
      <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>Access Token</label>
      <Input
        value={localConfig.paddleocr_online_token || ''}
        onChange={e => setLocalConfig({...localConfig, paddleocr_online_token: e.target.value})}
        placeholder="输入 PaddleOCR access token"
        style={{ fontFamily: 'monospace' }}
      />
    </div>
    <div style={{ fontSize: 12, color: '#999' }}>
      从 <a href="https://aistudio.baidu.com/paddleocr/task" target="_blank">PaddleOCR 控制台</a> 获取端点和 Token。
      <a href="https://ai.baidu.com/ai-doc/AISTUDIO/Cmkz2m0ma" target="_blank">API 文档</a>
    </div>
  </div>
)}
```

- [ ] **Step 2: Add new config fields to localConfig interface**

In the `interface AppConfig` used by `ConfigSettings.tsx` (around line 20-42), add:

```typescript
  mineru_token: string        // line ~40
  mineru_model: string        // line ~41
  paddleocr_online_token: string    // line ~42
  paddleocr_online_endpoint: string // line ~43
```

- [ ] **Step 3: Add engine config summary info for confirmation dialog**

Find the `config_info` builder around line 2060 and add:

In the mineru branch:
```python
        config_info = {
            "引擎": "MinerU 线上 API",
            "模型": config.get("mineru_model", "vlm"),
            "限制": "≤200MB / ≤200页",
        }
```

In the paddleocr_online branch:
```python
        config_info = {
            "引擎": "PaddleOCR-VL-1.5 线上 API",
            "端点": config.get("paddleocr_online_endpoint", ""),
        }
```

- [ ] **Step 4: Verify frontend compiles**

Run: `cd frontend; npm run build 2>&1 | Select-Object -Last 5`
Expected: build succeeds

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConfigSettings.tsx backend/engine/pipeline.py
git commit -m "feat: add MinerU and PaddleOCR-VL-1.5 settings UI panels"
```

---

### Task 8: Final Integration & Verification

**Files:**
- Modify: `backend/engine/__init__.py`

- [ ] **Step 1: Update backend/engine/__init__.py exports**

```python
from backend.engine.mineru_client import MinerUClient, MinerUAPIError, MinerUTimeoutError, parse_layout_from_zip
from backend.engine.paddleocr_online_client import PaddleOCRClient, PaddleOCRAPIError, parse_paddleocr_result
from backend.engine.pdf_api_embed import embed_api_text_layer
```

- [ ] **Step 2: Run all new tests**

```bash
cd D:\opencode\book-downloader
pytest tests/test_mineru_client.py tests/test_paddleocr_online_client.py tests/test_pdf_api_embed.py -v
```
Expected: all ~15 tests pass

- [ ] **Step 3: Run backend import check**

Run: `python -c "from backend.engine.mineru_client import MinerUClient; from backend.engine.paddleocr_online_client import PaddleOCRClient; from backend.engine.pdf_api_embed import embed_api_text_layer; print('All imports OK')"`
Expected: All imports OK

- [ ] **Step 4: Commit**

```bash
git add backend/engine/__init__.py
git commit -m "chore: export new online OCR API modules from engine package"
```

---

## Self-Review Checklist

### 1. Spec Coverage
- [x] MinerU API support — Tasks 2, 5
- [x] PaddleOCR-VL-1.5 API support — Tasks 3, 6
- [x] MinerU token-based auth (Bearer) — Task 2
- [x] PaddleOCR token-based auth (token prefix) — Task 3
- [x] China mainland network note for MinerU — Tasks 5, 7
- [x] Proxy concern noted — Task 2 (timeout config)
- [x] Rasterization/layout detection kept as-is — Architecture decision (APIs do their own)
- [x] Frontend provider selection — Task 1, 7
- [x] Config persistence — Task 1
- [x] BW compression still works post-OCR — Architecture (output_path feeds into existing compression)

### 2. Placeholder Scan
- No "TBD", "TODO", "implement later"
- All code blocks are complete, compilable implementations
- All test cases have assertions
- No edge-case hand-waving

### 3. Type Consistency
- `MinerUClient` constructor from Task 2 matches usage in Task 5
- `PaddleOCRClient` constructor from Task 3 matches usage in Task 6
- `embed_api_text_layer` signature from Task 4 matches usage in Tasks 5, 6
- `parse_layout_from_zip` returns `Dict[int, List[Dict]]` — consistent with `embed_api_text_layer`'s `PageTextBlocks`
- `parse_paddleocr_result` returns `List[Dict]` — converted to `PageTextBlocks` in Task 6

## Known Limitations (noted in plan)

1. **MinerU requires China mainland network** — users behind non-CN proxies will get timeout. Plan notes this in UI and logs.
2. **PaddleOCR-VL-1.5 markdown has no bbox data** — uses reading-order positioning with default margins. Text is searchable but positions may not match visual layout exactly.
3. **PaddleOCR endpoint/API_URL is user-specific** — users must obtain from PaddleOCR console.
4. **MinerU batch poll sleep is blocking** — uses `asyncio.sleep()` which is fine for async, but a single-file optimization could be added later.
5. **No progress during PaddleOCR processing** — the PaddleOCR API call is synchronous (POST → wait → response), so progress stays at 20% until complete.
