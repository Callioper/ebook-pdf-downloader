# LLM OCR 接入 ocrmypdf 流程 (文字层与图片层对齐) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 LLM 视觉模型替换 ocrmypdf 的 OCR 引擎，使 LLM OCR 输出的文字层与原始页面图片精确对齐（利用 ocrmypdf 的 sandwich 渲染和图片预处理）。

**Architecture:** 编写 `ocrmypdf_llmocr` 插件实现 `OcrEngine.generate_pdf()` 接口（sandwich 路径），ocrmypdf 负责页面栅格化、预处理、PDF/A 转换，插件仅需：调用 LLM API → 估算文本行 Y 坐标 → 用 pikepdf 写不可见文字层 PDF → 交回 ocrmypdf 叠加。不再需要独立的 `llm_ocr.py` 中的 `insert_textbox`。

**Tech Stack:** ocrmypdf 插件系统 (pluggy hooks)、pikepdf (写 PDF 文字层)、httpx (调 LLM API)、PIL (读图片尺寸 DPI)

---

## 文件结构

| 文件 | 职责 | 变更 |
|------|------|------|
| `backend/engine/ocrmypdf_llmocr/__init__.py` | 插件入口：注册 hooks (`get_ocr_engine`, `add_options`, `check_options`) | **新建** |
| `backend/engine/ocrmypdf_llmocr/engine.py` | `LlmOcrEngine` 类：实现 `OcrEngine` 抽象接口（`version`, `generate_pdf`, `languages` 等） | **新建** |
| `backend/engine/ocrmypdf_llmocr/text_pdf.py` | `create_text_only_pdf()`：用 pikepdf 创建只含不可见文字层的单页 PDF，按 LLM 返回的行数和图片 DPI 均匀分布行位置 | **新建** |
| `backend/engine/llm_ocr.py` | 保留 `verify_llm_model`, `ocr_page` 函数（被插件复用），移除 `build_searchable_pdf`, `run_llm_ocr` | **修改** |
| `backend/engine/pipeline.py:1738-1789` | LLM OCR 分支改为：调用 ocrmypdf + `--plugin ocrmypdf_llmocr` + `--pdf-renderer sandwich`（与 EasyOCR 模式一致） | **修改** |
| `backend/api/search.py:766-779` | `check-ocr` 端点保持原有 LLM OCR 检测逻辑（使用 `verify_llm_model`） | 不变 |
| `backend/book-downloader.spec` | hiddenimports 加入 `engine.ocrmypdf_llmocr` | **修改** |
| `frontend/src/components/ConfigSettings.tsx` | LLM OCR 配置面板保持原有逻辑 | 不变 |

---

### Task 1: 创建 `ocrmypdf_llmocr` 插件骨架

**Files:**
- Create: `D:\opencode\book-downloader\backend\engine\ocrmypdf_llmocr\__init__.py`
- Create: `D:\opencode\book-downloader\backend\engine\ocrmypdf_llmocr\engine.py`

**Why:** ocrmypdf 通过 pluggy 插件系统发现引擎。`__init__.py` 注册 hooks，`engine.py` 实现 `OcrEngine` 抽象基类。

- [ ] **Step 1: 创建 `__init__.py`（插件入口 + hooks）**

```python
# backend/engine/ocrmypdf_llmocr/__init__.py
"""ocrmypdf plugin — LLM-based OCR engine via OpenAI-compatible vision API."""

import logging

log = logging.getLogger(__name__)

try:
    from ocrmypdf.hooks import hookimpl
except ImportError:
    from ocrmypdf.pluginspec import hookimpl


@hookimpl
def add_options(parser):
    group = parser.add_argument_group("LLM OCR", "LLM-based OCR options")
    group.add_argument(
        "--llm-ocr-endpoint",
        default="http://localhost:11434",
        help="LLM API endpoint (OpenAI-compatible, e.g. Ollama/LM Studio)",
    )
    group.add_argument(
        "--llm-ocr-model",
        default="",
        help="LLM model name (e.g. llava:13b, noctrex/paddleocr-vl-1.5)",
    )
    group.add_argument(
        "--llm-ocr-api-key",
        default="",
        help="API key (leave empty for local models)",
    )
    group.add_argument(
        "--llm-ocr-lang",
        default="chi_sim+eng",
        help="Language hint for OCR",
    )


@hookimpl
def check_options(options):
    if not getattr(options, 'llm_ocr_model', ''):
        log.warning("LLM OCR: no model configured (--llm-ocr-model)") 


@hookimpl
def get_ocr_engine(options):
    from .engine import LlmOcrEngine
    return LlmOcrEngine()


@hookimpl
def initialize(plugin_manager):
    pass
```

- [ ] **Step 2: 创建 `engine.py`（LlmOcrEngine 类的最小骨架）**

```python
# backend/engine/ocrmypdf_llmocr/engine.py
"""LLM OCR engine — ocrmypdf OcrEngine implementation."""

import logging
from pathlib import Path
from typing import Set

from ocrmypdf.pluginspec import OcrEngine

log = logging.getLogger(__name__)


class LlmOcrEngine(OcrEngine):

    @staticmethod
    def version() -> str:
        return "1.0.0"

    @staticmethod
    def creator_tag(options) -> str:
        return "LLM-OCR v1.0"

    def __str__(self) -> str:
        return "LLM OCR Engine"

    @staticmethod
    def languages(options) -> Set[str]:
        return {"chi_sim", "chi_tra", "eng", "jpn", "kor", "fra", "deu", "spa"}

    @staticmethod
    def get_orientation(input_file: Path, options) -> "OrientationConfidence":
        from ocrmypdf.pluginspec import OrientationConfidence
        return OrientationConfidence(angle=0, confidence=0.0)

    @staticmethod
    def get_deskew(input_file: Path, options) -> float:
        return 0.0

    @staticmethod
    def generate_hocr(input_file, output_hocr, output_text, options):
        raise NotImplementedError("LLM OCR does not support hOCR output")

    @staticmethod
    def generate_pdf(input_file, output_pdf, output_text, options):
        """
        Called by ocrmypdf for each page image.
        input_file: Path to page image (PNG)
        output_pdf: Path to write text-only PDF
        output_text: Path to write sidecar text file
        options: ocrmypdf OcrOptions (has custom llm_ocr_* attrs)
        """
        from .text_pdf import create_text_only_pdf
        # Will be expanded in Task 2
        raise NotImplementedError("text_pdf module not yet created")
```

- [ ] **Step 3: 验证插件被 ocrmypdf 发现**

```powershell
$env:PYTHONPATH = "D:\opencode\book-downloader\backend;D:\opencode\book-downloader\backend\engine"
& "C:\Python314\python.exe" -c "
import ocrmypdf.pluginspec as p
import engine.ocrmypdf_llmocr
pm = p.get_plugin_manager()
pm.register(engine.ocrmypdf_llmocr)
engines = pm.hook.get_ocr_engine()
print('Discovered engines:', [str(e) for e in engines if e])
"
```

Expected: "LLM OCR Engine" should appear in the list.

- [ ] **Step 4: Commit**

```bash
git add backend/engine/ocrmypdf_llmocr/
git commit -m "feat: add ocrmypdf_llmocr plugin skeleton (hooks + engine stub)"
```

---

### Task 2: 实现 `text_pdf.py` — 创建定位文字层 PDF

**Files:**
- Create: `D:\opencode\book-downloader\backend\engine\ocrmypdf_llmocr\text_pdf.py`
- Modify: `D:\opencode\book-downloader\backend\engine\ocrmypdf_llmocr\engine.py` (完成 `generate_pdf()`)

**Why:** 这是核心 — 将 LLM 返回的纯文本按估算的 Y 坐标写入 PDF 不可见文字层，利用 ocrmypdf sandwich 渲染叠加到原始页面图片上。

- [ ] **Step 1: 创建 `text_pdf.py`**

```python
# backend/engine/ocrmypdf_llmocr/text_pdf.py
"""Create a text-only PDF with invisible text layer positioned by estimated line heights."""

import logging
from pathlib import Path

import pikepdf
from PIL import Image

log = logging.getLogger(__name__)


def create_text_only_pdf(
    output_pdf: Path,
    page_text: str,
    image_path: Path,
) -> None:
    """
    Create a single-page PDF with invisible text at estimated positions.

    The text is placed in evenly-spaced lines from top to bottom.
    This PDF is later grafted onto the original page image by ocrmypdf's
    sandwich renderer, giving each text line approximate position matching.

    Args:
        output_pdf: Path to write the text-only PDF
        page_text: Recognized text (lines separated by newlines)
        image_path: Original page image (for dimensions and DPI)
    """
    if not page_text or not page_text.strip():
        # Empty page — produce a minimal empty PDF
        _write_empty_pdf(output_pdf)
        return

    lines = page_text.split('\n')
    lines = [l for l in lines if l.strip()]  # skip blank lines
    if not lines:
        _write_empty_pdf(output_pdf)
        return

    # Read image dimensions and DPI
    with Image.open(image_path) as img:
        img_width, img_height = img.size
        dpi_x = float(img.info.get('dpi', (72, 72))[0])
        dpi_y = float(img.info.get('dpi', (72, 72))[1])

    # Convert pixel dimensions to PDF points
    page_w_pt = img_width / dpi_x * 72.0
    page_h_pt = img_height / dpi_y * 72.0

    # Calculate line height
    margin_pt = page_h_pt * 0.05  # 5% top/bottom margin
    usable_h = page_h_pt - 2 * margin_pt
    line_h_pt = usable_h / max(len(lines), 1)

    # Create PDF with pikepdf
    pdf = pikepdf.Pdf.new()

    # One page, MediaBox matching image dimensions in points
    page = pdf.add_blank_page(page_size=(page_w_pt, page_h_pt))

    # Build content stream with invisible text
    content = pikepdf.Stream(pdf, b'')
    content.write(b'3 Tr\n')  # text render mode 3 = invisible
    content.write(b'BT\n')

    font_name = b'/F1'
    font_size = line_h_pt * 0.7  # font at 70% of line height
    content.write(
        f'{font_size:.2f} Tf\n'.encode('ascii')
    )

    for i, line_text in enumerate(lines):
        # Y position: PDF coordinates are bottom-left origin
        y_pt = page_h_pt - margin_pt - (i + 0.3) * line_h_pt
        x_pt = margin_pt * 0.5

        content.write(
            f'1 0 0 1 {x_pt:.2f} {y_pt:.2f} Tm\n'.encode('ascii')
        )

        # Escape PDF string special chars
        escaped = (
            line_text.replace('\\', '\\\\')
            .replace('(', '\\(')
            .replace(')', '\\)')
        )
        content.write(
            f'({escaped}) Tj\n'.encode('utf-8')
        )

    content.write(b'ET\n')

    # Add a simple font resource (use Courier — CJK fonts are handled by
    # the sandwich renderer which grafts the text layer onto the original image.
    # The actual glyphs may not render in Courier but the text is stored
    # as Unicode character codes which PDF readers can search/select.)
    page.contents_add(content, compress=True)
    resources = pikepdf.Dictionary({
        '/Font': pikepdf.Dictionary({
            '/F1': pikepdf.Dictionary({
                '/Type': '/Font',
                '/Subtype': '/Type1',
                '/BaseFont': '/Courier',
                '/Encoding': '/WinAnsiEncoding',
            }),
        }),
    })
    page.Resources = resources

    pdf.save(output_pdf)
    pdf.close()


def _write_empty_pdf(output_pdf: Path) -> None:
    """Write a minimal empty PDF for pages with no text."""
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    pdf.save(output_pdf)
    pdf.close()
```

- [ ] **Step 2: 完成 `engine.py` 的 `generate_pdf()` 实现**

修改 `D:\opencode\book-downloader\backend\engine\ocrmypdf_llmocr\engine.py` 中的 `generate_pdf()` 方法：

```python
    @staticmethod
    def generate_pdf(input_file, output_pdf, output_text, options):
        """Called by ocrmypdf for each page image."""
        import base64
        import asyncio

        from .text_pdf import create_text_only_pdf

        # Read image bytes
        img_bytes = open(input_file, 'rb').read()
        img_b64 = base64.b64encode(img_bytes).decode('utf-8')

        endpoint = getattr(options, 'llm_ocr_endpoint', 'http://localhost:11434')
        model = getattr(options, 'llm_ocr_model', '')
        api_key = getattr(options, 'llm_ocr_api_key', '')
        lang = getattr(options, 'llm_ocr_lang', 'chi_sim+eng')

        if not model:
            log.error("LLM OCR: no model configured, skipping page")
            output_text.write_text("", encoding='utf-8')
            _write_empty_pdf(output_pdf)
            return

        # Call LLM API synchronously (ocrmypdf runs per-page in worker processes)
        text = _call_llm_sync(endpoint, model, api_key, img_b64, lang)

        if text is None:
            text = ""

        output_text.write_text(text, encoding='utf-8')
        create_text_only_pdf(output_pdf, text, input_file)


def _call_llm_sync(endpoint: str, model: str, api_key: str, img_b64: str, lang: str) -> str | None:
    """Synchronous wrapper around the LLM API call. Called from worker processes."""
    import httpx
    import json

    lang_hint = "Chinese and English" if "chi_sim" in lang else "English"

    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                },
                {
                    "type": "text",
                    "text": (
                        f"Extract ALL text from this image. This is a scanned book page in {lang_hint}. "
                        "Preserve the original text layout, line breaks, and structure. "
                        "Do not add commentary. Output ONLY the extracted text."
                    ),
                },
            ],
        }],
        "max_tokens": 4096,
        "temperature": 0,
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = httpx.post(
            f"{endpoint.rstrip('/')}/v1/chat/completions",
            json=body,
            headers=headers,
            timeout=120,
        )
        if resp.status_code != 200:
            log.warning(f"LLM OCR page failed: HTTP {resp.status_code}")
            return None
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return None
        content = choices[0].get("message", {}).get("content", "")
        return content if content else None
    except Exception as e:
        log.warning(f"LLM OCR page error: {e}")
        return None


def _write_empty_pdf(output_pdf):
    """Minimal empty PDF for pages with no text."""
    import pikepdf
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    pdf.save(output_pdf)
    pdf.close()
```

- [ ] **Step 3: 验证插件端到端工作（3 页测试 PDF）**

```powershell
$env:PYTHONPATH = "D:\opencode\book-downloader\backend;D:\opencode\book-downloader\backend\engine"
& "C:\Python314\python.exe" -m ocrmypdf `
  --plugin ocrmypdf_llmocr `
  --llm-ocr-endpoint "http://127.0.0.1:12345" `
  --llm-ocr-model "noctrex/paddleocr-vl-1.5" `
  --llm-ocr-lang "chi_sim+eng" `
  --optimize 0 `
  --pdf-renderer sandwich `
  --output-type pdf `
  "C:\Users\Administrator\tmp\ocr_test\test_ocr.pdf" `
  "C:\Users\Administrator\tmp\ocr_test\test_llm_plugin_output.pdf"
```

Expected: 退出码 0，输出 PDF 含中文文字层。

- [ ] **Step 4: Commit**

```bash
git add backend/engine/ocrmypdf_llmocr/text_pdf.py backend/engine/ocrmypdf_llmocr/engine.py
git commit -m "feat: implement generate_pdf with LLM API call and text-layer PDF creation"
```

---

### Task 3: 将 LLM OCR 分支接入 ocrmypdf 流程（替换 pipeline.py 中的直接调用）

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pipeline.py:1738-1789`
- Modify: `D:\opencode\book-downloader\backend\engine\llm_ocr.py` (剪裁)

**Why:** 当前 `pipeline.py` 的 LLM OCR 分支直接调用 `run_llm_ocr()` 并用 `insert_textbox` 制作 PDF。改为：构建 ocrmypdf 命令 + `--plugin ocrmypdf_llmocr`，走 ocrmypdf sandwich 流程，文字层由插件自动对齐。

- [ ] **Step 1: 修改 pipeline.py 的 LLM OCR 分支**

找到 `elif ocr_engine == "llm_ocr":` 分支（约 1738-1789 行），完整替换为：

```python
        elif ocr_engine == "llm_ocr":
            task_store.add_log(task_id, "Running LLM-based OCR via ocrmypdf plugin...")

            if not _is_scanned(pdf_path, python_cmd=_py_for_ocr):
                task_store.add_log(task_id, "PDF already has text layer, skipping OCR")
                report["ocr_done"] = True
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            llm_endpoint = config.get("llm_ocr_endpoint", "http://localhost:11434")
            llm_model = config.get("llm_ocr_model", "")
            llm_api_key = config.get("llm_ocr_api_key", "")

            if not llm_endpoint or not llm_model:
                task_store.add_log(task_id, "LLM OCR: endpoint or model not configured")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            output_pdf = pdf_path.replace(".pdf", "_ocr.pdf")
            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 10})

            # Register the LLM OCR plugin module before calling ocrmypdf
            _llm_plugin_path = os.path.join(os.path.dirname(__file__), "ocrmypdf_llmocr")
            cmd = [
                _py_for_ocr, "-m", "ocrmypdf",
                "--plugin", "ocrmypdf_llmocr",
                "--llm-ocr-endpoint", llm_endpoint,
                "--llm-ocr-model", llm_model,
                "--llm-ocr-lang", ocr_lang or "chi_sim+eng",
                "--optimize", "0",
                "--oversample", ocr_oversample,
                "-j", "1",
                "--output-type", "pdf",
                "--pdf-renderer", "sandwich",
                pdf_path,
                output_pdf,
            ]
            if llm_api_key:
                cmd.insert(cmd.index("--llm-ocr-lang") + 2, "--llm-ocr-api-key")
                cmd.insert(cmd.index("--llm-ocr-api-key") + 1, llm_api_key)

            # Ensure PYTHONPATH includes our plugin directory
            _ocr_env = {**os.environ,
                        "PYTHONPATH": os.pathsep.join([
                            os.path.dirname(os.path.dirname(__file__)),  # backend/
                            os.path.dirname(__file__),  # backend/engine/
                        ] + os.environ.get("PYTHONPATH", "").split(os.pathsep)),
                        "PYTHONUNBUFFERED": "1"}

            try:
                _exit = await _run_ocrmypdf_with_progress(
                    task_id, cmd, env=_ocr_env,
                    timeout=ocr_timeout, total_pages=_total_pages,
                    output_pdf=output_pdf,
                )
                if _exit == 0:
                    os.replace(output_pdf, pdf_path)
                    task_store.add_log(task_id, "LLM OCR completed successfully")
                    report["ocr_done"] = True
                else:
                    task_store.add_log(task_id, f"LLM OCR failed with exit code {_exit}")
            except asyncio.TimeoutError:
                task_store.add_log(task_id, f"LLM OCR timed out after {ocr_timeout}s")
            except Exception as e:
                task_store.add_log(task_id, f"LLM OCR error: {e}")
```

- [ ] **Step 2: 裁剪 `llm_ocr.py` — 移除不再需要的函数**

`run_llm_ocr()` 和 `build_searchable_pdf()` 不再被 pipeline 调用（功能已由插件替代）。但保留 `verify_llm_model()` 和 `ocr_page()`（被 `check-ocr` API 端点和设置页使用）。

删除:
- `def build_searchable_pdf(...)` — 整个函数（约 169-203 行）
- `def run_llm_ocr(...)` — 整个函数（约 206-307 行）
- `def encode_image_to_base64(...)` — 移到插件的 engine.py 中（如已复制则删除）
- `def extract_page_images(...)` — 不再需要

保留:
- `verify_llm_model(...)` — 被 `check-ocr` 端点使用
- `ocr_page(...)` — 被 `verify_llm_model` 或前端诊断使用

- [ ] **Step 3: 验证 pipeline 集成端到端**

```powershell
& "C:\Python314\python.exe" -c "
import sys, os
sys.path.insert(0, r'D:\opencode\book-downloader\backend')
os.environ['PYTHONPATH'] = r'D:\opencode\book-downloader\backend;D:\opencode\book-downloader\backend\engine'
import subprocess
pdf = r'C:\Users\Administrator\tmp\ocr_test\test_ocr.pdf'
out = pdf.replace('.pdf', '_llm_via_ocrmypdf.pdf')
cmd = ['C:\\Python314\\python.exe', '-m', 'ocrmypdf',
    '--plugin', 'ocrmypdf_llmocr',
    '--llm-ocr-endpoint', 'http://127.0.0.1:12345',
    '--llm-ocr-model', 'noctrex/paddleocr-vl-1.5',
    '--llm-ocr-lang', 'chi_sim+eng',
    '--optimize', '0', '--oversample', '200', '-j', '1',
    '--output-type', 'pdf', '--pdf-renderer', 'sandwich',
    pdf, out]
r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env={**os.environ})
print(f'Exit: {r.returncode}')
if r.returncode != 0:
    print('STDERR:', r.stderr[-500:])
    print('STDOUT:', r.stdout[-500:])
else:
    import fitz
    d = fitz.open(out)
    print(f'Pages: {len(d)}')
    for i in range(len(d)):
        t = d[i].get_text().strip()[:100]
        print(f'  P{i+1}: {t}')
    d.close()
"
```

Expected: 退出码 0，输出 PDF 有文字层且对话层与图片位置大致对应。

- [ ] **Step 4: Commit**

```bash
git add backend/engine/pipeline.py backend/engine/llm_ocr.py
git commit -m "refactor: use ocrmypdf plugin for LLM OCR (replaces direct insert_textbox approach)"
```

---

### Task 4: 更新 PyInstaller spec 并重新编译

**Files:**
- Modify: `D:\opencode\book-downloader\backend\book-downloader.spec`

- [ ] **Step 1: 更新 hiddenimports**

在 hiddenimports 列表中添加插件模块：

```python
# 在 'engine.pdf_parallel' 之后添加:
        'engine.ocrmypdf_llmocr',
        'engine.ocrmypdf_llmocr.engine',
        'engine.ocrmypdf_llmocr.text_pdf',
```

同时确保 `pikepdf` 在 hiddenimports 中（如果没有的话）:

```python
        'pikepdf',
```

- [ ] **Step 2: 重新编译 exe 并部署**

```powershell
cd D:\opencode\book-downloader
python -m PyInstaller --noconfirm backend/book-downloader.spec
Copy-Item dist\BookDownloader.exe backend\dist\BookDownloader.exe -Force
```

Expected: Build complete, 约 185-190 MB。

- [ ] **Step 3: 实机功能验证**

启动 exe → 设置页选择 LLM OCR 引擎 → 创建任务 → 运行 → 打开输出 PDF → 验证文字可选/可搜索且位置与图片中文字对应。

- [ ] **Step 4: Commit**

```bash
git add backend/book-downloader.spec
git commit -m "build: add ocrmypdf_llmocr plugin to PyInstaller hiddenimports"
```

---

## 自我审核

**1. Spec coverage:**
- 文字层与图片层对齐 → Task 2 (`text_pdf.py` 估算行位置) + Task 3 (走 ocrmypdf sandwich 渲染)
- 使用 ocrmypdf 流程 → Task 1 (插件骨架) + Task 3 (pipeline 改为 ocrmypdf 命令)
- 引擎改为 LLM OCR → Task 2 (`generate_pdf` 调用 LLM API)

**2. Placeholder scan:** 通过。所有步骤含具体代码和命令。

**3. Type consistency:**
- `generate_pdf(input_file, output_pdf, output_text, options)` — 与 ocrmypdf `OcrEngine` 接口一致
- `create_text_only_pdf(output_pdf, page_text, image_path)` — 在 engine.py 中调用处参数匹配
- `_call_llm_sync` 返回 `str | None` — engine.py 中 `if text is None: text = ""` 正确处理
- `ocr_oversample` 来自 pipeline.py 配置读取，类型 `str` — 正确传入 cmd 列表
