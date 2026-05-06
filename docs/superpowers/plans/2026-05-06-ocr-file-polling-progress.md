# OCR 文件轮询实时进度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 PaddleOCR/EasyOCR 的进度反馈从纯心跳"处理中... N分N秒"升级为文件轮询方式的真实页面级进度"5/217 页"，同时保留 Tesseract 的 stderr 解析方案不变。

**Architecture:** 在现有 `_monitor` 定时任务中增加 PDF 页面计数逻辑——每 5 秒尝试用 fitz 打开输出 PDF、读取已完成的页数、与 total_pages 对比计算百分比和 ETA。Tesseract 仍使用 stderr 解析方案（更精确），PaddleOCR/EasyOCR 自动回退到文件轮询。

**Tech Stack:** Python 3.10+ (PyMuPDF/fitz)

---

## File Structure

| File | Change | Responsibility |
|------|--------|---------------|
| `backend/engine/pipeline.py` | Modify | 在 `_monitor` 中添加 PDF 页数检测 |

---

### Task 1: 添加文件轮询页面计数

**Files:**
- Modify: `backend/engine/pipeline.py` (in `_run_ocrmypdf_with_progress`)

添加一个辅助函数用于安全读取输出 PDF 的当前页数，并在 `_monitor` 中使用它来生成真实进度。

- [ ] **Step 1: 添加输出 PDF 页数读取函数**

在 `_run_ocrmypdf_with_progress` 函数内部，在 `_monitor` 定义之前添加：

```python
    def _count_output_pages() -> int:
        """Try to open output PDF and count pages. Returns 0 if not accessible yet."""
        try:
            import fitz as _fitz
            _doc = _fitz.open(output_pdf)
            _n = len(_doc)
            _doc.close()
            return _n
        except Exception:
            return 0
```

注意：`output_pdf` 变量来自函数参数，需在函数签名中添加。目前 `_run_ocrmypdf_with_progress` 的参数只有 `task_id, cmd, env, timeout, total_pages`。需要新增 `output_pdf` 参数。

- [ ] **Step 2: 更新 `_run_ocrmypdf_with_progress` 签名**

在函数签名中添加 `output_pdf` 参数：

```python
async def _run_ocrmypdf_with_progress(
    task_id: str, cmd: List[str],
    env: Optional[Dict[str, Optional[str]]] = None,
    timeout: int = 7200,
    total_pages: int = 0,
    output_pdf: str = "",
) -> int:
```

- [ ] **Step 3: 在 `_monitor` 中使用页面计数**

修改 `_monitor` 函数，在发送心跳时尝试文件轮询：

```python
    async def _monitor(p):
        """Emit heartbeat progress while process is running."""
        nonlocal _cur, _tot
        while p.returncode is None:
            await asyncio.sleep(5)
            if p.returncode is not None:
                break
            # Check if task was cancelled
            _t = task_store.get(task_id)
            if _t and _t.get("status") == "cancelled":
                try:
                    p.kill()
                except Exception:
                    pass
                break

            # Try file-based page counting (works for all engines)
            _file_pages = 0
            if output_pdf and total_pages > 0:
                _file_pages = _count_output_pages()

            _now = time.time()
            _elapsed_sec = int(_now - _start)

            if _file_pages > 0 and _file_pages > _cur:
                # File-based progress found — update real page tracking
                _cur = _file_pages
                _tot = total_pages
                _pct = int(_cur / _tot * 100)
                _eta = ""
                if _cur > 1 and _elapsed_sec > 5:
                    _sec_pp = _elapsed_sec / _cur
                    _rem = (_tot - _cur) * _sec_pp
                    _eta = f"约{int(_rem//60)}分{int(_rem%60)}秒" if _rem > 60 else f"约{int(_rem)}秒"
                await _emit_progress(task_id, "ocr", _pct, f"{_cur}/{_tot} 页", _eta)
            elif _cur == 0 or total_pages == 0:
                # No page info available yet — fallback to heartbeat
                _detail = f"处理中... {_elapsed_sec//60}分{_elapsed_sec%60}秒" if _elapsed_sec >= 60 else f"处理中... {_elapsed_sec}秒"
                await _emit_progress(task_id, "ocr", 0, _detail, "")
```

注意：现在 `_cur` 和 `_tot` 在 `_monitor` 中也被引用了，需要在 `_monitor` 的 `nonlocal` 声明中去掉 `_had_output`（如果已移除），保留 `_cur`。

- [ ] **Step 4: 更新所有调用方传入 `output_pdf`**

需要更新 pipeline.py 中所有调用 `_run_ocrmypdf_with_progress` 的地方，添加 `output_pdf` 参数：

**Tesseract 调用**（约 line 1590）：
```python
_exit = await _run_ocrmypdf_with_progress(task_id, cmd, timeout=ocr_timeout, total_pages=_total_pages, output_pdf=output_pdf)
```

**EasyOCR 调用**（约 line 1635）：
```python
_exit = await _run_ocrmypdf_with_progress(task_id, cmd, timeout=ocr_timeout, total_pages=_total_pages, output_pdf=output_pdf)
```

**PaddleOCR 调用**（约 line 1675）：
```python
_exit = await _run_ocrmypdf_with_progress(task_id, cmd, env=_ocr_env, timeout=ocr_timeout, total_pages=_total_pages, output_pdf=output_pdf)
```

- [ ] **Step 5: 提交**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: file-based page counting for OCR progress monitoring"
```

---

## Self-Review

### 1. Spec coverage
- 文件轮询：✅ `_count_output_pages()` 每 5 秒读输出 PDF 页数
- 真实页面进度：✅ `_cur/_tot` 从文件页数更新，计算百分比和 ETA
- Tesseract 不受影响：✅ 文件轮询仅在 `_cur==0` 时启用（其 stderr 解析已设 `_cur > 0`）
- 心跳回退：✅ 无页数时仍显示 "处理中..."

### 2. Placeholder scan
无占位符。所有代码完整。

### 3. Type consistency
- `output_pdf` 参数在所有 3 个调用方 + 函数签名一致
- `_count_output_pages()` 返回 int
- `_cur` 和 `_tot` 在 `_monitor` 和 `_reader` 中共享访问一致
