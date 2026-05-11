import io
import os
import pytest
import fitz

from engine.pdf_api_embed import embed_api_text_layer


@pytest.fixture
def blank_pdf():
    """Create a minimal PDF with one blank page."""
    buf = io.BytesIO()
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(buf)
    doc.close()
    return buf.getvalue()


@pytest.fixture
def blank_pdf_two_pages():
    buf = io.BytesIO()
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.new_page(width=595, height=842)
    doc.save(buf)
    doc.close()
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
    doc = fitz.open(output_path)
    assert len(doc) == 1
    doc.close()


def test_embed_preserves_non_text_pages(tmp_path, blank_pdf_two_pages):
    input_path = str(tmp_path / "input.pdf")
    output_path = str(tmp_path / "output.pdf")
    with open(input_path, "wb") as f:
        f.write(blank_pdf_two_pages)

    layout = {
        0: [{"text": "Page 0 only", "bbox": (100, 700, 200, 720), "category_id": 2}]
    }

    embed_api_text_layer(input_path, output_path, layout)

    doc = fitz.open(output_path)
    assert len(doc) == 2
    doc.close()


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

    doc = fitz.open(output_path)
    assert len(doc) == 1
    doc.close()
