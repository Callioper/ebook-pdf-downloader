"""Calculate page offset between 书葵网 pages and actual PDF pages."""


def find_toc_page_by_label(pdf_path: str) -> int:
    """
    Locate TOC page by page label.

    DuXiu scan naming: !00001.jpg = TOC page.
    Returns: 0-indexed physical page number, or -1 if not found.
    """
    import fitz
    doc = fitz.open(pdf_path)
    for i in range(min(30, len(doc))):
        label = doc[i].get_label()
        if label == '!00001.jpg':
            doc.close()
            return i
    doc.close()
    return -1


def detect_offset_by_label_match(
    scanned_pdf: str,
    ocr_pdf: str,
    bookmark_text: str
) -> int:
    """
    Calculate offset via OCR cross-reference using label=000001.jpg anchor.

    Formula: offset = (anchor_physical_page + 1) - anchor_shukui_page
    """
    import fitz
    scanned = fitz.open(scanned_pdf)
    ocr_doc = fitz.open(ocr_pdf)

    lines = bookmark_text.strip().split('\n')
    anchor_shukui_page = None
    for line in lines:
        parts = line.split('\t')
        if len(parts) >= 2:
            try:
                anchor_shukui_page = int(parts[1].strip())
                break
            except ValueError:
                continue

    if anchor_shukui_page is None:
        scanned.close()
        ocr_doc.close()
        return 0

    stacks_anchor_page = None
    for i in range(len(scanned)):
        if scanned[i].get_label() == '000001.jpg':
            stacks_anchor_page = i
            break

    if stacks_anchor_page is None:
        scanned.close()
        ocr_doc.close()
        return 0

    offset = (stacks_anchor_page + 1) - anchor_shukui_page

    scanned.close()
    ocr_doc.close()
    return offset
