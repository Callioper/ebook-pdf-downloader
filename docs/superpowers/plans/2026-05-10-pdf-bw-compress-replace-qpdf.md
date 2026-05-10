# PDF 黑白二值化压缩 — 替换 qpdf 方案

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 pikepdf + Pillow 黑白二值化方案替换现有 qpdf 纯结构压缩，将 OCR PDF 中的彩色/灰度 JPEG 图片转为 1-bit 黑白 + FlateDecode，同时完整保留 OCR 文字层。

**Architecture:** 在 `pipeline.py` 的 OCR 步骤完成后（原 qpdf 位置），以内联 Python 代码遍历 PDF 每一页，找到第一个 Image XObject，解码图片→灰度→二值化→FlateDecode 压缩→替换回 XObject（只换 Resources.XObject，不动 Contents → 文字层保留）。新增 `pdf_compress_half` 配置项控制全/半分辨率。

**Tech Stack:** pikepdf, Pillow (已安装), zlib (标准库)

---

### Task 1: 安装 pikepdf 依赖

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/book-downloader.spec`

- [ ] **Step 1: 添加 pikepdf 到 requirements.txt**

在 `backend/requirements.txt` 末尾追加一行:

```
pikepdf==10.5.1
```

- [ ] **Step 2: 安装 pikepdf**

```powershell
cd D:\opencode\book-downloader\backend; & "C:\Users\Administrator\.local\bin\uv.exe" pip install pikepdf==10.5.1
```

Expected: `Successfully installed pikepdf-10.5.1`

- [ ] **Step 3: 验证导入正常**

```powershell
cd D:\opencode\book-downloader\backend; & "C:\Users\Administrator\.local\bin\uv.exe" run python -c "import pikepdf; print(pikepdf.__version__); from PIL import Image; print('OK')"
```

Expected: `10.5.1` 然后 `OK`

- [ ] **Step 4: 添加 pikepdf 到 PyInstaller hiddenimports**

在 `backend/book-downloader.spec` 的 `hiddenimports` 列表末尾追加 `'pikepdf'`:

```python
    hiddenimports=[
        ...
        'httpx', 'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont',
        'pikepdf',          # ← 新增
    ],
```

- [ ] **Step 5: 提交**

```powershell
cd D:\opencode\book-downloader; git add backend/requirements.txt backend/book-downloader.spec; git commit -m "deps: add pikepdf 10.5.1 for PDF BW compression"
```

---

### Task 2: 添加 pdf_compress_half 配置键

**Files:**
- Modify: `backend/config.py` (DEFAULT_CONFIG dict)
- Modify: `config.default.json`
- Modify: `frontend/src/components/ConfigSettings.tsx` (DEFAULT_CONFIG + AppConfig interface)

- [ ] **Step 1: 添加后端默认配置**

在 `D:\opencode\book-downloader\backend\config.py:77-78` 的 `DEFAULT_CONFIG` 字典中，`"pdf_compress": False` 后面添加:

```python
    "pdf_compress": False,
    "pdf_compress_half": True,
```

- [ ] **Step 2: 添加前端默认配置 JSON**

在 `D:\opencode\book-downloader\config.default.json:24` 的 `"pdf_compress": false` 后面，添加:

```json
    "pdf_compress": false,
    "pdf_compress_half": true,
```

- [ ] **Step 3: 添加 TypeScript 接口字段**

在 `D:\opencode\book-downloader\frontend\src\components\ConfigSettings.tsx` 的 `AppConfig` 接口中，`[key: string]: unknown` 之前添加:

```typescript
  pdf_compress_half: boolean
```

- [ ] **Step 4: 添加前端 DEFAULT_CONFIG 字段**

在同一文件的 `DEFAULT_CONFIG` 对象中，找到 `bookmark_confirm_enabled: false` (line 169) 之后添加:

```typescript
  pdf_compress: false,
  pdf_compress_half: true,
```

- [ ] **Step 5: 验证后端配置加载**

```powershell
cd D:\opencode\book-downloader\backend; & "C:\Users\Administrator\.local\bin\uv.exe" run python -c "from config import DEFAULT_CONFIG; assert 'pdf_compress_half' in DEFAULT_CONFIG; print(DEFAULT_CONFIG['pdf_compress_half'])"
```

Expected: `True`

- [ ] **Step 6: 提交**

```powershell
cd D:\opencode\book-downloader; git add backend/config.py config.default.json frontend/src/components/ConfigSettings.tsx; git commit -m "feat: add pdf_compress_half config key for BW compression resolution control"
```

---

### Task 3: 实现 BW 压缩工具函数

**Files:**
- Create: `backend/engine/pdf_bw_compress.py`

- [ ] **Step 1: 编写 BW 压缩模块**

新建 `D:\opencode\book-downloader\backend\engine\pdf_bw_compress.py`:

```python
# -*- coding: utf-8 -*-
"""PDF 黑白二值化压缩工具 —— 将扫描版 PDF 图片转为 1-bit BW + FlateDecode"""

import io
import os
import zlib

import pikepdf
from PIL import Image


def bw_compress_pdf(
    input_path: str,
    output_path: str,
    half_res: bool = False,
    threshold: int = 128,
) -> tuple[int, int]:
    """
    将 PDF 内嵌图片转为 1-bit 黑白并用 FlateDecode 重新压缩。

    Args:
        input_path:  输入 PDF 路径
        output_path: 输出 PDF 路径
        half_res:    True=半分辨率(~150DPI), False=全分辨率(~300DPI)
        threshold:   二值化阈值 (0-255)，默认 128

    Returns:
        (原始大小字节数, 压缩后大小字节数)
    """
    pdf = pikepdf.open(input_path)
    total = len(pdf.pages)

    for i, page in enumerate(pdf.pages):
        xobjects = page.Resources.get(
            pikepdf.Name.XObject, pikepdf.Dictionary()
        )
        img_name = None
        img_obj = None
        for name, obj in xobjects.items():
            if obj.get(pikepdf.Name.Subtype) == pikepdf.Name.Image:
                img_name = str(name)
                img_obj = obj
                break

        if img_obj is None:
            continue

        raw = img_obj.read_raw_bytes()
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

        page.Resources.XObject[pikepdf.Name(img_name)] = new_stream

        if (i + 1) % 20 == 0:
            yield i + 1, total

    pdf.save(output_path, compress_streams=True)
    pdf.close()

    before = os.path.getsize(input_path)
    after = os.path.getsize(output_path)

    yield total, total
    yield before, after


def bw_compress_pdf_blocking(
    input_path: str,
    output_path: str,
    half_res: bool = False,
    threshold: int = 128,
    progress_callback=None,
) -> tuple[int, int]:
    """
    同步版本，通过 progress_callback(page, total) 报告进度。

    Returns:
        (before_bytes, after_bytes)
    """
    pdf = pikepdf.open(input_path)
    total = len(pdf.pages)

    for i, page in enumerate(pdf.pages):
        xobjects = page.Resources.get(
            pikepdf.Name.XObject, pikepdf.Dictionary()
        )
        img_name = None
        img_obj = None
        for name, obj in xobjects.items():
            if obj.get(pikepdf.Name.Subtype) == pikepdf.Name.Image:
                img_name = str(name)
                img_obj = obj
                break

        if img_obj is None:
            continue

        raw = img_obj.read_raw_bytes()
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

        page.Resources.XObject[pikepdf.Name(img_name)] = new_stream

        if (i + 1) % 20 == 0 and progress_callback:
            progress_callback(i + 1, total)

    pdf.save(output_path, compress_streams=True)
    pdf.close()

    before = os.path.getsize(input_path)
    after = os.path.getsize(output_path)

    if progress_callback:
        progress_callback(total, total)

    return before, after
```

- [ ] **Step 2: 验证模块能导入**

```powershell
cd D:\opencode\book-downloader\backend; & "C:\Users\Administrator\.local\bin\uv.exe" run python -c "from engine.pdf_bw_compress import bw_compress_pdf_blocking; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 提交**

```powershell
cd D:\opencode\book-downloader; git add backend/engine/pdf_bw_compress.py; git commit -m "feat: add pdf_bw_compress module (pikepdf + Pillow BW compression)"
```

---

### Task 4: 替换 pipeline.py 中的 qpdf 压缩块

**Files:**
- Modify: `backend/engine/pipeline.py` (lines 2454-2489)

- [ ] **Step 1: 添加 import**

在 `D:\opencode\book-downloader\backend\engine\pipeline.py` 的 import 区域（第 10 行 `import os` 之后）添加:

```python
from engine.pdf_bw_compress import bw_compress_pdf_blocking
```

- [ ] **Step 2: 替换整个 qpdf 压缩块**

在 `pipeline.py:2454-2489`，将现有的 qpdf 压缩代码块替换为:

```python
    # PDF compression (pikepdf BW, replaces qpdf structural compression)
    if report.get("ocr_done") and config.get("pdf_compress", False):
        if report.get("pdf_path") and os.path.exists(report["pdf_path"]):
            task_store.add_log(task_id, "Compressing PDF (BW binarization)...")
            try:
                half_res = config.get("pdf_compress_half", True)
                output_path = report["pdf_path"] + ".bw"
                before, after = bw_compress_pdf_blocking(
                    input_path=report["pdf_path"],
                    output_path=output_path,
                    half_res=half_res,
                    threshold=128,
                )
                os.replace(output_path, report["pdf_path"])
                saved_pct = round((1 - after / before) * 100, 1)
                task_store.add_log(
                    task_id,
                    f"BW compression: {before/1024/1024:.1f}MB → {after/1024/1024:.1f}MB "
                    f"({saved_pct}% saved, {'half' if half_res else 'full'} resolution)",
                )
            except Exception as e:
                task_store.add_log(task_id, f"BW compression failed: {str(e)[:200]}")
                try:
                    os.remove(report["pdf_path"] + ".bw")
                except Exception:
                    pass
```

- [ ] **Step 3: 替换 ocrmypdf 阶段的日志措辞**

在 `pipeline.py:2097-2105`，将现有的 GhostScript 日志改为不提及 qpdf（因为压缩现在用 pikepdf，GhostScript optimize 只是 ocrmypdf 内部的优化）:

```python
    if config.get("pdf_compress", False):
        import shutil as _opt_sh
        if _opt_sh.which("gswin64c") or _opt_sh.which("gs"):
            _opt_level = "1"
            task_store.add_log(task_id, "PDF optimization enabled (GhostScript found for ocrmypdf --optimize)")
        else:
            task_store.add_log(task_id, "PDF optimization requested but GhostScript not found; ocrmypdf will skip --optimize")
    else:
        task_store.add_log(task_id, "PDF optimization disabled")
```

- [ ] **Step 4: 验证语法**

```powershell
cd D:\opencode\book-downloader\backend; & "C:\Users\Administrator\.local\bin\uv.exe" run python -c "import py_compile; py_compile.compile('engine/pipeline.py', doraise=True); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 5: 验证模块导入链路**

```powershell
cd D:\opencode\book-downloader\backend; & "C:\Users\Administrator\.local\bin\uv.exe" run python -c "from engine.pipeline import run_pipeline; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: 提交**

```powershell
cd D:\opencode\book-downloader; git add backend/engine/pipeline.py; git commit -m "feat: replace qpdf with pikepdf BW compression in OCR pipeline step"
```

---

### Task 5: 更新前端 OCR 设置 UI

**Files:**
- Modify: `frontend/src/components/ConfigSettings.tsx` (lines 1387-1399)

- [ ] **Step 1: 替换 PDF 压缩区域的 JSX**

在 `ConfigSettings.tsx:1387-1399`，将当前代码:

```tsx
                  {/* PDF 压缩 */}
                  <div className="border-t border-gray-200 pt-2 mt-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={!!form.pdf_compress}
                        onChange={(e) => setForm((prev) => ({ ...prev, pdf_compress: e.target.checked }))}
                        className="rounded border-gray-300"
                      />
                      <span className="text-xs font-medium text-gray-600">PDF 压缩（OCR 后执行 qpdf 结构压缩）</span>
                    </label>
                    <p className="text-xs text-gray-400 mt-0.5 ml-5">使用 qpdf 纯结构压缩，零文字层损失。</p>
                  </div>
```

替换为:

```tsx
                  {/* PDF 压缩 */}
                  <div className="border-t border-gray-200 pt-2 mt-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={!!form.pdf_compress}
                        onChange={(e) => setForm((prev) => ({ ...prev, pdf_compress: e.target.checked }))}
                        className="rounded border-gray-300"
                      />
                      <span className="text-xs font-medium text-gray-600">PDF 黑白二值化压缩（OCR 后执行）</span>
                    </label>
                    <p className="text-xs text-gray-400 mt-0.5 ml-5">将彩色扫描页转为 1-bit 黑白，大幅减小体积，完整保留 OCR 文字层。</p>
                    {form.pdf_compress && (
                      <div className="mt-2 ml-5 flex items-center gap-3">
                        <span className="text-xs text-gray-500">分辨率:</span>
                        <label className="flex items-center gap-1 cursor-pointer">
                          <input
                            type="radio"
                            name="pdf_compress_half"
                            checked={!form.pdf_compress_half}
                            onChange={() => setForm((prev) => ({ ...prev, pdf_compress_half: false }))}
                            className="border-gray-300"
                          />
                          <span className="text-xs text-gray-600">全分辨率 (~300 DPI)</span>
                        </label>
                        <label className="flex items-center gap-1 cursor-pointer">
                          <input
                            type="radio"
                            name="pdf_compress_half"
                            checked={!!form.pdf_compress_half}
                            onChange={() => setForm((prev) => ({ ...prev, pdf_compress_half: true }))}
                            className="border-gray-300"
                          />
                          <span className="text-xs text-gray-600">半分辨率 (~150 DPI, 体积更小)</span>
                        </label>
                      </div>
                    )}
                  </div>
```

- [ ] **Step 2: 验证 TypeScript 编译**

```powershell
cd D:\opencode\book-downloader\frontend; npx tsc --noEmit --pretty 2>&1 | Select-Object -First 20
```

Expected: 无新增类型错误（现有错误忽略）。

- [ ] **Step 3: 提交**

```powershell
cd D:\opencode\book-downloader; git add frontend/src/components/ConfigSettings.tsx; git commit -m "feat: update PDF compress UI for BW binarization with resolution toggle"
```

---

### Task 6: 完整构建并端到端验证

**Files:**
- Modify: `backend/book-downloader.spec` (verify hiddenimports)
- No new files

- [ ] **Step 1: 构建前端**

```powershell
cd D:\opencode\book-downloader\frontend; npm run build
```

- [ ] **Step 2: 构建 exe**

```powershell
cd D:\opencode\book-downloader\backend; & "C:\Users\Administrator\.local\bin\uv.exe" run pyinstaller book-downloader.spec --noconfirm
```

- [ ] **Step 3: 启动 exe 并测试**

```powershell
Start-Process -FilePath "D:\opencode\book-downloader\backend\dist\ebook-pdf-downloader.exe"
```

打开浏览器访问 `http://127.0.0.1:8000`，进入设置 → OCR 面板，验证:
1. 勾选 "PDF 黑白二值化压缩" 复选框
2. 出现全分辨率/半分辨率单选按钮，默认选中半分辨率
3. 保存设置

- [ ] **Step 4: 用真实 PDF 测试压缩效果**

选取一个已有 OCR 文字层的扫描 PDF，用命令行直接测试：

```powershell
cd D:\opencode\book-downloader\backend; & "C:\Users\Administrator\.local\bin\uv.exe" run python -c "
from engine.pdf_bw_compress import bw_compress_pdf_blocking

before, after = bw_compress_pdf_blocking(
    'D:/pdf/BookDownloader/download/xxx_bw_test.pdf',
    'D:/pdf/BookDownloader/download/xxx_bw_test_out.pdf',
    half_res=True
)
print(f'{before/1024/1024:.1f}MB -> {after/1024/1024:.1f}MB ({(1-after/before)*100:.1f}% saved)')

import pikepdf
pdf = pikepdf.open('D:/pdf/BookDownloader/download/xxx_bw_test_out.pdf')
page = pdf.pages[0]
for name, obj in page.Resources.XObject.items():
    if obj.get(pikepdf.Name.Subtype) == pikepdf.Name.Image:
        print(f'Image: {obj.Width}x{obj.Height}, {obj.BitsPerComponent}bpc, ColorSpace={obj.ColorSpace}, Filter={obj.Filter}')

content = page.Contents
if isinstance(content, pikepdf.Array):
    total_bt = sum(cs.read_bytes().count(b'BT') for cs in content if hasattr(cs, 'read_bytes'))
    print(f'Content streams: {len(content)}, BT blocks: {total_bt}')
pdf.close()
"
```

Expected: 
- 大小显著减小 (70%+)
- `BitsPerComponent=1`, `Filter=FlateDecode`, `ColorSpace=DeviceGray`
- `BT blocks > 0` → 文字层保留

- [ ] **Step 5: 提交**

```powershell
cd D:\opencode\book-downloader; git add backend/book-downloader.spec; git commit -m "build: update pyinstaller spec with pikepdf hidden import"
```

---

## Summary of Changes

| 文件 | 操作 | 内容 |
|------|------|------|
| `backend/requirements.txt` | 修改 | 添加 `pikepdf==10.5.1` |
| `backend/book-downloader.spec` | 修改 | hiddenimports 添加 `pikepdf` |
| `backend/config.py` | 修改 | DEFAULT_CONFIG 添加 `pdf_compress_half: True` |
| `config.default.json` | 修改 | 添加 `"pdf_compress_half": true` |
| `backend/engine/pdf_bw_compress.py` | 新建 | BW 压缩工具模块 |
| `backend/engine/pipeline.py` | 修改 | 替换 qpdf 块为 pikepdf BW 压缩；更新日志措辞 |
| `frontend/src/components/ConfigSettings.tsx` | 修改 | 更新 OCR 面板压缩 UI + 分辨率开关 |

## Migration Notes

- **配置兼容**: `pdf_compress_half` 新字段有默认值 `true`，旧配置自动兼容
- **qpdf 不再需要**: 如果系统上安装了 qpdf，不再被调用；可选择性卸载
- **GhostScript**: 仍用于 ocrmypdf 的 `--optimize 1`，不受影响
- **文字层安全**: pikepdf 只替换 `Resources.XObject`，不修改 `Contents` 内容流
