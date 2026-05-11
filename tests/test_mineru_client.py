import io
import zipfile
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from engine.mineru_client import (
    MinerUClient,
    MinerUAPIError,
    MinerUTimeoutError,
    parse_layout_from_zip,
)


@pytest.fixture
def client():
    return MinerUClient(token="test-token-123")


@pytest.mark.asyncio
async def test_submit_batch_returns_batch_id(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "code": 0,
        "data": {"batch_id": "batch-abc-123", "file_urls": ["https://oss.example.com/upload/abc"]},
        "msg": "ok",
    }
    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("engine.mineru_client.httpx.AsyncClient", return_value=mock_client):
        batch_id, file_urls = await client.submit_batch(file_names=["test.pdf"], model_version="vlm")

    assert batch_id == "batch-abc-123"
    assert file_urls == ["https://oss.example.com/upload/abc"]


@pytest.mark.asyncio
async def test_upload_file_sends_raw_bytes(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    pdf_bytes = b"%PDF-1.4 fake pdf content"
    with patch("engine.mineru_client.httpx.AsyncClient") as mock_client_cls:
        mock_up = MagicMock()
        mock_up.put = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value.__aenter__.return_value = mock_up

        await client.upload_file("https://oss.example.com/upload/abc", pdf_bytes)

        mock_up.put.assert_called_once()
        call_args = mock_up.put.call_args
        assert call_args[0][0] == "https://oss.example.com/upload/abc"
        assert call_args[1]["content"] == pdf_bytes


@pytest.mark.asyncio
async def test_poll_until_done_returns_zip_url(client):
    pending_resp = MagicMock()
    pending_resp.status_code = 200
    pending_resp.json.return_value = {
        "code": 0,
        "data": {"batch_id": "batch-abc", "extract_result": [{"file_name": "test.pdf", "state": "running"}]},
    }

    done_resp = MagicMock()
    done_resp.status_code = 200
    done_resp.json.return_value = {
        "code": 0,
        "data": {
            "batch_id": "batch-abc",
            "extract_result": [{
                "file_name": "test.pdf", "state": "done",
                "full_zip_url": "https://cdn.example.com/result.zip",
            }],
        },
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=[pending_resp, done_resp])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("engine.mineru_client.httpx.AsyncClient", return_value=mock_client):
        result = await client.poll_until_done("batch-abc", poll_interval=0.01)

    assert result["full_zip_url"] == "https://cdn.example.com/result.zip"


@pytest.mark.asyncio
async def test_poll_raises_on_failed(client):
    failed_resp = MagicMock()
    failed_resp.status_code = 200
    failed_resp.json.return_value = {
        "code": 0,
        "data": {"batch_id": "batch-abc", "extract_result": [{"file_name": "test.pdf", "state": "failed", "err_msg": "file too large"}]},
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=failed_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("engine.mineru_client.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(MinerUAPIError, match="file too large"):
            await client.poll_until_done("batch-abc", poll_interval=0.01)


@pytest.mark.asyncio
async def test_poll_raises_timeout(client):
    running_resp = MagicMock()
    running_resp.status_code = 200
    running_resp.json.return_value = {
        "code": 0,
        "data": {"batch_id": "batch-abc", "extract_result": [{"file_name": "test.pdf", "state": "running"}]},
    }

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=running_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("engine.mineru_client.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(MinerUTimeoutError):
            await client.poll_until_done("batch-abc", timeout=0.1, poll_interval=0.01)


def test_parse_layout_json_extracts_text_blocks():
    content_list = [
        {"type": "text", "text": "\u7b2c\u4e00\u7ae0 \u5f15\u8a00", "bbox": [100, 200, 400, 220], "page_idx": 0},
        {"type": "text", "text": "", "bbox": [100, 230, 400, 250], "page_idx": 0},
    ]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("test_content_list.json", json.dumps(content_list))
    zip_buf.seek(0)

    result = parse_layout_from_zip(zip_buf.read())
    assert 0 in result
    blocks = result[0]
    assert len(blocks) >= 1
    assert blocks[0]["text"] == "\u7b2c\u4e00\u7ae0 \u5f15\u8a00"
    assert "bbox" in blocks[0]
