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
    mock_response = MagicMock()
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
    mock_response = MagicMock()
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
    pending_resp = MagicMock()
    pending_resp.status_code = 200
    pending_resp.json.return_value = {
        "code": 0,
        "data": {
            "batch_id": "batch-abc",
            "extract_result": [{"file_name": "test.pdf", "state": "running"}],
        },
    }

    done_resp = MagicMock()
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
    failed_resp = MagicMock()
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
    running_resp = MagicMock()
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

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("test_layout.json", json.dumps(layout))
        zf.writestr("test_content_list.json", json.dumps(content_list))
    zip_buf.seek(0)

    result = parse_layout_from_zip(zip_buf.read())
    assert 0 in result
    blocks = result[0]
    assert len(blocks) >= 1
    assert blocks[0]["text"] == "第一章 引言"
    assert "bbox" in blocks[0]
