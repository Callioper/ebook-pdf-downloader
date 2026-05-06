"""Inject hierarchical bookmarks into PDF via PyMuPDF."""

import fitz
from addbookmark.bookmark_parser import parse_bookmark_hierarchy
from addbookmark.bookmark_offset import find_toc_page_by_label


def inject_bookmarks(
    pdf_path: str,
    bookmark_text: str,
    output_path: str,
    offset: int = 0,
) -> str:
    """
    Inject 书葵网 bookmarks into PDF.

    Args:
        pdf_path: Input PDF path.
        bookmark_text: 书葵网 raw bookmark text.
        output_path: Output PDF path.
        offset: Page offset (shukui_page + offset = PDF_viewer_page).

    Returns:
        Output file path.
    """
    doc = fitz.open(pdf_path)
    total = len(doc)

    outlines = parse_bookmark_hierarchy(bookmark_text)
    if not outlines:
        doc.save(output_path)
        doc.close()
        return output_path

    toc_entries = []

    # Add TOC page as first bookmark
    toc_page = find_toc_page_by_label(pdf_path)
    if toc_page >= 0:
        toc_entries.append([1, '目 录', toc_page + 1])

    # Add chapter bookmarks
    for title, shukui_page, level in outlines:
        page_num = shukui_page + offset
        page_num = max(1, min(page_num, total))
        toc_entries.append([level, title, page_num])

    doc.set_toc(toc_entries)
    doc.save(output_path)
    doc.close()
    return output_path
