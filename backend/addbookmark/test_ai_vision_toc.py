import os
import tempfile
import pytest


SIMHEI_PATH = r"C:\Windows\Fonts\simhei.ttf"


def _has_chinese_font():
    return os.path.exists(SIMHEI_PATH)


def _insert_cn(page, x, y, text):
    """Insert Chinese text using SimHei font."""
    import fitz
    page.insert_font(fontname="SimHei", fontfile=SIMHEI_PATH)
    page.insert_text((x, y), text, fontname="SimHei", fontsize=11)


def test_find_toc_pages_finds_contents_header():
    """Should detect pages containing 目录/目 录/CONTENTS with page refs."""
    from addbookmark.ai_vision_toc import find_toc_pages
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not installed")
    if not _has_chinese_font():
        pytest.skip("SimHei font not found")

    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        doc = fitz.open()
        doc.new_page()
        _insert_cn(doc[0], 72, 72, "书名")

        p1 = doc.new_page()
        _insert_cn(p1, 72, 72, "目 录")
        _insert_cn(p1, 72, 100, "第一章 概论 ..... 1")
        _insert_cn(p1, 72, 120, "第二章 基础 ..... 15")

        p2 = doc.new_page()
        _insert_cn(p2, 72, 72, "第三章 实验 ..... 30")

        p3 = doc.new_page()
        _insert_cn(p3, 72, 72, "第一章 概论")

        doc.save(pdf_path)
        doc.close()

        start, end = find_toc_pages(pdf_path)
        assert start == 1
        assert end >= 2
    finally:
        os.unlink(pdf_path)


def test_find_toc_pages_no_toc():
    from addbookmark.ai_vision_toc import find_toc_pages
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not installed")

    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        doc = fitz.open()
        for i in range(5):
            doc.new_page().insert_text((72, 72), f"Body text page {i+1}.")
        doc.save(pdf_path)
        doc.close()

        start, end = find_toc_pages(pdf_path)
        assert start == -1
    finally:
        os.unlink(pdf_path)


def test_find_toc_pages_rejects_chapter_opening():
    """Chapter opening page with section headers but no page refs should NOT be detected."""
    from addbookmark.ai_vision_toc import find_toc_pages
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not installed")
    if not _has_chinese_font():
        pytest.skip("SimHei font not found")

    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        doc = fitz.open()
        doc.new_page()
        _insert_cn(doc[0], 72, 72, "书名")

        p1 = doc.new_page()
        _insert_cn(p1, 72, 72, "第一章 概论")
        _insert_cn(p1, 72, 100, "1.1 背景")
        _insert_cn(p1, 72, 120, "1.2 方法")
        _insert_cn(p1, 72, 140, "1.3 意义")
        _insert_cn(p1, 72, 160, "1.4 结构")

        p2 = doc.new_page()
        _insert_cn(p2, 72, 72, "正文")

        doc.save(pdf_path)
        doc.close()

        start, end = find_toc_pages(pdf_path)
        assert start == -1
    finally:
        os.unlink(pdf_path)


def test_find_toc_pages_density_with_page_refs():
    """Dense chapter entries WITH page refs should be detected even without header."""
    from addbookmark.ai_vision_toc import find_toc_pages
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not installed")
    if not _has_chinese_font():
        pytest.skip("SimHei font not found")

    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        doc = fitz.open()
        doc.new_page()
        _insert_cn(doc[0], 72, 72, "书名")

        p1 = doc.new_page()
        for j in range(8):
            _insert_cn(p1, 72, 72 + j * 20, f"第{j+1}章 标题 ..... {(j+1)*10}")

        p2 = doc.new_page()
        _insert_cn(p2, 72, 72, "正文")

        doc.save(pdf_path)
        doc.close()

        start, end = find_toc_pages(pdf_path)
        assert start == 1
    finally:
        os.unlink(pdf_path)


def test_find_toc_pages_rejects_garbled_ocr():
    """Garbled OCR text containing '目录' should be rejected by CJK ratio check."""
    from addbookmark.ai_vision_toc import find_toc_pages
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not installed")

    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        doc = fitz.open()
        p = doc.new_page()
        # Mostly ASCII with "目录" accidentally present — CJK ratio < 30%
        p.insert_text((72, 72), "xx目 录zz  abcdefgh  ijklmnop  qrstuvwx")
        p.insert_text((72, 100), "chapter one ..... 1")
        doc.save(pdf_path)
        doc.close()

        start, end = find_toc_pages(pdf_path)
        assert start == -1
    finally:
        os.unlink(pdf_path)
