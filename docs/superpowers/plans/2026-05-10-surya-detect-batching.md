# Surya 版面检测分批次 — 降内存 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surya 版面检测从一次性传入全部页面改为分批次（每批 20 页），将峰值内存从 ~10GB 降至 ~2-3GB。

**Architecture:** 在 `OCRPipeline.run()` 的 detect 阶段循环分批调用 `get_detected_boxes_batch`，每批 20 页，逐批拼接结果。新增 `--detect-batch-size` CLI 参数（默认 20），环境变量 `OCR_DETECT_BATCH_SIZE` 备选。

**Tech Stack:** Python asyncio, Surya DetectionPredictor, PIL

---

### File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `local-llm-pdf-ocr/src/pdf_ocr/pipeline.py` | 修改 | 分批循环替代单次全量调用 |
| `local-llm-pdf-ocr/src/pdf_ocr/cli.py` | 修改 | 添加 `--detect-batch-size` CLI 参数 |

---

### Task 1: pipeline.py — 分批检测循环

**Files:**
- Modify: `local-llm-pdf-ocr/src/pdf_ocr/pipeline.py:151-160`

- [ ] **Step 1: 添加 `os` import**

在文件顶部 import 区域（约 `import asyncio` 之后），确认或添加：

```python
import os
```

- [ ] **Step 2: 替换 detect 阶段的单次全量批处理**

读取 `pipeline.py` 第 151-160 行。当前代码将全部页面的图片一次性传给 `get_detected_boxes_batch`。替换为分批循环：

```python
        # --- Phase 1: batch layout detection ---
        await _notify(progress, "detect", 0, 1, f"Detecting layout for {len(page_nums)} pages...")
        image_bytes = [base64.b64decode(images_dict[p]) for p in page_nums]

        # Batch detection to limit peak memory (Surya on CPU can use 7+ GB)
        _detect_batch_size = int(os.environ.get("OCR_DETECT_BATCH_SIZE", 20))
        batch_boxes = []
        for _i in range(0, len(image_bytes), _detect_batch_size):
            _batch = image_bytes[_i:_i + _detect_batch_size]
            _batch_result = await asyncio.to_thread(
                self.aligner.get_detected_boxes_batch, _batch
            )
            batch_boxes.extend(_batch_result)
            _done = _i + len(_batch)
            if progress:
                await progress("detect", _done, len(image_bytes),
                               f"Detecting layout ({_done}/{len(image_bytes)})")

        pages_structured: dict[int, list] = {
            p: [(box, "") for box in batch_boxes[i]] for i, p in enumerate(page_nums)
        }
        await _notify(progress, "detect", 1, 1, "Layout detection complete.")
```

- [ ] **Step 3: 验证语法**

```powershell
cd D:\opencode\book-downloader\local-llm-pdf-ocr
python -c "import py_compile; py_compile.compile('src/pdf_ocr/pipeline.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 提交**

```powershell
cd D:\opencode\book-downloader\local-llm-pdf-ocr
git add src/pdf_ocr/pipeline.py
git commit -m "feat: batch Surya detection in groups of 20 pages to cap peak memory"
```

---

### Task 2: cli.py — 添加 `--detect-batch-size` CLI 参数

**Files:**
- Modify: `local-llm-pdf-ocr/src/pdf_ocr/cli.py`

- [ ] **Step 1: 添加 CLI 参数**

读取 `cli.py` 找到 `build_parser()` 或 `add_argument` 区域。在 `--dense-threshold` 参数附近添加：

```python
    parser.add_argument(
        "--detect-batch-size",
        type=int,
        default=20,
        help="Pages per Surya detection batch. Lower = less RAM; "
             "higher = faster but more memory (default: 20). "
             "Also settable via env OCR_DETECT_BATCH_SIZE.",
    )
```

- [ ] **Step 2: 在 run() 函数中传递到环境变量**

找到 `run()` 函数。在调用 `pipeline.run()` 之前（约 line 181），添加：

```python
        # Forward detect-batch-size to Pipeline via env (avoids signature change)
        if hasattr(args, 'detect_batch_size') and args.detect_batch_size:
            os.environ["OCR_DETECT_BATCH_SIZE"] = str(args.detect_batch_size)

        try:
            await pipeline.run(...)
```

- [ ] **Step 3: 验证语法**

```powershell
cd D:\opencode\book-downloader\local-llm-pdf-ocr
python -c "import py_compile; py_compile.compile('src/pdf_ocr/cli.py', doraise=True); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 验证 `--detect-batch-size` 参数可见**

```powershell
cd D:\opencode\book-downloader\local-llm-pdf-ocr
uv run local-llm-pdf-ocr --help | findstr "detect-batch-size"
```

Expected: 显示参数说明。

- [ ] **Step 5: 提交**

```powershell
cd D:\opencode\book-downloader\local-llm-pdf-ocr
git add src/pdf_ocr/cli.py
git commit -m "feat: add --detect-batch-size CLI arg to control Surya detection batch size"
```

---

## Summary

| Task | 文件 | 内容 |
|------|------|------|
| 1 | `pipeline.py` | 分批循环替代一次性全量检测，默认 20 页/批 |
| 2 | `cli.py` | `--detect-batch-size` 参数 + 环境变量传递 |
