"""PDF utility: split PDF into chunks for API processing."""
import os
import tempfile
from typing import List

import fitz


def get_pdf_info(pdf_path: str) -> tuple[int, int]:
    """Return (page_count, file_size_bytes)."""
    size = os.path.getsize(pdf_path)
    doc = fitz.open(pdf_path)
    pages = len(doc)
    doc.close()
    return pages, size


def split_pdf(pdf_path: str, max_pages: int = 50) -> List[str]:
    """Split a PDF into chunks of max_pages each. Returns list of temp file paths."""
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    if total_pages <= max_pages:
        doc.close()
        return [pdf_path]

    chunks = []
    for start in range(0, total_pages, max_pages):
        end = min(start + max_pages, total_pages) - 1
        sub = fitz.open()
        sub.insert_pdf(doc, from_page=start, to_page=end)
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        sub.save(tmp.name, garbage=3, deflate=True)
        sub.close()
        chunks.append(tmp.name)
    doc.close()
    return chunks


def cleanup_chunks(chunks: List[str], original: str) -> None:
    """Delete temp chunk files (skip original)."""
    for p in chunks:
        if p != original and os.path.exists(p):
            os.unlink(p)
