import json
import pytest
from unittest.mock import MagicMock, patch

from backend.engine.paddleocr_online_client import (
    PaddleOCRClient,
    PaddleOCRAPIError,
    parse_jsonl_result,
    PADDLEOCR_JOB_URL,
)

EXAMPLE_JSONL = json.dumps({
    "result": {
        "layoutParsingResults": [
            {"markdown": {"text": "# Test\ncontent", "images": {}}, "outputImages": {}}
        ]
    }
}) + "\n"


@pytest.fixture
def client():
    return PaddleOCRClient(token="test-token")

def test_parse_jsonl_result_single_page():
    pages = parse_jsonl_result(EXAMPLE_JSONL)
    assert len(pages) == 1
    assert pages[0]["markdown"].startswith("# Test")

def test_parse_jsonl_result_multi_page():
    text = EXAMPLE_JSONL + json.dumps({
        "result": {
            "layoutParsingResults": [
                {"markdown": {"text": "# Page 2", "images": {}}, "outputImages": {}}
            ]
        }
    }) + "\n"
    pages = parse_jsonl_result(text)
    assert len(pages) == 2
    assert pages[1]["markdown"].startswith("# Page 2")

def test_parse_jsonl_result_empty():
    pages = parse_jsonl_result("")
    assert pages == []

def test_parse_jsonl_result_empty_lines():
    pages = parse_jsonl_result("\n\n  \n")
    assert pages == []

@pytest.mark.asyncio
async def test_submit_job_file_returns_job_id(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": {"jobId": "job-abc-123"}
    }

    with patch.object(client._client, "post", return_value=mock_response) as mock_post:
        job_id = await client.submit_job_file("test.pdf", b"%PDF-1.4 fake")

    assert job_id == "job-abc-123"
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert call_args[1]["data"]["model"] == "PaddleOCR-VL-1.5"
    assert "files" in call_args[1]

@pytest.mark.asyncio
async def test_submit_job_file_raises_on_error(client):
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "bad request"

    with patch.object(client._client, "post", return_value=mock_response):
        with pytest.raises(PaddleOCRAPIError, match="job submission failed"):
            await client.submit_job_file("test.pdf", b"bad data")

@pytest.mark.asyncio
async def test_poll_job_returns_on_done(client):
    done_resp = MagicMock()
    done_resp.status_code = 200
    done_resp.json.return_value = {
        "data": {
            "state": "done",
            "extractProgress": {"extractedPages": 5, "totalPages": 5},
            "resultUrl": {"jsonUrl": "https://cdn.example.com/result.jsonl"}
        }
    }

    with patch.object(client._client, "get", return_value=done_resp):
        result = await client.poll_job("job-xyz", poll_interval=0.01)

    assert result["state"] == "done"
    assert result["resultUrl"]["jsonUrl"] == "https://cdn.example.com/result.jsonl"

@pytest.mark.asyncio
async def test_poll_job_raises_on_failed(client):
    failed_resp = MagicMock()
    failed_resp.status_code = 200
    failed_resp.json.return_value = {
        "data": {"state": "failed", "errorMsg": "file too large"}
    }

    with patch.object(client._client, "get", return_value=failed_resp):
        with pytest.raises(PaddleOCRAPIError, match="file too large"):
            await client.poll_job("job-xyz", poll_interval=0.01)

@pytest.mark.asyncio
async def test_poll_job_raises_timeout(client):
    running_resp = MagicMock()
    running_resp.status_code = 200
    running_resp.json.return_value = {
        "data": {"state": "running"}
    }

    with patch.object(client._client, "get", return_value=running_resp):
        with pytest.raises(PaddleOCRAPIError, match="did not complete"):
            await client.poll_job("job-xyz", timeout=0.1, poll_interval=0.01)

@pytest.mark.asyncio
async def test_download_jsonl_returns_pages(client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = EXAMPLE_JSONL

    with patch.object(client._client, "get", return_value=mock_response):
        pages = await client.download_jsonl("https://cdn.example.com/result.jsonl")

    assert len(pages) == 1
    assert pages[0]["markdown"].startswith("# Test")
