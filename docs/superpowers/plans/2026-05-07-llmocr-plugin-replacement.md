# LLM OCR Replacement with `llmocr` Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current `engine/ocrmypdf_llmocr/` plugin and `engine/llm_ocr.py` with the `ahnafnafee/local-llm-pdf-ocr` project (`llmocr` v1.2.0), which uses Tesseract layout analysis + LLM text + DP alignment for accurate per-word text positioning.

**Architecture:** `llmocr` is an ocrmypdf plugin (entry_point-based). It uses Tesseract TSV output for word-level bounding boxes, sends the page image to an LLM for text recognition, then DP-aligns LLM lines to Tesseract boxes before generating a text-only PDF via pikepdf. Our pipeline switches from direct Python call to `--plugin llmocr` path.

**Tech Stack:** ocrmypdf plugin system, Tesseract (layout only), LLM API (OpenAI-compatible), pikepdf, Needleman-Wunsch DP alignment

---

## 文件结构

| 文件 | 职责 | 变更 |
|------|------|------|
| `backend/engine/llmocr/` | 复制自 `D:\opencode\llmocr\src\llmocr/` 的完整插件（plugin.py, engine.py, llm_client.py, layout.py, text_pdf.py） | **新建** |
| `backend/engine/pipeline.py:1738-1800` | LLM OCR 分支改为 ocrmypdf + `--plugin llmocr` | **修改** |
| `backend/engine/llm_ocr.py` | 保留 `verify_llm_model`、`ocr_page`（被 check-ocr 端点使用），删除其余函数 | **修改** |
| `backend/engine/ocrmypdf_llmocr/` | 旧的 LLM OCR 插件（已不适用） | **删除** |
| `backend/api/search.py:766-779` | check-ocr 端点保持使用 `verify_llm_model` | 不变 |
| `backend/book-downloader.spec` | hiddenimports 加入 `engine.llmocr`，移除 `engine.ocrmypdf_llmocr` | **修改** |

---

### Task 1: 复制 `llmocr` 插件到项目并安装依赖

**Files:**
- Create: `D:\opencode\book-downloader\backend\engine\llmocr/`（完整复制自 `D:\opencode\llmocr\src\llmocr/`）

- [ ] **Step 1: 复制插件到项目**

```powershell
Remove-Item -Recurse -Force "D:\opencode\book-downloader\backend\engine\llmocr" -ErrorAction SilentlyContinue
Copy-Item -Recurse "D:\opencode\llmocr\src\llmocr" "D:\opencode\book-downloader\backend\engine\llmocr"
Write-Output "Copied"
```

- [ ] **Step 2: 安装依赖**

```powershell
pip install fpdf2 pikepdf httpx
```

- [ ] **Step 3: 验证导入**

```powershell
$env:PYTHONPATH = "D:\opencode\book-downloader\backend\engine"
python -c "from llmocr.plugin import add_options, check_options, get_ocr_engine; from llmocr.engine import LlmOcrEngine; print('Import OK')"
```

Expected: `Import OK`

- [ ] **Step 4: Commit**

```bash
git add backend/engine/llmocr/
git commit -m "feat: add llmocr plugin (Tesseract layout + LLM text + DP alignment)"
```

---

### Task 2: 安装 `llmocr` 并测试端到端

**Files:**
- Modify: none (test only)

- [ ] **Step 1: 安装 `llmocr` pip 包（使其 entry_point 被 ocrmypdf 发现）**

```powershell
cd D:\opencode\llmocr
pip install -e .
```

Verify:
```powershell
python -c "import llmocr; print(llmocr.__version__)"
```

Expected: `1.2.0`

- [ ] **Step 2: 测试 LLM OCR 端到端（3 页 PDF）**

```powershell
$env:PYTHONPATH = "D:\opencode\book-downloader\backend\engine"
python -m ocrmypdf `
  --plugin llmocr `
  --llm-ocr-endpoint "http://127.0.0.1:12345" `
  --llm-ocr-model "noctrex/paddleocr-vl-1.5" `
  --llm-ocr-lang "chi_sim+eng" `
  --llm-ocr-timeout 300 `
  --optimize 0 `
  --output-type pdf `
  --pdf-renderer sandwich `
  "C:\Users\Administrator\tmp\ocr_test\test_ocr.pdf" `
  "C:\Users\Administrator\tmp\ocr_test\test_llmocr_output.pdf"
```

Expected: Exit code 0, output PDF has text layer aligned with image content.

- [ ] **Step 3: 验证输出 PDF 有文字**

```python
import fitz
d = fitz.open(r'C:\Users\Administrator\tmp\ocr_test\test_llmocr_output.pdf')
for i in range(len(d)):
    print(f'Page {i+1}: {d[i].get_text().strip()[:100]}')
d.close()
```

Expected: Chinese text correctly extracted and positioned.

- [ ] **Step 4: Commit**

```bash
git add backend/engine/llmocr/
git commit -m "feat: register llmocr plugin via pip install -e"
```

---

### Task 3: 修改 Pipeline 使用 `--plugin llmocr`

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pipeline.py:1738-1800`
- Delete: `D:\opencode\book-downloader\backend\engine\ocrmypdf_llmocr/`
- Modify: `D:\opencode\book-downloader\backend\engine\llm_ocr.py`

- [ ] **Step 1: 替换 pipeline.py 的 LLM OCR 分支**

找到 `elif ocr_engine == "llm_ocr":` 分支（当前约 1738-1800 行），完整替换为：

```python
        elif ocr_engine == "llm_ocr":
            task_store.add_log(task_id, "Running LLM-based OCR via llmocr plugin...")

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

            cmd = [
                _py_for_ocr, "-m", "ocrmypdf",
                "--plugin", "llmocr",
                "--llm-ocr-endpoint", llm_endpoint,
                "--llm-ocr-model", llm_model,
                "--llm-ocr-lang", ocr_lang or "chi_sim+eng",
                "--llm-ocr-timeout", "300",
                "--optimize", _opt_level,
                "--oversample", ocr_oversample,
                "-j", str(ocr_jobs),
                "--output-type", "pdf",
                "--pdf-renderer", "sandwich",
                pdf_path,
                output_pdf,
            ]
            if llm_api_key:
                cmd.insert(cmd.index("--llm-ocr-lang") + 2, "--llm-ocr-api-key")
                cmd.insert(cmd.index("--llm-ocr-api-key") + 1, llm_api_key)

            # Ensure PYTHONPATH includes our plugin directory
            _engine_dir = os.path.dirname(__file__)
            _ocr_env = {
                **os.environ,
                "PYTHONPATH": os.pathsep.join(
                    [_engine_dir] + os.environ.get("PYTHONPATH", "").split(os.pathsep)
                    if os.environ.get("PYTHONPATH")
                    else [_engine_dir]
                ),
                "PYTHONUNBUFFERED": "1",
                "PYTHONIOENCODING": "utf-8",
            }

            try:
                _exit = await _run_ocrmypdf_with_progress(
                    task_id, cmd, env=_ocr_env,
                    timeout=ocr_timeout, total_pages=_total_pages,
                    output_pdf=output_pdf,
                )
                if _exit == 0:
                    task_store.add_log(task_id, "LLM OCR completed, validating quality...")
                    if _is_ocr_readable(output_pdf, python_cmd=_py_for_ocr):
                        os.replace(output_pdf, pdf_path)
                        task_store.add_log(task_id, "LLM OCR quality check passed")
                        report["ocr_done"] = True
                    else:
                        task_store.add_log(task_id, "LLM OCR quality check failed, keeping original PDF")
                        try:
                            os.remove(output_pdf)
                        except Exception:
                            pass
                else:
                    task_store.add_log(task_id, f"LLM OCR failed with exit code {_exit}")
            except asyncio.TimeoutError:
                task_store.add_log(task_id, f"LLM OCR timed out after {ocr_timeout}s")
            except Exception as e:
                task_store.add_log(task_id, f"LLM OCR error: {e}")
```

关键变化：
- `--plugin` 从 `ocrmypdf_llmocr` 改为 `llmocr`
- 添加 `--llm-ocr-timeout 300`（新插件支持的超时参数）
- PYTHONPATH 中加入 `_engine_dir` 使 `llmocr` 可导入

- [ ] **Step 2: 删除旧插件**

```powershell
Remove-Item -Recurse -Force "D:\opencode\book-downloader\backend\engine\ocrmypdf_llmocr" -ErrorAction SilentlyContinue
```

- [ ] **Step 3: 裁剪 `llm_ocr.py`**

删除 `run_llm_ocr()`、`build_searchable_pdf()`、`extract_page_images()`、`encode_image_to_base64()`（已由插件替代）。
保留 `verify_llm_model()` 和 `ocr_page()`（被 `check-ocr` 端点使用）。

- [ ] **Step 4: 验证语法**

```powershell
python -c "import py_compile; py_compile.compile(r'D:\opencode\book-downloader\backend\engine\pipeline.py', doraise=True); print('PIPELINE OK')"
```

- [ ] **Step 5: Commit**

```bash
git add backend/engine/pipeline.py backend/engine/llm_ocr.py
git rm -r backend/engine/ocrmypdf_llmocr
git commit -m "refactor: use llmocr plugin for LLM OCR (Tesseract layout + DP alignment)"
```

---

### Task 4: 更新设置与检查端点

**Files:**
- Modify: `D:\opencode\book-downloader\frontend\src\components\ConfigSettings.tsx`
- Verify: `D:\opencode\book-downloader\backend\api\search.py:766-779`

- [ ] **Step 1: 确认 check-ocr 端点兼容**

`check-ocr` 端点使用 `from engine.llm_ocr import verify_llm_model`（保留的函数），不需要改动。

- [ ] **Step 2: 更新前端 `llm_ocr_timeout` 配置**

在 `ConfigSettings.tsx` 的 LLM OCR 设置区域，添加超时配置输入框。找到 LLM OCR 配置区（endpoint、model、api_key 附近），添加：

```tsx
<div className="setting-row">
  <label>请求超时（秒）</label>
  <input
    type="number"
    min={30}
    max={600}
    step={30}
    value={form.llm_ocr_timeout || 300}
    onChange={(e) => setForm((prev) => ({ ...prev, llm_ocr_timeout: parseInt(e.target.value) || 300 }))}
  />
  <span className="hint">每次 LLM 请求超时，默认 300s</span>
</div>
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ConfigSettings.tsx
git commit -m "feat: add llm_ocr_timeout to settings UI"
```

---

### Task 5: 更新 PyInstaller Spec 并重新编译

**Files:**
- Modify: `D:\opencode\book-downloader\backend\book-downloader.spec`

- [ ] **Step 1: 更新 hiddenimports 和 datas**

将 `engine.ocrmypdf_llmocr` 相关 hiddenimports 替换为 `engine.llmocr`：

```python
# 移除:
'engine.ocrmypdf_llmocr',
'engine.ocrmypdf_llmocr.engine',
'engine.ocrmypdf_llmocr.text_pdf',

# 添加:
'engine.llmocr',
'engine.llmocr.plugin',
'engine.llmocr.engine',
'engine.llmocr.llm_client',
'engine.llmocr.layout',
'engine.llmocr.text_pdf',
```

`engine/` 目录已包含在 datas 中，`llmocr/` 在其子目录下，会自动打包。

- [ ] **Step 2: 重新编译 exe**

```powershell
cd D:\opencode\book-downloader
python -m PyInstaller --noconfirm backend/book-downloader.spec
```

- [ ] **Step 3: 部署**

```powershell
Copy-Item dist\BookDownloader.exe backend\dist\BookDownloader.exe -Force
```

- [ ] **Step 4: 实机测试 LLM OCR**

启动 exe → 设置页配置 LLM OCR endpoint/model → 创建任务 → 验证输出 PDF 有正确对齐的文字层。

- [ ] **Step 5: Commit**

```bash
git add backend/book-downloader.spec
git commit -m "build: replace ocrmypdf_llmocr with llmocr plugin in PyInstaller spec"
```

---

## 自我审核

**1. Spec coverage:**
- 替换为 `llmocr` 插件 → Task 1-2 (复制 + 测试)
- Pipeline 改用 `--plugin llmocr` → Task 3
- 删除旧代码 → Task 3
- 前端设置更新 → Task 4
- 编译部署 → Task 5

**2. Placeholder scan:** 通过。所有步骤含具体代码和命令。

**3. Type consistency:**
- `_run_ocrmypdf_with_progress` 签名未改，仅 cmd 增加 `--llm-ocr-timeout`
- `_is_ocr_readable` 质量检查保留
- `verify_llm_model` 保留（`llm_ocr.py` 中未被删除的函数）
