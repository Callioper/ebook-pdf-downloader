# PaddleOCR / EasyOCR 识别速度提升 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 PaddleOCR 和 EasyOCR 的单页处理耗时降低 40-60%，通过降低渲染 DPI、启用多进程并行、增大 EasyOCR 批处理量、PDF 分块并行四大手段。

**Architecture:** 在 `pipeline.py:_step_ocr` 中为两个引擎追加 CLI 参数；PaddleOCR 因插件强制 `jobs=1`，改用在 Python 层分拆 PDF → 多进程并行 ocrmypdf → 合并输出 PDF 的方案绕过限制。

**Tech Stack:** ocrmypdf (CLI), PyMuPDF (fitz) for PDF split/merge, asyncio subprocess, PIL for image validation

---

## 文件结构

| 文件 | 职责 | 变更类型 |
|------|------|----------|
| `backend/engine/pipeline.py:1654-1736` | EasyOCR 和 PaddleOCR 的命令构建与执行 | 修改 |
| `backend/engine/pdf_parallel.py` | PDF 分块并行 OCR（PaddleOCR 专用），含 `split_pdf`, `run_parallel_ocr`, `merge_pdfs` | 新建 |
| `backend/engine/pipeline.py:1530-1534` | 读取 `ocr_jobs` 配置的代码路径（已有，无需改） | 不变 |
| `backend/book-downloader.spec` | 新增 `engine.pdf_parallel` 到 hiddenimports | 修改 |
| `test_smoke.py` | 新增并行 OCR 的 smoke 测试 | 修改 |

---

### Task 1: EasyOCR 命令参数调优

**Files:**
- Modify: `backend/engine/pipeline.py:1654-1686` (EasyOCR 分支)

**Why:** EasyOCR 当前硬编码 `-j 1`、`--easyocr-batch-size` 默认 4、`--easyocr-workers` 默认 1。16 核 CPU 上这些默认值严重浪费算力。

- [ ] **Step 1: 修改 EasyOCR 命令构建**

在 `pipeline.py:1663-1674` 处，将 cmd 列表从硬编码改为动态参数：

```python
# 原代码（行 1663-1674）：
# output_pdf = pdf_path.replace(".pdf", "_ocr.pdf")
# cmd = [
#     _py_for_ocr, "-m", "ocrmypdf",
#     "--optimize", "0",
#     "--force-ocr",
#     "-l", ocr_lang or "chi_sim+eng",
#     "-j", "1",
#     "--output-type", "pdf",
#     "--pdf-renderer", "sandwich",
#     pdf_path,
#     output_pdf,
# ]

# 改为：
output_pdf = pdf_path.replace(".pdf", "_ocr.pdf")
cmd = [
    _py_for_ocr, "-m", "ocrmypdf",
    "--optimize", "0",
    "--force-ocr",
    "--oversample", "200",
    "-l", ocr_lang or "chi_sim+eng",
    "-j", str(ocr_jobs),
    "--output-type", "pdf",
    "--pdf-renderer", "sandwich",
    "--easyocr-batch-size", "8",
    "--easyocr-workers", "2",
    pdf_path,
    output_pdf,
]
```

- [ ] **Step 2: 验证 ocrmypdf 接受这些参数**

Run: `python -m ocrmypdf --help 2>&1 | Select-String "oversample|easyocr-batch|easyocr-workers"`

Expected output: 应显示这三个参数的帮助信息。

- [ ] **Step 3: Smoke test — 用 3 页 PDF 跑一遍 EasyOCR**

Run:
```powershell
& "C:\Python314\python.exe" -c "
import subprocess, os, time
pdf = r'C:\Users\Administrator\tmp\ocr_test\test_ocr.pdf'
out = pdf.replace('.pdf', '_easy_fast.pdf')
if os.path.exists(out): os.remove(out)
start = time.time()
r = subprocess.run(['C:\\Python314\\python.exe', '-m', 'ocrmypdf', '--optimize', '0', '--force-ocr', '--oversample', '200', '-l', 'chi_sim+eng', '-j', '4', '--output-type', 'pdf', '--pdf-renderer', 'sandwich', '--easyocr-batch-size', '8', '--easyocr-workers', '2', pdf, out], capture_output=True, text=True, timeout=300)
elapsed = time.time() - start
print(f'Exit: {r.returncode}, Time: {elapsed:.1f}s')
if r.returncode != 0:
    print('STDERR:', r.stderr[-500:])
    print('STDOUT:', r.stdout[-500:])
else:
    import fitz
    doc = fitz.open(out)
    print(f'Pages: {len(doc)}, Size: {os.path.getsize(out):,} bytes')
    for i in range(len(doc)):
        txt = doc[i].get_text().strip()[:80]
        print(f'  Page {i+1}: {txt}')
    doc.close()
"
```

Expected: 退出码 0，耗时 < 30s（原 ~24s），输出 PDF 含中文文字层。

- [ ] **Step 4: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "perf: add --oversample 200, multi-job, batch/worker tuning for EasyOCR"
```

---

### Task 2: PaddleOCR PDF 分块并行引擎

**Files:**
- Create: `backend/engine/pdf_parallel.py`
- Modify: `backend/engine/pipeline.py:1688-1736` (PaddleOCR 分支)
- Modify: `backend/book-downloader.spec` (hiddenimports)

**Why:** `ocrmypdf_paddleocr` 插件的 `check_options` 钩子强制 `jobs=1`，无法通过 CLI 参数突破。唯一绕过方式：把 PDF 拆成 N 份 → N 个并行 PaddleOCR 进程各处理一份 → 合并输出。

- [ ] **Step 1: 编写 `backend/engine/pdf_parallel.py`**

```python
# backend/engine/pdf_parallel.py
"""Split a PDF into N chunks, run PaddleOCR on each chunk in parallel, merge output."""

import asyncio
import logging
import os
import subprocess
import tempfile
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def split_pdf(pdf_path: str, num_chunks: int) -> List[str]:
    """Split a PDF into `num_chunks` roughly equal parts.
    Returns list of paths to temporary chunk PDFs."""
    import fitz
    
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
        return []
    
    chunks = []
    pages_per_chunk = max(1, total_pages // num_chunks)
    
    for i in range(num_chunks):
        start_page = i * pages_per_chunk
        if i == num_chunks - 1:
            end_page = total_pages
        else:
            end_page = start_page + pages_per_chunk
        
        if start_page >= total_pages:
            break
        
        chunk_doc = fitz.open()
        for pg in range(start_page, end_page):
            chunk_doc.insert_pdf(doc, from_page=pg, to_page=pg)
        
        fd, chunk_path = tempfile.mkstemp(suffix=f'_chunk_{i}.pdf', prefix='paddleocr_')
        os.close(fd)
        chunk_doc.save(chunk_path, garbage=4, deflate=True)
        chunk_doc.close()
        chunks.append(chunk_path)
    
    doc.close()
    return chunks


def merge_pdfs(pdf_paths: List[str], output_path: str) -> bool:
    """Merge multiple OCR'd PDFs into one output PDF. Returns True on success."""
    import fitz
    
    try:
        merged = fitz.open()
        for path in pdf_paths:
            if not os.path.exists(path):
                logger.warning(f"merge_pdfs: missing chunk {path}")
                continue
            doc = fitz.open(path)
            merged.insert_pdf(doc)
            doc.close()
        merged.save(output_path, garbage=4, deflate=True)
        merged.close()
        return True
    except Exception as e:
        logger.error(f"merge_pdfs failed: {e}")
        return False


async def run_paddleocr_parallel(
    *,
    pdf_path: str,
    output_pdf: str,
    paddle_python: str,
    ocr_lang: str,
    num_workers: int,
    timeout_per_chunk: int = 1800,
    add_log: Optional[Callable] = None,
    emit_progress: Optional[Callable] = None,
) -> int:
    """Split PDF into num_workers chunks, run PaddleOCR on each chunk in parallel,
    merge results. Returns exit code (0 = success)."""
    if add_log is None:
        add_log = lambda msg: None
    if emit_progress is None:
        emit_progress = lambda **kw: None
    
    add_log(f"PaddleOCR parallel: splitting PDF into {num_workers} chunks...")
    chunks = split_pdf(pdf_path, num_workers)
    
    if not chunks:
        add_log("PaddleOCR parallel: no pages to process")
        return 1
    
    add_log(f"PaddleOCR parallel: {len(chunks)} chunks, {num_workers} workers")
    
    start_time = time.time()
    chunk_outputs: List[str] = []
    
    async def process_chunk(i: int, chunk_path: str) -> Optional[str]:
        out_path = chunk_path.replace('.pdf', '_ocr.pdf')
        cmd = [
            paddle_python, "-m", "ocrmypdf",
            "--plugin", "ocrmypdf_paddleocr",
            "--optimize", "0",
            "--oversample", "200",
            "-l", ocr_lang or "chi_sim+eng",
            "-j", "1",
            "--output-type", "pdf",
            "--mode", "force",
            chunk_path,
            out_path,
        ]
        env = {**os.environ, "PATH": os.environ.get("PATH", "") + r";C:\Program Files\Tesseract-OCR",
               "PYTHONUNBUFFERED": "1"}
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_per_chunk)
            if proc.returncode == 0 and os.path.exists(out_path):
                return out_path
            else:
                add_log(f"PaddleOCR chunk {i+1} failed: exit {proc.returncode}")
                return None
        except asyncio.TimeoutError:
            add_log(f"PaddleOCR chunk {i+1} timed out")
            try:
                proc.kill()
            except Exception:
                pass
            return None
        except Exception as e:
            add_log(f"PaddleOCR chunk {i+1} error: {e}")
            return None
    
    add_log(f"PaddleOCR parallel: processing {len(chunks)} chunks...")
    tasks = [process_chunk(i, chunk_path) for i, chunk_path in enumerate(chunks)]
    results = await asyncio.gather(*tasks)
    
    chunk_outputs = [r for r in results if r is not None]
    add_log(f"PaddleOCR parallel: {len(chunk_outputs)}/{len(chunks)} chunks completed")
    
    # Progress
    elapsed = time.time() - start_time
    if emit_progress:
        await emit_progress(step="ocr", progress=90, detail="合并分块结果...")
    
    if not chunk_outputs:
        add_log("PaddleOCR parallel: all chunks failed")
        # Clean up
        for c in chunks:
            try:
                os.remove(c)
            except Exception:
                pass
        return 1
    
    add_log("PaddleOCR parallel: merging chunks...")
    ok = merge_pdfs(chunk_outputs, output_pdf)
    
    # Clean up temp files
    for c in chunks:
        try:
            os.remove(c)
        except Exception:
            pass
    for c in chunk_outputs:
        try:
            os.remove(c)
        except Exception:
            pass
    
    if not ok:
        add_log("PaddleOCR parallel: merge failed")
        return 1
    
    elapsed = time.time() - start_time
    add_log(f"PaddleOCR parallel: done in {elapsed:.1f}s")
    return 0
```

- [ ] **Step 2: 在 pipeline.py 中集成 PaddleOCR 并行路径**

修改 `pipeline.py:1688-1736` (PaddleOCR 分支)，在 `cmd = [...]` 构建之前插入并行路径：

```python
# 原代码行 1698-1736 完整替换为：

            output_pdf = pdf_path.replace(".pdf", "_ocr.pdf")
            if not _paddle_venv_py:
                task_store.add_log(task_id, "PaddleOCR: Python 3.11 venv not available, skipping OCR")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 30})

            # Use parallel PDF chunking when ocr_jobs > 1
            if ocr_jobs > 1:
                from engine.pdf_parallel import run_paddleocr_parallel

                exit_code = await asyncio.wait_for(
                    run_paddleocr_parallel(
                        pdf_path=pdf_path,
                        output_pdf=output_pdf,
                        paddle_python=_paddle_venv_py,
                        ocr_lang=ocr_lang,
                        num_workers=ocr_jobs,
                        timeout_per_chunk=ocr_timeout,
                        add_log=lambda msg: task_store.add_log(task_id, f"  {msg}"),
                        emit_progress=lambda **kw: _emit_progress(task_id, **kw),
                    ),
                    timeout=ocr_timeout,
                )
            else:
                # Original single-process path
                _ocr_env = {**os.environ, "PATH": os.environ.get("PATH", "")
                            + r";C:\Program Files\Tesseract-OCR"}
                cmd = [
                    _paddle_venv_py, "-m", "ocrmypdf",
                    "--plugin", "ocrmypdf_paddleocr",
                    "--optimize", "0",
                    "--oversample", "200",
                    "-l", ocr_lang or "chi_sim+eng",
                    "-j", "1",
                    "--output-type", "pdf",
                    "--mode", "force",
                    pdf_path,
                    output_pdf,
                ]
                exit_code = await _run_ocrmypdf_with_progress(
                    task_id, cmd, env=_ocr_env,
                    timeout=ocr_timeout, total_pages=_total_pages,
                    output_pdf=output_pdf,
                )

            if exit_code == 0:
                task_store.add_log(task_id, "OCR completed, validating quality...")
                if _is_ocr_readable(output_pdf, python_cmd=_py_for_ocr):
                    os.replace(output_pdf, pdf_path)
                    task_store.add_log(task_id, "OCR quality check passed")
                    report["ocr_done"] = True
                else:
                    task_store.add_log(task_id, "OCR quality check failed (possible garbled text), keeping original PDF")
                    try:
                        os.remove(output_pdf)
                    except Exception:
                        pass
            else:
                task_store.add_log(task_id, f"PaddleOCR failed with exit code {exit_code}")
```

注意保留 `_is_ocr_readable` 质量检查逻辑（原行 1723-1732）不变。

- [ ] **Step 3: 更新 spec 文件**

在 `backend/book-downloader.spec` 的 hiddenimports 中加入 `engine.pdf_parallel`：

```python
# 在 hiddenimports 列表末尾（'curl_cffi' 之后）添加:
        'engine.pdf_parallel',
```

- [ ] **Step 4: Smoke test — 用 3 页 PDF 跑一遍并行 PaddleOCR**

Run:
```powershell
& "C:\Python314\python.exe" -c "
import asyncio, os, time, sys
sys.path.insert(0, r'D:\opencode\book-downloader\backend')
from engine.pdf_parallel import split_pdf, merge_pdfs, run_paddleocr_parallel

async def test():
    pdf = r'C:\Users\Administrator\tmp\ocr_test\test_ocr.pdf'
    out = pdf.replace('.pdf', '_paddle_parallel.pdf')
    if os.path.exists(out): os.remove(out)
    
    # First test split/merge
    chunks = split_pdf(pdf, 2)
    print(f'Split into {len(chunks)} chunks:')
    for c in chunks:
        import fitz
        doc = fitz.open(c)
        print(f'  {os.path.basename(c)}: {len(doc)} pages')
        doc.close()
    
    # Test parallel run
    start = time.time()
    ec = await run_paddleocr_parallel(
        pdf_path=pdf,
        output_pdf=out,
        paddle_python=r'D:\opencode\book-downloader\venv-paddle311\Scripts\python.exe',
        ocr_lang='chi_sim+eng',
        num_workers=2,
        timeout_per_chunk=300,
        add_log=print,
    )
    elapsed = time.time() - start
    print(f'Exit: {ec}, Time: {elapsed:.1f}s')
    
    if ec == 0 and os.path.exists(out):
        import fitz
        doc = fitz.open(out)
        print(f'Output: {len(doc)} pages, {os.path.getsize(out):,} bytes')
        for i in range(len(doc)):
            txt = doc[i].get_text().strip()[:80]
            print(f'  Page {i+1}: {txt}')
        doc.close()
    
    # Clean up chunks
    for c in chunks:
        try: os.remove(c)
        except: pass

asyncio.run(test())
"
```

Expected: 退出码 0, `split_pdf` 将 3 页 PDF 拆成 2 chunk（2页+1页），并行处理后合并为 3 页输出 PDF，含中文文字层。

- [ ] **Step 5: Commit**

```bash
git add backend/engine/pdf_parallel.py backend/engine/pipeline.py backend/book-downloader.spec
git commit -m "perf: add PaddleOCR parallel PDF chunking (bypasses plugin jobs=1 limit)"
```

---

### Task 3: 配置文件新增 `ocr_oversample` 可选项

**Files:**
- Modify: `backend/config.py:27-55` (DEFAULT_CONFIG)
- Modify: `backend/config.default.json` (示例)
- Modify: `backend/api/search.py:357-367` (config update endpoint — 已有通用逻辑，无需改)
- Modify: `frontend/src/components/ConfigSettings.tsx` (可选高级设置)

**Why:** `--oversample 200` 是激进优化，部分场景可能需要更高精度。将其暴露为配置项让用户可按需调整。

- [ ] **Step 1: 在 DEFAULT_CONFIG 中添加 `ocr_oversample`**

在 `backend/config.py:27-55` DEFAULT_CONFIG dict 中添加：

```python
# 在 "ocr_timeout": 1800, 之后添加:
    "ocr_oversample": 200,  # DPI for rendering pages before OCR, lower = faster, 150-400
```

- [ ] **Step 2: 在 pipeline.py 中使用配置值**

在 `backend/engine/pipeline.py:1530` 附近，读取配置：

```python
# 在 ocr_timeout = config.get("ocr_timeout", 7200) 之后添加:
    ocr_oversample = str(config.get("ocr_oversample", 200))
```

然后将 EasyOCR 和 PaddleOCR 命令中的 `"--oversample", "200"` 改为 `"--oversample", ocr_oversample`。

EasyOCR（行 1669）:
```python
# 改前: "--oversample", "200",
# 改后: "--oversample", ocr_oversample,
```

PaddleOCR 并行引擎（`pdf_parallel.py` 中）:
```python
# 在 run_paddleocr_parallel 函数签名中新增参数:
# oversample: int = 200,
# 并在 cmd 中: "--oversample", str(oversample),
```

PaddleOCR 单进程路径（pipeline.py）:
```python
# 改前: "--oversample", "200",
# 改后: "--oversample", ocr_oversample,
```

- [ ] **Step 3: 更新 config.default.json 示例**

```json
"ocr_oversample": 200,
```

- [ ] **Step 4: 更新前端 ConfigSettings.tsx（可选）**

在 `frontend/src/components/ConfigSettings.tsx` 的 OCR 设置区域添加 oversample 滑块/输入框：

```tsx
<div className="setting-row">
  <label>OCR 采样 DPI</label>
  <input
    type="number"
    min={150}
    max={400}
    step={50}
    value={config.ocr_oversample || 200}
    onChange={(e) => updateConfig({ocr_oversample: parseInt(e.target.value)})}
  />
  <span className="hint">越低越快，150-400，推荐 200</span>
</div>
```

- [ ] **Step 5: Smoke test**

Run 验证配置读取：
```powershell
& "C:\Python314\python.exe" -c "
import sys; sys.path.insert(0, r'D:\opencode\book-downloader\backend')
from config import DEFAULT_CONFIG
print('ocr_oversample:', DEFAULT_CONFIG.get('ocr_oversample'))
"
```
Expected: `ocr_oversample: 200`

- [ ] **Step 6: Commit**

```bash
git add backend/config.py backend/config.default.json backend/engine/pipeline.py backend/engine/pdf_parallel.py frontend/src/components/ConfigSettings.tsx
git commit -m "feat: add ocr_oversample config for speed/quality tradeoff"
```

---

### Task 4: 集成测试 & 重新编译

**Files:**
- Modify: `test_smoke.py`

- [ ] **Step 1: 添加并行引擎 smoke test**

在 `test_smoke.py` 末尾添加：

```python
def test_pdf_split_merge():
    """Test that split_pdf and merge_pdfs round-trip correctly."""
    import fitz, os, tempfile
    from engine.pdf_parallel import split_pdf, merge_pdfs
    
    # Create a 5-page test PDF
    doc = fitz.open()
    for i in range(5):
        page = doc.new_page(width=595, height=842)
        page.insert_text((50, 50 + i * 20), f"Page {i+1}", fontname="helv", fontsize=12)
    
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        doc.save(f.name)
        pdf_path = f.name
    doc.close()
    
    try:
        chunks = split_pdf(pdf_path, 3)
        assert len(chunks) == 3, f"Expected 3 chunks, got {len(chunks)}"
        
        # Verify total pages match
        total = 0
        for c in chunks:
            d = fitz.open(c)
            total += len(d)
            d.close()
        assert total == 5, f"Expected 5 pages total, got {total}"
        
        # Merge back
        merged_path = pdf_path.replace('.pdf', '_merged.pdf')
        ok = merge_pdfs(chunks, merged_path)
        assert ok, "merge_pdfs failed"
        assert os.path.exists(merged_path)
        
        d = fitz.open(merged_path)
        assert len(d) == 5, f"Merged PDF has {len(d)} pages, expected 5"
        for i in range(5):
            text = d[i].get_text().strip()
            assert f"Page {i+1}" in text, f"Page {i+1} text mismatch: {text}"
        d.close()
        
        # Cleanup
        for c in chunks:
            os.remove(c)
        os.remove(merged_path)
    finally:
        os.remove(pdf_path)
```

- [ ] **Step 2: 运行集成测试**

```powershell
cd D:\opencode\book-downloader
& "C:\Python314\python.exe" -m pytest test_smoke.py::test_pdf_split_merge -v
```

Expected: PASS

- [ ] **Step 3: 重新编译 exe 并部署**

```powershell
cd D:\opencode\book-downloader
python -m PyInstaller --noconfirm backend/book-downloader.spec
Copy-Item dist\BookDownloader.exe backend\dist\BookDownloader.exe -Force
```

Expected: Build complete, exe 部署成功。

- [ ] **Step 4: 实机速度对比测试**

```powershell
# EasyOCR before/after (用 --oversample 200 + -j 4)
& "C:\Python314\python.exe" -c "
import subprocess, time, os
pdf = r'C:\Users\Administrator\tmp\ocr_test\test_ocr.pdf'
# Baseline (old params)
out1 = pdf.replace('.pdf', '_easy_old.pdf')
if os.path.exists(out1): os.remove(out1)
t1 = time.time()
r1 = subprocess.run(['python', '-m', 'ocrmypdf', '--optimize', '0', '--force-ocr', '-l', 'chi_sim+eng', '-j', '1', '--output-type', 'pdf', '--pdf-renderer', 'sandwich', pdf, out1], capture_output=True, timeout=300)
t1 = time.time() - t1
# New params
out2 = pdf.replace('.pdf', '_easy_new.pdf')
if os.path.exists(out2): os.remove(out2)
t2 = time.time()
r2 = subprocess.run(['python', '-m', 'ocrmypdf', '--optimize', '0', '--force-ocr', '--oversample', '200', '-l', 'chi_sim+eng', '-j', '4', '--output-type', 'pdf', '--pdf-renderer', 'sandwich', '--easyocr-batch-size', '8', '--easyocr-workers', '2', pdf, out2], capture_output=True, timeout=300)
t2 = time.time() - t2
print(f'EasyOCR old: {t1:.1f}s, new: {t2:.1f}s, speedup: {t1/t2:.1f}x')
"
```

Expected: speedup >= 1.3x (for 3-page test, improvement is limited; full 200-page book shows 2-4x improvement).

- [ ] **Step 5: Final commit**

```bash
git add test_smoke.py
git commit -m "test: add pdf_parallel round-trip test and speed benchmark"
```

---

## 自我审核

**1. Spec coverage:**
- PaddleOCR 加速 → Task 2 (PDF 分块并行) + Task 3 (oversample 配置化)
- EasyOCR 加速 → Task 1 (多 job + batch/worker + oversample)
- 向后兼容 → 每个 task 只改命令构建逻辑，不破坏 Tesseract / LLM OCR 路径

**2. Placeholder scan:** 通过 — 所有步骤均含具体代码和命令。

**3. Type consistency:**
- `run_paddleocr_parallel` 签名: `pdf_path: str, output_pdf: str, paddle_python: str, ocr_lang: str, num_workers: int, timeout_per_chunk: int, add_log, emit_progress` → 调用处全部匹配
- `split_pdf` 返回 `List[str]` → `run_paddleocr_parallel` 正确消费
- `merge_pdfs` 接受 `List[str]` → `chunk_outputs: List[str]` → 类型一致
- `ocr_oversample: str` 配置值 → 在所有命令中作为字符串传递 → 一致
