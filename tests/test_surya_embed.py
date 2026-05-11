import io
import os
import pytest
import fitz

from backend.engine.pdf_api_embed import embed_with_surya_boxes


@pytest.fixture
def blank_pdf():
    buf = io.BytesIO()
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def test_embed_surya_boxes_creates_output(tmp_path, blank_pdf):
    input_path = str(tmp_path / "input.pdf")
    output_path = str(tmp_path / "output.pdf")
    with open(input_path, "wb") as f:
        f.write(blank_pdf)

    surya_boxes = {0: [[0.1, 0.2, 0.9, 0.25], [0.1, 0.3, 0.9, 0.35]]}
    page_texts = {0: ["Hello World", "Chapter One"]}

    embed_with_surya_boxes(input_path, output_path, surya_boxes, page_texts)

    assert os.path.exists(output_path)
    doc = fitz.open(output_path)
    assert len(doc) == 1
    doc.close()


def test_embed_surya_boxes_more_boxes_than_text(tmp_path, blank_pdf):
    input_path = str(tmp_path / "input.pdf")
    output_path = str(tmp_path / "output.pdf")
    with open(input_path, "wb") as f:
        f.write(blank_pdf)

    # More boxes than texts — extra boxes get empty string, skipped gracefully
    surya_boxes = {0: [[0.1, 0.2, 0.9, 0.25], [0.1, 0.3, 0.9, 0.35]]}
    page_texts = {0: ["Line 1"]}

    embed_with_surya_boxes(input_path, output_path, surya_boxes, page_texts)
    assert os.path.exists(output_path)


def test_embed_surya_boxes_empty_page_skipped(tmp_path, blank_pdf):
    input_path = str(tmp_path / "input.pdf")
    output_path = str(tmp_path / "output.pdf")
    with open(input_path, "wb") as f:
        f.write(blank_pdf)

    surya_boxes = {0: []}
    page_texts = {0: []}

    embed_with_surya_boxes(input_path, output_path, surya_boxes, page_texts)
    assert os.path.exists(output_path)
