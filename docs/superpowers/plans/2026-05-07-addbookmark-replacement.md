# addbookmark 模块替换实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用新的 addbookmark 模块（书葵网 + 晴天软件双源 + 中文命名层级推断 + 页码偏移）替换现有的书签获取和注入功能

**Architecture:** 复制 addbookmark 模块到 backend/addbookmark/，将 fitz 导入推迟到函数级（保持内存优化），inject_bookmarks 支持 exe 环境下的 subprocess 兜底，Pipeline _step_bookmark 改用 addbookmark 入口

**Tech Stack:** Python, PyMuPDF (fitz), requests, BeautifulSoup, pywinauto (晴天软件可选)

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/addbookmark/__init__.py` | 创建 | 空包标记 |
| `backend/addbookmark/bookmarkget.py` | 创建 | 书葵网抓取 + apply_bookmark_to_pdf 兼容入口 |
| `backend/addbookmark/headers.py` | 创建 | HTTP 请求头 |
| `backend/addbookmark/bookmark_parser.py` | 创建 | 中文命名规则层级推断 |
| `backend/addbookmark/bookmark_offset.py` | 创建+修改 | TOC 标签定位 + 偏移计算（fitz 懒加载） |
| `backend/addbookmark/bookmark_injector.py` | 创建+修改 | PDF 书签注入（fitz 懒加载 + subprocess 兜底） |
| `backend/addbookmark/bookmark_integrated.py` | 创建 | 双源集成入口 |
| `backend/engine/pipeline.py` | 修改 | _step_bookmark 改用 addbookmark 入口 |
| `backend/book-downloader.spec` | 修改 | 添加 addbookmark 到 datas |
| `backend/nlc/bookmarkget.py` | 修改 | 改为空壳，委托到 addbookmark |

---

### Task 1: 复制 addbookmark 核心文件到 backend

**Files:**
- Create: `D:\opencode\book-downloader\backend\addbookmark\__init__.py`
- Create: `D:\opencode\book-downloader\backend\addbookmark\bookmark_parser.py`
- Create: `D:\opencode\book-downloader\backend\addbookmark\bookmark_integrated.py`
- Create: `D:\opencode\book-downloader\backend\addbookmark\headers.py`
- Create: `D:\opencode\book-downloader\backend\addbookmark\bookmarkget.py`
- Create: `D:\opencode\book-downloader\backend\addbookmark\bookmark_offset.py`
- Create: `D:\opencode\book-downloader\backend\addbookmark\bookmark_injector.py`

- [ ] **Step 1: 创建 backend/addbookmark/ 目录和 __init__.py**

```bash
New-Item -ItemType Directory -Path "D:\opencode\book-downloader\backend\addbookmark" -Force
New-Item -ItemType File -Path "D:\opencode\book-downloader\backend\addbookmark\__init__.py" -Force
```

- [ ] **Step 2: 复制不需要修改的文件**

```bash
Copy-Item "D:\opencode\addbookmark\bookmark_parser.py" "D:\opencode\book-downloader\backend\addbookmark\bookmark_parser.py" -Force
Copy-Item "D:\opencode\addbookmark\bookmark_integrated.py" "D:\opencode\book-downloader\backend\addbookmark\bookmark_integrated.py" -Force
Copy-Item "D:\opencode\addbookmark\headers.py" "D:\opencode\book-downloader\backend\addbookmark\headers.py" -Force
Copy-Item "D:\opencode\addbookmark\bookmarkget.py" "D:\opencode\book-downloader\backend\addbookmark\bookmarkget.py" -Force
```

Wait - need to verify `bookmark_integrated.py` imports. It uses `from addbookmark.bookmarkget import _get_bookmark_sync`. Since we're placing the module in `backend/addbookmark/`, the import `from addbookmark.bookmarkget` resolves correctly when `backend/` is on the Python path (PyInstaller handles this via the datas entry). But in dev mode (running from backend/), the sys.path includes backend/, so `addbookmark` is importable.

The imports in `bookmark_integrated.py` are already correct:
```python
from addbookmark.bookmarkget import _get_bookmark_sync
from addbookmark.bookmark_parser import parse_bookmark_hierarchy
```

Similarly, `bookmarkget.py` has:
```python
from addbookmark.headers import get_shukui_headers
```

These all work as long as `backend/` is on sys.path (it is, since main.py sets it).

OK, the copy is straightforward. Proceeding to copy bookmark_offset.py and bookmark_injector.py which need modifications.

- [ ] **Step 3: 复制 bookmark_offset.py（需要修改 fitz 懒加载）**

Copy first, then modify in the next step.

```bash
Copy-Item "D:\opencode\addbookmark\bookmark_offset.py" "D:\opencode\book-downloader\backend\addbookmark\bookmark_offset.py" -Force
```

- [ ] **Step 4: 复制 bookmark_injector.py（需要修改 fitz 懒加载 + subprocess）**

```bash
Copy-Item "D:\opencode\addbookmark\bookmark_injector.py" "D:\opencode\book-downloader\backend\addbookmark\bookmark_injector.py" -Force
```

- [ ] **Step 5: 验证模块可导入**

```bash
python -c "import sys; sys.path.insert(0, 'D:\\opencode\\book-downloader\\backend'); from addbookmark.bookmark_parser import parse_bookmark_hierarchy; print('parser OK')"
python -c "import sys; sys.path.insert(0, 'D:\\opencode\\book-downloader\\backend'); from addbookmark.headers import get_shukui_headers; print('headers OK')"
python -c "import sys; sys.path.insert(0, 'D:\\opencode\\book-downloader\\backend'); from addbookmark.bookmark_integrated import BookmarkItem; print('integrated OK')"
```

Expected: All three print "OK".

Note: bookmarkget.py and bookmark_injector.py may fail at this point because they import fitz at the top level. We fix that next.

- [ ] **Step 6: 提交**

```bash
git add backend/addbookmark/
git commit -m "feat: add addbookmark module (bookmark parsing + integration)"
```

---

### Task 2: bookmark_offset.py — 将 fitz 导入推迟到函数级

**Files:**
- Modify: `D:\opencode\book-downloader\backend\addbookmark\bookmark_offset.py`

当前第 3 行有顶层 `import fitz`，导致模块导入即加载 mupdf DLL。

- [ ] **Step 1: 修改 bookmark_offset.py**

将 `import fitz` 移入各函数内部：

```python
"""Calculate page offset between 书葵网 pages and actual PDF pages."""


def find_toc_page_by_label(pdf_path: str) -> int:
    """
    Locate TOC page by page label.

    DuXiu scan naming: !00001.jpg = TOC page.
    Returns: 0-indexed physical page number, or -1 if not found.
    """
    import fitz
    doc = fitz.open(pdf_path)
    for i in range(min(30, len(doc))):
        label = doc[i].get_label()
        if label == '!00001.jpg':
            doc.close()
            return i
    doc.close()
    return -1


def detect_offset_by_label_match(
    scanned_pdf: str,
    ocr_pdf: str,
    bookmark_text: str
) -> int:
    """
    Calculate offset via OCR cross-reference using label=000001.jpg anchor.

    Formula: offset = (anchor_physical_page + 1) - anchor_shukui_page
    """
    import fitz
    scanned = fitz.open(scanned_pdf)
    ocr_doc = fitz.open(ocr_pdf)

    # Parse first bookmark entry's page number
    lines = bookmark_text.strip().split('\n')
    anchor_shukui_page = None
    for line in lines:
        parts = line.split('\t')
        if len(parts) >= 2:
            try:
                anchor_shukui_page = int(parts[1].strip())
                break
            except ValueError:
                continue

    if anchor_shukui_page is None:
        scanned.close()
        ocr_doc.close()
        return 0

    # Find label=000001.jpg in scanned PDF
    stacks_anchor_page = None
    for i in range(len(scanned)):
        if scanned[i].get_label() == '000001.jpg':
            stacks_anchor_page = i
            break

    if stacks_anchor_page is None:
        scanned.close()
        ocr_doc.close()
        return 0

    offset = (stacks_anchor_page + 1) - anchor_shukui_page

    scanned.close()
    ocr_doc.close()
    return offset
```

- [ ] **Step 2: 验证导入不触发 fitz 加载**

```bash
python -c "import sys; sys.path.insert(0, 'D:\\opencode\\book-downloader\\backend'); from addbookmark.bookmark_offset import find_toc_page_by_label; print('import OK (no fitz load)')"
```

Expected: `import OK (no fitz load)` — 不会报 fitz 找不到的错误。

- [ ] **Step 3: 提交**

```bash
git add backend/addbookmark/bookmark_offset.py
git commit -m "fix: lazy-load fitz in bookmark_offset.py to avoid DLL preload"
```

---

### Task 3: bookmark_injector.py — fitz 懒加载 + subprocess 兜底

**Files:**
- Modify: `D:\opencode\book-downloader\backend\addbookmark\bookmark_injector.py`

当前第 3-5 行有顶层 `import fitz` 和 `from addbookmark.bookmark_parser import ...`。后者不需要改，前者需要懒加载。同时 `find_toc_page_by_label` 也会触发 fitz 加载，所以整个 `inject_bookmarks` 函数需要重构。

- [ ] **Step 1: 重写 bookmark_injector.py**

主进程做书签解析（纯 Python）→ 子进程做 PDF 操作（fitz）。子进程脚本完全自包含，不依赖 addbookmark 模块。

```python
"""Inject hierarchical bookmarks into PDF via PyMuPDF."""
import json
import os
import subprocess as _sp
import sys


def inject_bookmarks(
    pdf_path: str,
    bookmark_text: str,
    output_path: str,
    offset: int = 0,
) -> str:
    """
    Inject bookmarks into PDF.

    Args:
        pdf_path: Input PDF path.
        bookmark_text: 书葵网/晴天软件 raw bookmark text.
        output_path: Output PDF path.
        offset: Page offset (shukui_page + offset = PDF_viewer_page).

    Returns:
        Output file path.
    """
    from addbookmark.bookmark_parser import parse_bookmark_hierarchy

    outlines = parse_bookmark_hierarchy(bookmark_text)
    if not outlines:
        return output_path

    # Try direct fitz first (dev/venv with fitz installed)
    try:
        import fitz as _f

        doc = _f.open(pdf_path)
        total = len(doc)

        from addbookmark.bookmark_offset import find_toc_page_by_label
        toc_page = find_toc_page_by_label(pdf_path)

        toc_entries = []
        if toc_page >= 0:
            toc_entries.append([1, '目 录', toc_page + 1])

        for title, shukui_page, level in outlines:
            page_num = shukui_page + offset
            page_num = max(1, min(page_num, total))
            toc_entries.append([level, title, page_num])

        doc.set_toc(toc_entries)
        doc.save(output_path)
        doc.close()
        return output_path

    except ImportError:
        pass

    # Subprocess fallback (exe environment where fitz is not bundled)
    python_cmd = _find_system_python()
    if not python_cmd:
        raise RuntimeError("bookmark_injector: no system Python available for fitz subprocess")

    # Pre-compute outline data: [(title, shukui_page, level), ...]
    items = [[title, shukui_page, level] for title, shukui_page, level in outlines]

    # Self-contained subprocess script (no addbookmark dependency)
    script = (
        "import json,sys;"
        "data=json.loads(sys.stdin.read());"
        "import fitz;"
        "doc=fitz.open(data['pdf']);"
        "total=len(doc);"
        "toc_page=-1;"
        "for i in range(min(30,total)):"
        " if doc[i].get_label()=='!00001.jpg':"
        "  toc_page=i;break;"
        "entries=[];"
        "if toc_page>=0: entries.append([1,'\u76ee \u5f55',toc_page+1]);"
        "for t,p,l in data['items']:"
        " pn=max(1,min(p+data['offset'],total));"
        " entries.append([l,t,pn]);"
        "doc.set_toc(entries);"
        "doc.save(data['out'],incremental=False);"
        "doc.close();"
        "print('OK')"
    )
    r = _sp.run(
        [python_cmd, "-c", script],
        input=json.dumps({
            "pdf": pdf_path, "items": items,
            "offset": offset, "out": output_path,
        }),
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError(f"bookmark inject subprocess failed (rc={r.returncode}): {r.stderr[:300]}")
    return output_path


def _find_system_python():
    """Find system Python executable (skip frozen exe)."""
    if getattr(sys, 'frozen', False):
        exe = sys.executable
        import shutil as _sh
        for cmd in ["python", "python3", "py"]:
            found = _sh.which(cmd)
            if found and os.path.abspath(found) != os.path.abspath(exe):
                return found
        return None
    return sys.executable
```

- [ ] **Step 2: 验证导出（不触发 fitz）**

```bash
python -c "import sys; sys.path.insert(0, 'D:\\opencode\\book-downloader\\backend'); from addbookmark.bookmark_injector import inject_bookmarks; print('import OK')"
```

Expected: `import OK`

- [ ] **Step 3: 提交**

```bash
git add backend/addbookmark/bookmark_injector.py
git commit -m "feat: add subprocess fallback to bookmark_injector, lazy-load fitz"
```

---

### Task 4: 更新 Pipeline _step_bookmark

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pipeline.py:1860-1911`

替换现有的 `_step_bookmark` 函数。

- [ ] **Step 1: 读取当前 _step_bookmark 函数范围**

函数在 `pipeline.py` 第 1860 到 1911 行。确认边界：

```bash
python -c "with open(r'D:\opencode\book-downloader\backend\engine\pipeline.py','r',encoding='utf-8') as f: lines=f.readlines(); print([i+1 for i,l in enumerate(lines) if 'async def _step_bookmark' in l or 'async def _step_finalize' in l])"
```

Expected: `[1860, 1914]` 或类似行号。

- [ ] **Step 2: 替换 _step_bookmark 函数体**

将第 1860 到 1911 行替换为新实现。oldString 是现有的整个 `_step_bookmark` 函数：

```python
async def _step_bookmark(task_id: str, task: Dict[str, Any], config: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    task_store.add_log(task_id, "Step 6/7: Processing bookmarks/TOC...")
    await _emit(task_id, "step_progress", {"step": "bookmark", "progress": 0})

    bookmark = task.get("bookmark", "")
    pdf_path = report.get("pdf_path", "")

    if not bookmark:
        task_store.add_log(task_id, "No bookmark provided, trying shukui.net (by ISBN)...")
        try:
            from addbookmark.bookmarkget import get_bookmark
            isbn = report.get("isbn", "")
            if isbn:
                bookmark = await get_bookmark(isbn)
                if bookmark:
                    task_store.add_log(task_id, "Bookmark fetched from shukui.net")
                    report["bookmark"] = bookmark
                else:
                    task_store.add_log(task_id, "Bookmark not found on shukui.net")
            else:
                task_store.add_log(task_id, "No ISBN available for bookmark lookup")
        except ImportError:
            task_store.add_log(task_id, "Bookmark module not available")
        except Exception as e:
            task_store.add_log(task_id, f"Bookmark fetch error: {e}")

    if bookmark and pdf_path and os.path.exists(pdf_path):
        task_store.add_log(task_id, "Applying bookmark to PDF...")
        try:
            from addbookmark.bookmark_injector import inject_bookmarks
            inject_bookmarks(pdf_path, bookmark, pdf_path, offset=0)
            task_store.add_log(task_id, "Bookmark applied to PDF")
            report["bookmark_applied"] = True
        except ImportError:
            task_store.add_log(task_id, "Bookmark PDF module not available")
        except Exception as e:
            task_store.add_log(task_id, f"Bookmark apply error: {e}")

    await _emit(task_id, "step_progress", {"step": "bookmark", "progress": 100})
    return report
```

- [ ] **Step 3: 验证 Python 语法**

```bash
python -c "import py_compile; py_compile.compile(r'D:\opencode\book-downloader\backend\engine\pipeline.py', doraise=True); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 4: 提交**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: use addbookmark module for bookmark step in pipeline"
```

---

### Task 5: 更新 PyInstaller spec 文件

**Files:**
- Modify: `D:\opencode\book-downloader\backend\book-downloader.spec`

需要将 addbookmark 目录添加到 datas，不用添加到 hiddenimports（因为 pipe 中已经用 import 路径触发 PyInstaller 分析）。

- [ ] **Step 1: 添加 addbookmark 到 spec 的 datas**

在 spec 文件中找到 `datas=[` 部分，添加 addbookmark 目录条目。在现有的 NLC_DIR 行之后插入：

```python
ADD_BOOKMARK_DIR = BACKEND_DIR / "addbookmark"

a = Analysis(
    [str(BACKEND_DIR / "main.py")],
    pathex=[str(BACKEND_DIR)],
    binaries=[],
    datas=[
        (str(FRONTEND_DIST), "frontend/dist"),
        (str(NLC_DIR / "nlc_isbn.py"), "nlc/nlc_isbn.py"),
        (str(NLC_DIR / "bookmarkget.py"), "nlc/bookmarkget.py"),
        (str(NLC_DIR / "headers.py"), "nlc/headers.py"),
        (str(NLC_DIR / "formatting.py"), "nlc/formatting.py"),
        (str(BACKEND_DIR / "addbookmark"), "addbookmark"),    # NEW
        (str(BACKEND_DIR / "engine"), "engine"),
        (str(BACKEND_DIR / "api"), "api"),
        # ... rest unchanged
    ],
```

- [ ] **Step 2: 提交**

```bash
git add backend/book-downloader.spec
git commit -m "build: include addbookmark module in PyInstaller bundle"
```

---

### Task 6: 构建并部署

- [ ] **Step 1: 构建前端**

```bash
cmd /c "npm run build" 2>&1
```

Workdir: `D:\opencode\book-downloader\frontend`
Expected: `built in X.XXs`

- [ ] **Step 2: 构建 exe**

```bash
python -m PyInstaller --noconfirm "D:\opencode\book-downloader\backend\book-downloader.spec" 2>&1 | Select-Object -Last 5
```

Workdir: `D:\opencode\book-downloader`
Expected: `Build complete!`

- [ ] **Step 3: 部署 exe**

```bash
Copy-Item "D:\opencode\book-downloader\dist\BookDownloader.exe" "D:\opencode\book-downloader\backend\dist\BookDownloader.exe" -Force
```

- [ ] **Step 4: 验证 exe 可启动**

启动 `D:\opencode\book-downloader\backend\dist\BookDownloader.exe`，确认：
- 控制台无 `ImportError` 
- http://127.0.0.1:8000 可访问

- [ ] **Step 5: 提交**

```bash
git add backend/dist/BookDownloader.exe
git commit -m "build: deploy BookDownloader.exe with addbookmark module"
```

---

### Task 7: 端到端测试

- [ ] **Step 1: 测试书葵网书签获取**

```bash
python -c "import sys; sys.path.insert(0, r'D:\opencode\book-downloader\backend'); from addbookmark.bookmarkget import _get_bookmark_sync; result = _get_bookmark_sync('9787561789322'); print('OK' if result else 'FAIL'); print(result[:200] if result else '')"
```

用 ISBN 9787561789322（何为女性）测试。Expected: 返回书签文本，如 `"第一章  何为女性？...\t1\n导言\t3\n..."`

- [ ] **Step 2: 测试书签层级解析**

```bash
python -c "import sys; sys.path.insert(0, r'D:\opencode\book-downloader\backend'); from addbookmark.bookmark_parser import parse_bookmark_hierarchy; from addbookmark.bookmarkget import _get_bookmark_sync; text = _get_bookmark_sync('9787561789322'); result = parse_bookmark_hierarchy(text); print(f'{len(result)} items:'); [print(f'  L{r[2]} | {r[0][:30]} -> p.{r[1]}') for r in result[:10]]"
```

Expected: 输出层级书签列表，如：
```
XX items:
  L1 | 第一章  何为女性？... -> p.1
  L2 | 导言 -> p.3
  L3 | 第一节  生理学和社会规范 -> p.8
  ...
```

- [ ] **Step 3: 测试完整 pipeline（通过 API）**

确保 exe 正在运行，然后通过 API 创建并启动任务：

```bash
# 创建任务
curl -s -X POST http://127.0.0.1:8000/api/v1/search -H "Content-Type: application/json" -d "{\"book_id\": \"2590784\"}"
```

从返回中获取 `task_id`，然后：

```bash
# 启动任务
curl -s -X POST http://127.0.0.1:8000/api/v1/tasks/{task_id}/start
```

- [ ] **Step 4: 监控任务进度**

观察日志中 Step 6 的输出：
```
[HH:MM:SS] Step 6/7: Processing bookmarks/TOC...
[HH:MM:SS] Bookmark fetched from shukui.net
[HH:MM:SS] Applying bookmark to PDF...
[HH:MM:SS] Bookmark applied to PDF
```

- [ ] **Step 5: 验证输出 PDF 包含书签**

```bash
python -c "import fitz; doc=fitz.open(r'D:\pdf\BookDownloader\download\12928975_何为女性.pdf'); toc=doc.get_toc(); print(f'{len(toc)} bookmarks:'); [print(f'  L{t[0]} | {t[1][:40]} -> p.{t[2]}') for t in toc[:15]]; doc.close()"
```

Expected: 输出 PDF 包含书签条目，`set_toc` 格式 `[level, title, page]`。

- [ ] **Step 6: 提交**

```bash
git commit --allow-empty -m "test: verify addbookmark end-to-end pipeline works"
```
