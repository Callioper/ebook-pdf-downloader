import json
import pytest
from unittest.mock import patch, AsyncMock

from engine.surya_detect import (
    run_surya_detect,
    SuryaDetectError,
    parse_detect_output,
)


def test_parse_detect_output():
    raw = json.dumps({
        "pages": [
            {"page": 0, "width": 595.0, "height": 842.0, "boxes": [[0.1, 0.2, 0.9, 0.25], [0.1, 0.3, 0.9, 0.35]]},
            {"page": 1, "width": 612.0, "height": 792.0, "boxes": [[0.05, 0.1, 0.95, 0.15]]},
        ]
    }) + "\n"

    result = parse_detect_output(raw)
    assert 0 in result
    assert 1 in result
    assert len(result[0]) == 2
    assert result[0][0] == [0.1, 0.2, 0.9, 0.25]
    assert len(result[1]) == 1


def test_parse_detect_output_empty_page():
    raw = json.dumps({
        "pages": [{"page": 0, "width": 595.0, "height": 842.0, "boxes": []}]
    }) + "\n"

    result = parse_detect_output(raw)
    assert 0 in result
    assert result[0] == []


def test_parse_detect_output_invalid_json():
    with pytest.raises(SuryaDetectError):
        parse_detect_output("not json")


@pytest.mark.asyncio
async def test_run_surya_detect_mock():
    mock_output = json.dumps({
        "pages": [{"page": 0, "width": 595.0, "height": 842.0, "boxes": [[0.1, 0.2, 0.9, 0.25]]}]
    }) + "\n"

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(mock_output.encode(), b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await run_surya_detect("test.pdf", dpi=200, pages=None)

    assert 0 in result
    assert result[0] == [[0.1, 0.2, 0.9, 0.25]]


@pytest.mark.asyncio
async def test_run_surya_detect_process_failure():
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"error message"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        with pytest.raises(SuryaDetectError, match="exit code 1"):
            await run_surya_detect("test.pdf")
