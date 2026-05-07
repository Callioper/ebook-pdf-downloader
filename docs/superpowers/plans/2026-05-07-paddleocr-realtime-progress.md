# PaddleOCR Real-Time Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PaddleOCR parallel mode shows real-time page-level progress (page N/M, percentage, ETA) instead of staying at 30% until completion

**Architecture:** Replace `proc.communicate()` (blocking, no streaming) in `pdf_parallel.py` with line-by-line stdout reading + regex parsing of ocrmypdf progress output. Pass `total_pages` from pipeline so each chunk's progress maps to overall percentage. Emit progress at per-chunk page level + per-chunk completion level.

**Tech Stack:** Python asyncio, async subprocess, regex

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/engine/pdf_parallel.py` | 修改 | 核心改动：流式读取 + 进度解析 + 实时发射 |
| `backend/engine/pipeline.py` | 修改 | 传 `total_pages` 给 `run_paddleocr_parallel()` |

---

### Task 1: pdf_parallel.py — 流式读取 + 进度解析

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pdf_parallel.py`

当前问题：`process_chunk` 使用 `proc.communicate()` 缓冲全部输出直到 chunk 完成，期间零进度反馈。

- [ ] **Step 1: 修改 `run_paddleocr_parallel` 函数签名，接受 `total_pages`**

```python
async def run_paddleocr_parallel(
    *,
    pdf_path: str,
    output_pdf: str,
    paddle_python: str,
    ocr_lang: str,
    num_workers: int,
    total_pages: int = 0,    # NEW
    timeout_per_chunk: int = 1800,
    oversample: int = 200,
    optimize: str = "0",
    add_log: Optional[Callable] = None,
    emit_progress: Optional[Callable] = None,
) -> int:
```

找到第 78-90 行，在 `num_workers: int,` 之后加入 `total_pages: int = 0,`。

- [ ] **Step 2: 修改 `process_chunk` 内部函数——实现流式读取 + 进度解析**

将当前的 `proc.communicate()` 阻塞调用（第 137 行）替换为：

```python
async def process_chunk(i: int, chunk_path: str) -> Optional[str]:
    import re
    out_path = chunk_path.replace('.pdf', '_ocr.pdf')
    cmd = [
        paddle_python, "-m", "ocrmypdf",
        "--plugin", "ocrmypdf_paddleocr",
        "--optimize", optimize,
        "--oversample", str(oversample),
        "-l", ocr_lang or "chi_sim+eng",
        "-j", "1",
        "--output-type", "pdf",
        "--mode", "force",
        chunk_path,
        out_path,
    ]
    env = {**os.environ, "PATH": os.environ.get("PATH", "") + r";C:\Program Files\Tesseract-OCR",
           "PYTHONUNBUFFERED": "1"}

    chunk_start = time.time()
    chunk_pages = 0
    chunk_completed = 0

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        _spawned_procs.append(proc)

        async for line in proc.stdout:
            text = line.decode('utf-8', errors='replace').strip()
            if not text:
                continue

            # Parse progress patterns from ocrmypdf output
            m = re.search(r'\[(\d+)/(\d+)\]', text)
            if m:
                chunk_completed = int(m.group(1))
                chunk_pages = int(m.group(2))
            else:
                m = re.search(r'[Pp]age\s+(\d+)\s+[oO]f\s+(\d+)', text)
                if m:
                    chunk_completed = int(m.group(1))
                    chunk_pages = int(m.group(2))

            # Emit real-time progress
            if chunk_pages > 0 and chunk_completed > 0 and emit_progress is not None:
                _pages_before = sum(chunk_page_counts[:i]) if i > 0 else 0
                global_cur = _pages_before + chunk_completed
                if total_pages > 0:
                    _pct = int(global_cur / total_pages * 100)
                    _elapsed = time.time() - start_time
                    _speed = global_cur / _elapsed if _elapsed > 0 else 0
                    _eta = (total_pages - global_cur) / _speed if _speed > 0 else 0
                    _eta_str = f"{int(_eta // 60)}分{int(_eta % 60)}秒" if _eta > 0 else ""
                    await emit_progress(
                        step="ocr",
                        progress=_pct,
                        detail=f"{global_cur}/{total_pages} 页",
                        eta=_eta_str,
                    )
                else:
                    await emit_progress(
                        step="ocr",
                        progress=0,
                        detail=f"块 {i+1}: {chunk_completed}/{chunk_pages} 页",
                    )

        await proc.wait()

        if proc.returncode == 0 and os.path.exists(out_path):
            return out_path
        else:
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except Exception:
                    pass
            add_log(f"PaddleOCR chunk {i+1} failed: exit {proc.returncode}")
            return None
    except asyncio.TimeoutError:
        add_log(f"PaddleOCR chunk {i+1} timed out")
        try:
            proc.kill()
        except Exception:
            pass
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        return None
    except Exception as e:
        add_log(f"PaddleOCR chunk {i+1} error: {e}")
        try:
            if proc:
                proc.kill()
        except Exception:
            pass
        if os.path.exists(out_path):
            try:
                os.remove(out_path)
            except Exception:
                pass
        return None
    finally:
        if proc and proc in _spawned_procs:
            _spawned_procs.remove(proc)
```

**注意**：`_pages_before` 使用 Step 3 中预计算的 `chunk_page_counts`，避免运行时反复打开 PDF。

- [ ] **Step 3: 在 `run_paddleocr_parallel` 中添加 chunk 完成时的进度发射**

在 `asyncio.gather` 结束后（第 189 行之前），不需要额外改动——进度已在流式读取中发射。但需要更新 chunk 完成日志。

修改 `run_paddleocr_parallel` 函数体，在 `split_pdf` 调用后添加页数预计算：

在第 100 行 `chunks = split_pdf(pdf_path, num_workers)` 之后，加入：

```python
chunk_page_counts = []
for c in chunks:
    import fitz
    d = fitz.open(c)
    chunk_page_counts.append(len(d))
    d.close()
```

并在 `process_chunk` 中（第 111 行的函数定义），将 `chunk_page_counts` 作为闭包变量可用。修改 `_pages_before` 计算：

```python
_pages_before = sum(chunk_page_counts[:i]) if i > 0 else 0
```

- [ ] **Step 4: 处理 `chunk_page_counts` 闭包引用**

`process_chunk` 是 `run_paddleocr_parallel` 的内部函数，可以直接访问 `chunk_page_counts`。在第 111 行附近，替换原有的 `_pages_before` 行：

找到 `process_chunk` 函数定义的位置（约第 111 行），在进度发射代码中使用：

```python
# 在 async for line in proc.stdout 循环的进度发射部分
_pages_before = sum(chunk_page_counts[:i]) if i > 0 else 0
```

- [ ] **Step 5: 验证语法正确性**

```bash
python -c "import py_compile; py_compile.compile(r'D:\opencode\book-downloader\backend\engine\pdf_parallel.py', doraise=True); print('Syntax OK')"
```

- [ ] **Step 6: 提交**

```bash
git add backend/engine/pdf_parallel.py
git commit -m "feat: add real-time page progress to PaddleOCR parallel mode"
```

---

### Task 2: pipeline.py — 传递 total_pages

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pipeline.py:1682-1699`

在调用 `run_paddleocr_parallel` 时传入 `_total_pages`。

- [ ] **Step 1: 添加 `total_pages` 参数到调用处**

找到第 1686-1697 行的 `run_paddleocr_parallel(...)` 调用，在 `num_workers=ocr_jobs,` 之后加入：

```python
total_pages=_total_pages,
```

修改后的调用为：

```python
exit_code = await asyncio.wait_for(
    run_paddleocr_parallel(
        pdf_path=pdf_path,
        output_pdf=output_pdf,
        paddle_python=_paddle_venv_py,
        ocr_lang=ocr_lang,
        num_workers=ocr_jobs,
        total_pages=_total_pages,    # NEW
        timeout_per_chunk=ocr_timeout,
        oversample=int(ocr_oversample),
        optimize=_opt_level,
        add_log=lambda msg: task_store.add_log(task_id, f"  {msg}"),
        emit_progress=lambda **kw: _emit_progress(task_id, **kw),
    ),
    timeout=ocr_timeout,
)
```

- [ ] **Step 2: 验证语法正确性**

```bash
python -c "import py_compile; py_compile.compile(r'D:\opencode\book-downloader\backend\engine\pipeline.py', doraise=True); print('Syntax OK')"
```

- [ ] **Step 3: 提交**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: pass total_pages to run_paddleocr_parallel"
```

---

### Task 3: 构建并部署

- [ ] **Step 1: 构建 exe**

```bash
python -m PyInstaller --noconfirm "D:\opencode\book-downloader\backend\book-downloader.spec" 2>&1 | Select-Object -Last 3
```

Workdir: `D:\opencode\book-downloader`
Expected: `Build complete!`

- [ ] **Step 2: 部署**

```bash
Copy-Item "D:\opencode\book-downloader\dist\BookDownloader.exe" "D:\opencode\book-downloader\backend\dist\BookDownloader.exe" -Force
```

- [ ] **Step 3: 提交**

```bash
git add backend/dist/BookDownloader.exe
git commit -m "build: deploy exe with PaddleOCR real-time progress"
```

---

### Task 4: 端到端测试

- [ ] **Step 1: 启动 exe，创建 PaddleOCR 任务**

确保 exe 正在运行，通过 API 创建任务：

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" -d "{\"book_id\": \"2590784\"}"
```

记录 `task_id`。

- [ ] **Step 2: 设置 OCR 引擎为 PaddleOCR（多 worker）**

确保配置中 `ocr_engine=paddleocr` 且 `ocr_jobs > 1`。

- [ ] **Step 3: 启动任务，观察前端进度**

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/tasks/{task_id}/start
```

在前端 TaskDetail 页面观察：
- Step 5 (OCR) 进度从 30% 开始，逐步增长到 90%（合并）→ 100%
- 进度详情显示 `N/217 页`（实际页数/总页数）
- 进度不再长时间卡在 30%

- [ ] **Step 4: 验证 ETA 显示**

观察日志或前端是否有 `剩余 X分Y秒` 的 ETA 显示。

- [ ] **Step 5: 提交**

```bash
git commit --allow-empty -m "test: verify PaddleOCR real-time progress end-to-end"
```
