# Smart Bookmark — Direct AI Vision TOC Injection

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "智能书签" button in settings page (next to 保存设置/检查更新) that opens a file picker, selects a PDF, and directly runs AI Vision TOC extraction + injection without any pipeline steps.

**Architecture:** Backend endpoint `POST /api/v1/toc/apply` takes a PDF path, runs `generate_toc()` via configured Vision LLM, then `inject_bookmarks()` into the original PDF. Frontend button calls Electron file dialog API, passes path to backend, shows progress/result.

**Tech Stack:** React, FastAPI, existing `ai_vision_toc.py`, `bookmark_injector.py`

---

## File Structure

| File | Role |
|---|---|
| `backend/api/toc.py` | New endpoint `POST /apply` — TOC extract + inject |
| `frontend/src/components/ConfigSettings.tsx:2509-2526` | Add "智能书签" button |

---

### Task 1: Backend — POST /api/v1/toc/apply

**Files:**
- Modify: `D:\opencode\book-downloader\backend\api\toc.py`

- [ ] **Step 1: Add the endpoint**

Read `D:\opencode\book-downloader\backend\api\toc.py`. Add this at the end of the file:

```python
class ApplyRequest(BaseModel):
    pdf_path: str

@router.post("/apply")
async def apply_bookmark(req: ApplyRequest):
    """Directly run AI Vision TOC extraction and inject into PDF."""
    from config import get_config
    cfg = get_config()

    if not os.path.exists(req.pdf_path):
        raise HTTPException(404, "PDF not found")

    # Run generate_toc with current AI Vision config
    bookmark = ""
    source = ""
    try:
        from addbookmark.ai_vision_toc import generate_toc
        bookmark, source = await generate_toc(req.pdf_path, cfg)
    except Exception as e:
        return {"ok": False, "message": f"TOC extraction failed: {str(e)[:200]}"}

    if not bookmark:
        return {"ok": False, "message": "未能提取到目录内容"}

    # Inject into PDF
    try:
        from addbookmark.bookmark_injector import inject_bookmarks
        inject_bookmarks(req.pdf_path, bookmark, req.pdf_path, offset=0)
    except Exception as e:
        return {"ok": False, "message": f"书签注入失败: {str(e)[:200]}"}

    return {"ok": True, "message": f"成功添加 {len(bookmark.split(chr(10)))} 条书签", "source": source}
```

- [ ] **Step 2: Verify syntax**

```bash
python -m py_compile backend\api\toc.py
```

- [ ] **Step 3: Commit**

```bash
git add backend/api/toc.py
git commit -m "feat: POST /api/v1/toc/apply — direct AI Vision TOC extraction + injection"
```

---

### Task 2: Frontend — "智能书签" button

**Files:**
- Modify: `D:\opencode\book-downloader\frontend\src\components\ConfigSettings.tsx:2510-2526`

- [ ] **Step 1: Add state and handler**

Find the state declarations near the top of ConfigSettings (around line 350-400). Add:

```typescript
  const [bookmarking, setBookmarking] = useState(false)
  const [bookmarkMsg, setBookmarkMsg] = useState('')
```

- [ ] **Step 2: Add button next to "保存设置" and "检查更新"**

Find the button group at lines 2510-2526. Add the new button after "检查更新":

```tsx
        <button
          type="button"
          onClick={async () => {
            setBookmarking(true)
            setBookmarkMsg('')
            try {
              // Open file dialog via backend
              const res = await fetch('/api/v1/select-file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filters: [{ name: 'PDF', extensions: ['pdf'] }] }),
              })
              const data = await res.json()
              if (!data.path) { setBookmarkMsg('未选择文件'); return }

              setBookmarkMsg('正在识别目录...')
              const r2 = await fetch('/api/v1/toc/apply', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pdf_path: data.path }),
              })
              const d2 = await r2.json()
              setBookmarkMsg(d2.message || (d2.ok ? '完成' : '失败'))
            } catch (e) {
              setBookmarkMsg(String(e))
            }
            setBookmarking(false)
          }}
          disabled={bookmarking}
          className="px-5 py-2 text-sm rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 font-medium"
        >
          {bookmarking ? '处理中...' : '智能书签'}
        </button>
        {bookmarkMsg && (
          <span className={`text-xs ${bookmarkMsg.includes('成功') ? 'text-green-600' : 'text-red-500'}`}>
            {bookmarkMsg}
          </span>
        )}
```

- [ ] **Step 3: Build frontend**

```bash
cd D:\opencode\book-downloader\frontend
npm run build
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/ConfigSettings.tsx
git commit -m "feat: 智能书签 button — direct AI Vision TOC injection from file picker"
```

---

### Self-Review

**1. Spec coverage:**
- File picker → `/api/v1/select-file` with PDF filter
- AI Vision TOC → `generate_toc()` with current config
- Inject → `inject_bookmarks()` into original PDF
- Button placement → next to 保存设置/检查更新

**2. Placeholder scan:** No TBD/TODO.

**3. Type consistency:**
- `ApplyRequest.pdf_path: str` → sent from frontend file picker result
- `generate_toc` returns `Tuple[str, str]` → destructured correctly
- `inject_bookmarks` takes `(pdf_path, bookmark, pdf_path, offset)` → same file
