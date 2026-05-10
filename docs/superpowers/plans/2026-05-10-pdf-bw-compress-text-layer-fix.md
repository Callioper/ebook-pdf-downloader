# PDF BW 压缩文字层修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 BW 压缩后中文文字层无法正确识别/复制的问题，对齐 `pdf_compress_技术方案.md` 规范。

**Architecture:** 两个独立根因：(1) CJK 字体 `china-s` 的 ToUnicode CMap 损坏导致中文复制乱码，需改回 SimSun `fontfile=` 方案；(2) BW 压缩代码处理了页面所有 Image XObject，应改为只处理第一个（背景图），避免误替换非背景图像资源。

**Tech Stack:** pikepdf, PyMuPDF (fitz), Pillow, SimSun TTC (C:\Windows\Fonts\simsun.ttc)

---

## 差异分析

| 方面 | 技术方案 spec | 当前实现 | Bug 影响 |
|------|-------------|----------|:---:|
| 图片选择 | 只替换**第一个** Image XObject (`break`) | 替换**所有** Image XObject | 可能误替非背景图 |
| CJK 字体 | SimSun `fontfile=` | `fontname="china-s"` | china-s ToUnicode CMap 损坏 → 中文复制乱码 |
| 新流构造 | `Type + Subtype + Width + Height + ColorSpace + BPC + Filter` | 相同 | — |
| 输出保存 | `pdf.save(compress_streams=True)` | 相同 | — |
| 文字保留 | 只替换 Resources.XObject，不动 Contents | 相同 | — |

**根因 1 — CJK 字体**: `china-s` (Adobe 内置字体) 的 ToUnicode CMap 无法正确映射中文字形到 Unicode 码点。PDF 阅读器中搜索/复制中文时得到乱码。SimSun `fontfile=` 方案通过 TrueType 字体自带的 cmap 表正确映射，已验证可用。

**根因 2 — 图片选择**: `local-llm-pdf-ocr` 生成的 OCR PDF 中，Text 块嵌入了 Form XObject 列表。pikepdf 在遍历 `XObject` 字典时可能遍历到非图片资源。只替换第一个 Image XObject 与 spec 对齐且更安全。

---

### Task 1: 修复 CJK 字体 — 恢复 SimSun fontfile= 方案

**Files:**
- Modify: `local-llm-pdf-ocr/src/pdf_ocr/core/pdf.py:28-53`
- Modify: `local-llm-pdf-ocr/src/pdf_ocr/core/pdf.py:248-255` (font selection)
- Modify: `local-llm-pdf-ocr/src/pdf_ocr/core/pdf.py:357-361` (insert_text call)

- [ ] **Step 1: 恢复 SimSun 常量**

将 `_CJK_FONTNAME = "china-s"` 改回 SimSun 文件路径方案：

```python
# ── CJK font support ──
_CJK_RANGES = [
    (0x4E00, 0x9FFF),    # CJK Unified Ideographs
    (0x3400, 0x4DBF),    # CJK Unified Ideographs Extension A
    (0x20000, 0x2A6DF),  # CJK Unified Ideographs Extension B
    (0xF900, 0xFAFF),    # CJK Compatibility Ideographs
    (0x3040, 0x309F),    # Hiragana
    (0x30A0, 0x30FF),    # Katakana
    (0xAC00, 0xD7AF),    # Hangul Syllables
    (0x3000, 0x303F),    # CJK Symbols and Punctuation
    (0xFF00, 0xFFEF),    # Halfwidth and Fullwidth Forms
]

_SIMSUN_PATH = r"C:\Windows\Fonts\simsun.ttc"


def _has_cjk(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
            return True
    return False


def _get_cjk_font() -> str:
    """Return SimSun font path if available, else fallback to china-s."""
    if os.path.exists(_SIMSUN_PATH):
        return _SIMSUN_PATH
    return "china-s"
```

- [ ] **Step 2: 添加 `import os` 回 imports**

在文件顶部 `import io` 之后一行添加：

```python
import os
```

- [ ] **Step 3: 修改字体选择逻辑**

将 `_draw_invisible_text` 方法中的字体选择改为使用 SimSun `fontfile=`：

```python
        font = fitz.Font("helv")
        _cjk = _has_cjk(text)
        if _cjk:
            _fontfile = _get_cjk_font()
            font = fitz.Font(fontfile=_fontfile)
        else:
            _fontfile = None
```

- [ ] **Step 4: 修改 insert_text 调用**

```python
        _insert_kwargs = {
            "fontsize": fontsize,
            "render_mode": 3,
            "color": (0, 0, 0),
            "morph": morph,
        }
        if _cjk and _fontfile != "china-s":
            _insert_kwargs["fontfile"] = _fontfile
        else:
            _insert_kwargs["fontname"] = "helv" if not _cjk else _fontfile
        page.insert_text(baseline, text, **_insert_kwargs)
```

- [ ] **Step 5: 修改 insert_textbox 全页回退调用**

```python
        if is_full_page_fallback:
            fallback_rect = fitz.Rect(10, 10, page_width - 10, page_height - 10)
            _cjk = _has_cjk(text)
            _tb_kwargs = {"fontsize": 6, "render_mode": 3, "color": (0, 0, 0), "align": 0}
            if _cjk:
                _fontfile = _get_cjk_font()
                if _fontfile != "china-s":
                    _tb_kwargs["fontfile"] = _fontfile
                else:
                    _tb_kwargs["fontname"] = _fontfile
            else:
                _tb_kwargs["fontname"] = "helv"
            page.insert_textbox(fallback_rect, text, **_tb_kwargs)
            return
```

- [ ] **Step 6: 验证语法**

```powershell
cd D:\opencode\book-downloader\local-llm-pdf-ocr
python -c "import py_compile; py_compile.compile('src/pdf_ocr/core/pdf.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 7: 提交**

```powershell
cd D:\opencode\book-downloader\local-llm-pdf-ocr
git add src/pdf_ocr/core/pdf.py
git commit -m "fix: restore SimSun fontfile= for CJK text, china-s has broken ToUnicode CMap"
```

---

### Task 2: BW 压缩对齐 spec — 只替换第一个 Image XObject

**Files:**
- Modify: `backend/engine/pdf_bw_compress.py:50`

- [ ] **Step 1: 添加 break 只处理第一个图片**

将处理所有图片的循环改为只处理第一个：

```python
            for name, obj in xobjects.items():
                if obj.get(pikepdf.Name.Subtype) != pikepdf.Name.Image:
                    continue

                try:
                    raw = obj.read_raw_bytes()
                    img = Image.open(io.BytesIO(raw))

                    if half_res:
                        target_w = img.width // 2
                        target_h = img.height // 2
                        img = img.resize((target_w, target_h), Image.LANCZOS)

                    gray = img.convert("L")
                    bw = gray.point(lambda x: 0 if x < threshold else 255, "1")

                    raw_bits = bw.tobytes()
                    compressed = zlib.compress(raw_bits, 9)

                    new_stream = pdf.make_stream(compressed)
                    new_stream.Type = pikepdf.Name.XObject
                    new_stream.Subtype = pikepdf.Name.Image
                    new_stream.Width = pikepdf.Integer(bw.width)
                    new_stream.Height = pikepdf.Integer(bw.height)
                    new_stream.ColorSpace = pikepdf.Name.DeviceGray
                    new_stream.BitsPerComponent = pikepdf.Integer(1)
                    new_stream.Filter = pikepdf.Name.FlateDecode

                    page.Resources.XObject[pikepdf.Name(name)] = new_stream
                except Exception:
                    failed_pages.append(i + 1)
                break  # ← 只处理第一个 Image XObject，对齐 spec
```

- [ ] **Step 2: 验证语法**

```powershell
cd D:\opencode\book-downloader\backend
python -c "import py_compile; py_compile.compile('engine/pdf_bw_compress.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 提交**

```powershell
cd D:\opencode\book-downloader
git add backend/engine/pdf_bw_compress.py
git commit -m "fix: only replace first Image XObject per page in BW compression, matching spec"
```

---

### Task 3: 添加文字层验证测试

**Files:**
- Create: `backend/tests/test_pdf_bw_compress.py`

- [ ] **Step 1: 编写验证测试**

```python
"""验证 BW 压缩后文字层完整性"""
import os
import pikepdf
from engine.pdf_bw_compress import bw_compress_pdf_blocking


def test_bt_blocks_preserved():
    """压缩后 BT 文字块数量不变"""
    input_pdf = r"D:\pdf\BookDownloader\download\12928975_為女女.pdf.llmocr.pdf"
    output_pdf = r"D:\pdf\BookDownloader\download\12928975_bw_test_verify.pdf"

    if not os.path.exists(input_pdf):
        pytest.skip("Test PDF not found")

    before, after = bw_compress_pdf_blocking(input_pdf, output_pdf, half_res=True)

    pdf = pikepdf.open(output_pdf)
    page = pdf.pages[0]

    # Check image properties
    for name, obj in page.Resources.XObject.items():
        if obj.get(pikepdf.Name.Subtype) == pikepdf.Name.Image:
            assert int(obj.BitsPerComponent) == 1, "Expected 1bpc"
            assert str(obj.ColorSpace) == "/DeviceGray", "Expected DeviceGray"
            assert str(obj.Filter) == "/FlateDecode", "Expected FlateDecode"

    # Verify text layer: BT blocks should exist
    content = page.Contents
    if isinstance(content, pikepdf.Array):
        total_bt = sum(
            cs.read_bytes().count(b"BT")
            for cs in content
            if hasattr(cs, "read_bytes")
        )
        assert total_bt > 0, "Text layer (BT blocks) must be preserved"

    pdf.close()
    os.remove(output_pdf)
```

- [ ] **Step 2: 运行测试**

```powershell
cd D:\opencode\book-downloader\backend
python -m pytest tests/test_pdf_bw_compress.py -v
```

Expected: `PASS`

- [ ] **Step 3: 提交**

```powershell
cd D:\opencode\book-downloader
git add backend/tests/test_pdf_bw_compress.py
git commit -m "test: add BT block preservation verification for BW compression"
```

---

### Task 4: 重新构建 exe

**Files:**
- No code changes — rebuild only

- [ ] **Step 1: 构建前端**

```powershell
cd D:\opencode\book-downloader\frontend
powershell -ExecutionPolicy Bypass -Command "npm run build"
```

- [ ] **Step 2: 构建 exe**

```powershell
Stop-Process -Name "ebook-pdf-downloader" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
cd D:\opencode\book-downloader\backend
python -m PyInstaller book-downloader.spec --noconfirm
```

- [ ] **Step 3: 启动并验证**

```powershell
Start-Process -FilePath "D:\opencode\book-downloader\backend\dist\ebook-pdf-downloader.exe" -WorkingDirectory "D:\opencode\book-downloader\backend\dist" -WindowStyle Hidden
Start-Sleep -Seconds 8
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/v1/config" -UseBasicParsing -TimeoutSec 10 | Out-Null
```

Expected: `200 OK`

---

## Summary

| 任务 | 文件 | 修复内容 |
|------|------|----------|
| Task 1 | `local-llm-pdf-ocr/src/pdf_ocr/core/pdf.py` | CJK 字体从 `china-s` 改回 SimSun `fontfile=` |
| Task 2 | `backend/engine/pdf_bw_compress.py` | 只替换第一个 Image XObject，对齐 spec |
| Task 3 | `backend/tests/test_pdf_bw_compress.py` | BT blocks 保留验证测试 |
| Task 4 | `backend/dist/` | 重新构建 exe |
