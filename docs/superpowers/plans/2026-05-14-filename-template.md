# File Rename Template + Settings Reorganization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add template-based file renaming on pipeline completion using metadata fields (title/author/publisher/ISBN etc.), with a settings UI for template input and live preview. Reorganize settings: split "下载与来源" into "下载" and "来源", move BW compression to OCR section.

**Architecture:** New `filename_template` config key stores a template string with `{field}` placeholders. At Step 7 finalize, `_apply_filename_template(report, config)` replaces placeholders with sanitized metadata values and renames the PDF file. Settings UI adds template input + preview panel showing a sample output. Layout restructuring is purely CSS/JSX reorganization — no API changes.

**Tech Stack:** Python/FastAPI (backend rename), React/TypeScript/Tailwind (frontend UI)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/config.py` | Modify | Add `filename_template` default + `_apply_filename_template` helper |
| `backend/engine/pipeline.py` | Modify | Step 7 finalize: apply rename template before/after moving to finished_dir |
| `frontend/src/components/ConfigSettings.tsx` | Modify | Reorganize sections, add template input + preview |
| `frontend/src/types.ts` | Modify | Add `filename_template` to AppConfig + TaskReport |

---

### Task 1: Backend — File rename template engine

**Files:**
- Create: `backend/engine/filename_template.py`
- Modify: `backend/config.py`

Add a template engine that takes a pattern like `{title}_{author}_{isbn}` and a metadata dict, returns a sanitized filename.

- [ ] **Step 1: Create `filename_template.py`**

```python
"""Filename template engine — {field} placeholder substitution."""

import re
import unicodedata
from typing import Dict

_FIELD_MAP = {
    "title": "title",
    "author": "authors",
    "authors": "authors",
    "publisher": "publisher",
    "isbn": "isbn",
    "ss_code": "ss_code",
    "source": "download_source",
    "download_source": "download_source",
    "year": "year",
    "book_id": "book_id",
}

def _sanitize(s: str, max_len: int = 80) -> str:
    """Remove path-unsafe characters, limit length."""
    s = unicodedata.normalize("NFKC", str(s))
    s = re.sub(r'[<>:"/\\|?*]', '_', s)
    s = re.sub(r'\s+', ' ', s).strip()
    if len(s) > max_len:
        s = s[:max_len].rsplit(' ', 1)[0]
    return s or "untitled"

def apply_template(template: str, metadata: Dict) -> str:
    """Replace {field} placeholders with sanitized metadata values."""
    if not template or "{" not in template:
        return None
    result = template
    for key, meta_key in _FIELD_MAP.items():
        val = metadata.get(meta_key, "")
        if isinstance(val, list):
            val = val[0] if val else ""
        val = _sanitize(str(val))
        if val:
            result = result.replace("{" + key + "}", val)
    # Remove remaining unmatched placeholders
    result = re.sub(r'\{[^}]+\}', '', result).strip()
    if not result:
        return None
    if not result.lower().endswith('.pdf'):
        result += '.pdf'
    return result
```

- [ ] **Step 2: Add `filename_template` default to `config.py`**

In `D:\opencode\book-downloader\backend\config.py`, add to the `DEFAULT_CONFIG` dict (around line where existing defaults are defined):

```python
"filename_template": "{title}",
```

- [ ] **Step 3: Verify template engine**

Create a quick test:
```python
from engine.filename_template import apply_template
r = apply_template("{title}_{author}", {"title": "至高的清贫", "authors": ["Giorgio Agamben"]})
print(r)  # Expected: 至高的清贫_Giorgio Agamben.pdf
```

- [ ] **Step 4: Commit**

```bash
git add backend/engine/filename_template.py backend/config.py
git commit -m "feat: add filename template engine with {field} placeholders"
```

---

### Task 2: Apply template in pipeline Step 7 (finalize)

**Files:**
- Modify: `backend/engine/pipeline.py` (Step 7: _step_finalize)

Wrap the existing file move in `_step_finalize` to apply the filename template. The rename must happen BEFORE the file is moved to `finished_dir`, and `report["pdf_path"]` must be updated.

- [ ] **Step 1: Read the current _step_finalize code**

Read lines 3019-3090 to understand the current flow: copy to target_dir, handle OCR originals, cleanup tmp.

- [ ] **Step 2: Add template logic before the file move**

Insert after the `pdf_path` check and before the move-to-target_dir block:

```python
    # ── Apply filename template ──
    template = config.get("filename_template", "").strip()
    if template and "{" in template:
        try:
            from engine.filename_template import apply_template
            new_name = apply_template(template, report)
            if new_name:
                new_path = os.path.join(os.path.dirname(pdf_path), new_name)
                if os.path.abspath(new_path) != os.path.abspath(pdf_path):
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    os.rename(pdf_path, new_path)
                    pdf_path = new_path
                    report["pdf_path"] = pdf_path
                    task_store.add_log(task_id, f"File renamed: {os.path.basename(pdf_path)}")
        except Exception as e:
            task_store.add_log(task_id, f"File rename failed: {e}")
```

- [ ] **Step 3: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: apply filename template in pipeline Step 7"
```

---

### Task 3: Settings reorganization + template UI

**Files:**
- Modify: `frontend/src/components/ConfigSettings.tsx`
- Modify: `frontend/src/types.ts`

Three changes in ConfigSettings.tsx:
1. Split "下载与来源" (expanded.download) into two sections: "下载" and "来源"
2. Move BW compression (pdf_compress, pdf_compress_half) to OCR section
3. Add filename template input + preview in the new "下载" section

- [ ] **Step 1: Add `filename_template` to types.ts**

In `D:\opencode\book-downloader\frontend\src\types.ts`, add to `AppConfig`:
```ts
filename_template: string
```

In `DEFAULT_CONFIG` in ConfigSettings.tsx (find where default is defined), add:
```ts
filename_template: '{title}',
```

- [ ] **Step 2: Rename and split sections**

In the `expanded` state (around line 363), change:
```tsx
const [expanded, setExpanded] = useState<Record<string, boolean>>({
    database: false,
    download: false,  // was "下载与来源"
    proxy: false,      // was "网络代理"
    ocr: false,
    bookmarks: false,
})
```

Add `sources: false` and `download: true` (default expanded for download).

- [ ] **Step 3: Create new "下载" section**

Move these items from the old download section into a new section at `expanded.download`:
- `download_dir` — 下载目录
- `finished_dir` — 完成目录  
- **NEW**: filename template input + preview panel

```tsx
{/* 文件名模板 */}
<div>
  <label className="text-xs font-medium text-gray-600 block mb-1">文件名模板</label>
  <input type="text" value={form.filename_template || '{title}'}
    onChange={(e) => updateForm({ filename_template: e.target.value })}
    className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
  <p className="text-[10px] text-gray-400 mt-1">
    可用字段: {'{title}'}, {'{author}'}, {'{publisher}'}, {'{isbn}'}, {'{ss_code}'}, {'{source}'}, {'{year}'}
  </p>
  {/* Live preview */}
  {form.filename_template && form.filename_template.includes('{') && (
    <div className="mt-2 p-2 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded">
      <p className="text-[10px] text-gray-500 mb-1">预览（基于当前默认值）:</p>
      <p className="text-xs font-mono text-gray-700 dark:text-gray-300">
        {form.filename_template
          .replace('{title}', '至高的清贫')
          .replace('{author}', '作者名')
          .replace('{publisher}', '出版社')
          .replace('{isbn}', '9787XXXXXXXX')
          .replace('{ss_code}', 'SS12345678')
          .replace('{source}', 'zlibrary')
          .replace('{year}', '2024')
        }.pdf
      </p>
    </div>
  )}
</div>
```

- [ ] **Step 4: Create new "来源" section**

Move these items into `expanded.sources`:
- Z-Library (email, password, login)
- Stacks (base_url, api_key, username, password)
- FlareSolverr (port, install guide)
- `aa_membership_key`

- [ ] **Step 5: Move BW compression to OCR section**

Move `pdf_compress` and `pdf_compress_half` from old download section to the OCR section, right before `ocr_confirm_enabled`:

```tsx
{/* PDF 黑白二值化压缩 */}
<div className="border-t border-gray-200 dark:border-gray-700 pt-3 mt-3">
  <label className="text-xs font-medium text-gray-600 block mb-1">PDF 压缩（OCR 后执行）</label>
  <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
    <input type="checkbox" checked={form.pdf_compress || false}
      onChange={(e) => updateForm({ pdf_compress: e.target.checked })}
      className="rounded" />
    启用 PDF 黑白二值化压缩
  </label>
  {form.pdf_compress && (
    <div className="ml-5 mt-1 space-y-0.5">
      <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer">
        <input type="radio" name="compress_res" checked={!form.pdf_compress_half}
          onChange={() => updateForm({ pdf_compress_half: false })} />
        全分辨率（~300 DPI，文件更大）
      </label>
      <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer">
        <input type="radio" name="compress_res" checked={!!form.pdf_compress_half}
          onChange={() => updateForm({ pdf_compress_half: true })} />
        半分辨率（~150 DPI，文件更小）
      </label>
    </div>
  )}
</div>
```

- [ ] **Step 6: Build frontend**

```bash
cmd /c "cd /d D:\opencode\book-downloader\frontend && npm run build"
```

Expected: 0 TS errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ConfigSettings.tsx frontend/src/types.ts
git commit -m "feat: file rename template UI + settings reorganization"
```

---

### Task 4: Rebuild and smoke test

- [ ] **Step 1: Rebuild exe**

```bash
cd backend
python -m PyInstaller --noconfirm book-downloader.spec
```

- [ ] **Step 2: Smoke test**

1. Open Settings → "下载" section → verify download_dir, finished_dir, filename template
2. Enter template `{title}_{author}` → preview shows "至高的清贫_作者名.pdf"
3. Check "来源" section → ZL/Stacks/FlareSolverr all present
4. Check "OCR" section → BW compression moved here
5. Run a pipeline task → verify output file is renamed per template

- [ ] **Step 3: Done**

---

## Self-Review

### Spec Coverage
- [x] Metadata-based file renaming → Task 1 (template engine) + Task 2 (pipeline apply)
- [x] Template preview → Task 3 Step 3 (live preview with sample values)
- [x] All metadata fields → `_FIELD_MAP` in Task 1 covers all 9 renameable fields
- [x] Settings: "下载" separated — download_dir + finished_dir + template → Task 3 Step 3
- [x] Settings: "来源" separated — ZL/Stacks/FlareSolverr → Task 3 Step 4
- [x] BW compression moved to OCR → Task 3 Step 5
- [x] Don't break existing pipeline calls — Task 2 updates `report["pdf_path"]` after rename

### Placeholder Scan
No TODOs, TBDs, or placeholders.

### Type Consistency
- `filename_template: string` in `AppConfig` matches `config.get("filename_template", "")` in pipeline
- Template fields in `_FIELD_MAP` match metadata keys in `report` dict
- Preview sample values match field names shown in help text
