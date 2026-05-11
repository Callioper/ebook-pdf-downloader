import base64
import pytest
from unittest.mock import MagicMock, patch

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
    mock_response = MagicMock()
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
    decoded = base64.b64decode(payload["file"])
    assert decoded == b"%PDF-1.4 fake"
    assert len(result) == 1
    assert result[0]["markdown"].startswith("# Test")

@pytest.mark.asyncio
async def test_process_pdf_raises_on_error(client):
    mock_response = MagicMock()
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
    mock_response = MagicMock()
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
