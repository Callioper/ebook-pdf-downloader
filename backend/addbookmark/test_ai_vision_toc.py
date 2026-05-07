import asyncio
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


def test_call_vision_llm_missing_endpoint():
    from addbookmark.ai_vision_toc import call_vision_llm
    with pytest.raises(ValueError, match="endpoint"):
        asyncio.run(
            call_vision_llm(images=["fake"], prompt="test", endpoint="", model="m", api_key="k")
        )


def test_build_vision_prompt_contains_status_instructions():
    from addbookmark.ai_vision_toc import build_vision_prompt
    prompt = build_vision_prompt()
    assert "NO_TOC" in prompt
    assert "页码" in prompt or "page" in prompt.lower()


def test_parse_vision_response_complete():
    from addbookmark.ai_vision_toc import parse_vision_response
    response = "第一章\t1\n第二章\t15\n第三章\t30\nTOC_COMPLETE"
    entries, status, next_range = parse_vision_response(response)
    assert len(entries) == 3
    assert status == "TOC_COMPLETE"
    assert next_range is None


def test_parse_vision_response_continues():
    from addbookmark.ai_vision_toc import parse_vision_response
    response = "第一章\t1\n第二章\t15\nTOC_CONTINUES: 6-10"
    entries, status, next_range = parse_vision_response(response)
    assert len(entries) == 2
    assert status == "TOC_CONTINUES"
    assert next_range == (6, 10)


def test_parse_vision_response_no_toc():
    from addbookmark.ai_vision_toc import parse_vision_response
    entries, status, _ = parse_vision_response("NO_TOC")
    assert entries == []
    assert status == "NO_TOC"


def test_parse_vision_response_dot_leaders():
    from addbookmark.ai_vision_toc import parse_vision_response
    response = "- 第一章 概论 ..... 1\n- 第二章 ..... 15\nTOC_COMPLETE"
    entries, status, _ = parse_vision_response(response)
    assert len(entries) == 2
    assert entries[0] == ("第一章 概论", 1)


def test_extract_toc_images_page_range():
    from addbookmark.ai_vision_toc import extract_toc_images
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not installed")

    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        doc = fitz.open()
        for i in range(10):
            doc.new_page().insert_text((72, 72), f"Page {i}")
        doc.save(pdf_path)
        doc.close()

        images = extract_toc_images(pdf_path, page_start=2, page_end=4)
        assert len(images) == 3
    finally:
        os.unlink(pdf_path)


def test_extract_toc_from_vision_no_config():
    from addbookmark.ai_vision_toc import extract_toc_from_vision
    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        try:
            import fitz
        except ImportError:
            pytest.skip("PyMuPDF not installed")
        doc = fitz.open()
        doc.new_page()
        doc.save(pdf_path)
        doc.close()

        result = asyncio.run(
            extract_toc_from_vision(pdf_path, config={})
        )
        assert result == ""
    finally:
        os.unlink(pdf_path)


def test_cross_validate_entries():
    from addbookmark.ai_vision_toc import _cross_validate_entries
    ocr_text = "第一章 概论的内容很多。\n第二章 基础理论很重要。"
    vision_entries = [
        ("第一章 概论", 1),
        ("第二章 基础理论", 15),
        ("第九章 幻觉内容", 99),
    ]
    validated = _cross_validate_entries(vision_entries, ocr_text)
    assert len(validated) == 2
    assert validated[0] == ("第一章 概论", 1)


def test_generate_toc_uses_ocr_text_when_available():
    from addbookmark.ai_vision_toc import generate_toc
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
        for _ in range(40):
            doc.new_page()
        _insert_cn(doc[0], 72, 72, "书名")
        _insert_cn(doc[1], 72, 72, "目 录")
        _insert_cn(doc[1], 72, 100, "第一章 概论 ..... 1")
        _insert_cn(doc[1], 72, 120, "第二章 基础 ..... 15")
        _insert_cn(doc[1], 72, 140, "第三章 实验 ..... 30")
        doc.save(pdf_path)
        doc.close()

        result, source = asyncio.run(
            generate_toc(pdf_path, config={})
        )
        assert result
        assert source == "ocr_text"
    finally:
        os.unlink(pdf_path)


def test_extract_toc_from_ocr_text_success():
    """Should return (bookmark, start, end) for valid TOC."""
    from addbookmark.ai_vision_toc import extract_toc_from_ocr_text
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
        # Create enough pages so TOC page numbers pass validate_entries range check
        for _ in range(40):
            doc.new_page()

        # Page 0: cover
        _insert_cn(doc[0], 72, 72, "书名")

        # Page 1: TOC
        _insert_cn(doc[1], 72, 72, "目 录")
        _insert_cn(doc[1], 72, 100, "第一章 概论 ..... 1")
        _insert_cn(doc[1], 72, 120, "第二章 基础 ..... 15")
        _insert_cn(doc[1], 72, 140, "第三章 实验 ..... 30")

        doc.save(pdf_path)
        doc.close()

        bookmark, start, end = extract_toc_from_ocr_text(pdf_path)
        assert bookmark
        assert start == 1
    finally:
        os.unlink(pdf_path)


def test_extract_toc_from_ocr_text_no_toc():
    from addbookmark.ai_vision_toc import extract_toc_from_ocr_text
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF not installed")

    fd, pdf_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        doc = fitz.open()
        for i in range(3):
            doc.new_page().insert_text((72, 72), f"Body text page {i+1}.")
        doc.save(pdf_path)
        doc.close()

        bookmark, start, end = extract_toc_from_ocr_text(pdf_path)
        assert bookmark == ""
        assert start == -1
    finally:
        os.unlink(pdf_path)


def test_extract_toc_from_ocr_text_returns_page_range_on_quality_fail():
    """Even when validation fails, page range should be returned for Phase 2."""
    from addbookmark.ai_vision_toc import extract_toc_from_ocr_text
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
        p = doc.new_page()
        p.insert_font(fontname="SimHei", fontfile=SIMHEI_PATH)
        p.insert_text((72, 72), "目 录", fontname="SimHei", fontsize=11)
        p.insert_text((72, 100), "第一章 ..... 1", fontname="SimHei", fontsize=11)  # only 1 entry < min_entries=3
        doc.save(pdf_path)
        doc.close()

        bookmark, start, end = extract_toc_from_ocr_text(pdf_path)
        assert bookmark == ""  # validation fails
        assert start >= 0  # but page detection succeeded
    finally:
        os.unlink(pdf_path)


def test_extract_toc_from_text_dot_leaders():
    """Parse 'title ..... page' format."""
    from addbookmark.ai_vision_toc import extract_toc_from_text
    text = "第一章 概论 ..... 1\n第二章 基础理论 ..... 15\n  2.1 背景 ..... 15\n  2.2 方法论 ..... 22\n第三章 实验 ..... 30"
    entries = extract_toc_from_text(text)
    assert len(entries) == 5
    assert entries[0] == ("第一章 概论", 1)
    assert entries[4] == ("第三章 实验", 30)


def test_extract_toc_from_text_tab_format():
    from addbookmark.ai_vision_toc import extract_toc_from_text
    text = "第一章\t1\n第二章\t15\n第三章\t30"
    entries = extract_toc_from_text(text)
    assert len(entries) == 3


def test_extract_toc_from_text_no_toc():
    from addbookmark.ai_vision_toc import extract_toc_from_text
    assert extract_toc_from_text("") == []
    assert extract_toc_from_text("正文内容不是目录") == []


def test_validate_entries_accepts_good_toc():
    from addbookmark.ai_vision_toc import validate_entries
    entries = [("第一章", 1), ("第二章", 15), ("第三章", 30)]
    assert validate_entries(entries, total_pages=200) is True


def test_validate_entries_rejects_too_few():
    from addbookmark.ai_vision_toc import validate_entries
    assert validate_entries([("第一章", 1)], total_pages=200) is False
    assert validate_entries([], total_pages=200) is False


def test_validate_entries_rejects_bad_page_numbers():
    from addbookmark.ai_vision_toc import validate_entries
    entries = [("第一章", 1), ("第二章", 9999), ("第三章", 99999)]
    assert validate_entries(entries, total_pages=100) is False


def test_validate_entries_rejects_non_monotonic():
    from addbookmark.ai_vision_toc import validate_entries
    entries = [("a", 100), ("b", 1), ("c", 200), ("d", 2), ("e", 150), ("f", 3)]
    assert validate_entries(entries, total_pages=200) is False


def test_validate_entries_accepts_slight_non_monotonic():
    from addbookmark.ai_vision_toc import validate_entries
    entries = [
        ("第一章", 1), ("第二章", 15), ("2.1", 15), ("2.2", 22),
        ("第三章", 30), ("附录", 1),
    ]
    assert validate_entries(entries, total_pages=200) is True


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
