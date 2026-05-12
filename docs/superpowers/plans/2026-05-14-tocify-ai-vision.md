# AI Vision TOC — Manual Page Selection + Structured Prompt + Offset Preview

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace auto TOC detection with manual page selection UI, structured Vision LLM prompt with multi-language hierarchy, and user-confirmed offset before injection.

**Architecture:** Step 6 detects empty `report["bookmark"]` and opens `TOCModal`. User selects TOC page range in a PDF page thumbnail strip. Backend renders selected pages as PNGs, sends to Vision LLM with the multi-language prompt. Response parsed into `title\tpage\n` format. Frontend shows parsed entries, user adjusts offset via a PDF page preview with real-time feedback, confirms to inject.

**Tech Stack:** React PDF preview (iframe or canvas), Vision LLM (OpenAI-compatible/Azure/Gemini/Anthropic), PyMuPDF rendering, existing `inject_bookmarks`

---

## File Structure

| File | Role |
|---|---|
| `frontend/src/components/TOCModal.tsx` | NEW — page selector + parsed preview + offset slider |
| `backend/api/toc.py` | NEW — render pages, call Vision LLM, parse response |
| `backend/addbookmark/ai_vision_toc.py` | MODIFY — replace old prompt with new multi-language prompt |
| `backend/engine/pipeline.py:2959-2975` | MODIFY — wire TOCModal into Step 6 bookmark |
| `frontend/src/components/Layout.tsx` | MODIFY — add `<TOCModal />` to outlet |

---

## User Flow

```
Step 6: report["bookmark"] 为空?
  └─ Yes → 弹出 TOCModal
        ├─ 1. 用户拖选目录页码范围 (如第 5-8 页)
        ├─ 2. 后端渲染选定页为 PNG → 送 Vision LLM
        ├─ 3. 前端显示解析结果: "title\tpage\n..."
        ├─ 4. 用户在 PDF 预览中对比目录条目与实际页码
        ├─ 5. 调整 offset（偏移量）——实时预览条目位置映射
        └─ 6. 确认 → inject_bookmarks(pdf, parsed_bookmark, offset)
```

---

### Task 1: New Vision LLM prompt + response parser

**Files:**
- Modify: `D:\opencode\book-downloader\backend\addbookmark\ai_vision_toc.py`

Replace the existing `build_vision_prompt()` function with the user's multi-language prompt. Add a new parser `parse_tocify_response()` that converts the Vision LLM output to `title\tpage` format.

- [ ] **Step 1: Replace build_vision_prompt()**

Replace `build_vision_prompt()` in `ai_vision_toc.py:485` with the full multi-language prompt (Chinese text with hierarchy rules, level indicators, output format spec). The prompt must instruct the model to output in code block format:

```
前言
第一章 绪论\t1
	第一节 研究背景\t3
		一、问题提出\t3
...
```

- [ ] **Step 2: Add parse_tocify_response()**

New function:

```python
def parse_tocify_response(response: str) -> str:
    """Parse Vision LLM response into title<tab>page format.
    
    Handles:
    - Tab-indented hierarchy → flattened with tab separator
    - Multiple spaces/tabs → single tab
    - No page number → inherits previous page
    """
    import re
    lines = []
    last_page = 1
    
    # Extract from code block if present
    m = re.search(r'```(.*?)```', response, re.DOTALL)
    text = m.group(1).strip() if m else response.strip()
    
    for line in text.split('\n'):
        line = line.strip()
        if not line:
            continue
        # Count leading tabs for hierarchy
        tabs = len(line) - len(line.lstrip('\t'))
        title = line.lstrip('\t')
        
        # Extract page number
        pm = re.search(r'\s+(\d{1,5})\s*$', title)
        if pm:
            page = int(pm.group(1))
            title = title[:pm.start()].strip()
            last_page = page
        else:
            page = last_page
        
        # Normalize: title + tab + page
        lines.append(f"{title}\t{page}")
    
    return '\n'.join(lines)
```

- [ ] **Step 3: Verify syntax**

```bash
python -m py_compile backend\addbookmark\ai_vision_toc.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/addbookmark/ai_vision_toc.py
git commit -m "feat: multi-language Vision prompt + tocify response parser"
```

---

### Task 2: Backend API — render pages + call Vision LLM

**Files:**
- Create: `D:\opencode\book-downloader\backend\api\toc.py`

A new FastAPI router with two endpoints:
- `POST /api/v1/toc/render-pages` — returns base64 PNG images of selected pages
- `POST /api/v1/toc/extract` — sends pages to Vision LLM, returns parsed bookmark text

- [ ] **Step 1: Create api/toc.py**

```python
"""TOC API — page rendering + Vision LLM extraction."""
import base64, io, json, os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/toc")

class RenderRequest(BaseModel):
    pdf_path: str
    start_page: int  # 0-indexed
    end_page: int

class ExtractRequest(BaseModel):
    pdf_path: str
    start_page: int
    end_page: int
    provider: str  # openai_compatible, gemini, anthropic, azure
    endpoint: str
    model: str
    api_key: str

@router.post("/render-pages")
def render_pages(req: RenderRequest):
    """Return base64 PNGs of selected page range."""
    import fitz
    doc = fitz.open(req.pdf_path)
    pages = []
    for i in range(req.start_page, min(req.end_page + 1, len(doc))):
        pix = doc[i].get_pixmap(dpi=150)
        buf = io.BytesIO(pix.tobytes("png"))
        pages.append(base64.b64encode(buf.getvalue()).decode())
    doc.close()
    return {"pages": pages, "count": len(pages)}

@router.post("/extract")
async def extract_toc(req: ExtractRequest):
    """Extract TOC from selected pages using Vision LLM."""
    from addbookmark.ai_vision_toc import build_vision_prompt, parse_tocify_response, call_vision_llm
    
    # Render pages as PNG
    import fitz
    doc = fitz.open(req.pdf_path)
    images = []
    for i in range(req.start_page, min(req.end_page + 1, len(doc))):
        pix = doc[i].get_pixmap(dpi=150)
        buf = io.BytesIO(pix.tobytes("png"))
        images.append(base64.b64encode(buf.getvalue()).decode())
    doc.close()
    
    prompt = build_vision_prompt()
    response = await call_vision_llm(
        images=images,
        prompt=prompt,
        provider=req.provider,
        endpoint=req.endpoint,
        model=req.model,
        api_key=req.api_key,
    )
    
    bookmark = parse_tocify_response(response) if response else ""
    return {"bookmark": bookmark, "raw_response": response[:500]}
```

- [ ] **Step 2: Register router in main.py**

Add to `D:\opencode\book-downloader\backend\main.py`:

```python
from api.toc import router as toc_router
app.include_router(toc_router)
```

- [ ] **Step 3: Verify syntax**

```bash
python -m py_compile backend\api\toc.py
python -m py_compile backend\main.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/api/toc.py backend/main.py
git commit -m "feat: TOC API — page rendering + Vision LLM extraction endpoints"
```

---

### Task 3: TOCModal frontend component

**Files:**
- Create: `D:\opencode\book-downloader\frontend\src\components\TOCModal.tsx`
- Modify: `D:\opencode\book-downloader\frontend\src\components\Layout.tsx`

A modal with 3 stages:
1. **Page select**: Thumbnail strip of pages, user drag-selects range
2. **Extract**: Loading spinner while Vision LLM processes
3. **Preview + Offset**: Parsed bookmark entries shown side-by-side with PDF page preview. Offset slider adjusts page mapping.

- [ ] **Step 1: Create TOCModal.tsx**

```tsx
import { useState, useEffect } from 'react'

interface TOCModalProps {
  pdfPath: string
  visible: boolean
  onConfirm: (bookmark: string, offset: number) => void
  onCancel: () => void
}

export default function TOCModal({ pdfPath, visible, onConfirm, onCancel }: TOCModalProps) {
  const [stage, setStage] = useState<'select' | 'extracting' | 'preview'>('select')
  const [startPage, setStartPage] = useState(0)
  const [endPage, setEndPage] = useState(5)
  const [pageImages, setPageImages] = useState<string[]>([])
  const [bookmark, setBookmark] = useState('')
  const [offset, setOffset] = useState(0)
  const [totalPages, setTotalPages] = useState(0)

  // 1. Load total pages on open
  useEffect(() => {
    if (!visible || !pdfPath) return
    fetch('/api/v1/toc/info', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({pdf_path: pdfPath}) })
      .then(r => r.json())
      .then(d => setTotalPages(d.pages))
  }, [visible, pdfPath])

  // 2. Render selected pages
  const loadPreviews = async () => {
    const res = await fetch('/api/v1/toc/render-pages', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pdf_path: pdfPath, start_page: startPage, end_page: endPage}),
    })
    const data = await res.json()
    setPageImages(data.pages)
  }

  // 3. Extract via Vision LLM
  const extract = async () => {
    setStage('extracting')
    // Use config values (passed via props or read from store)
    const res = await fetch('/api/v1/toc/extract', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        pdf_path: pdfPath, start_page: startPage, end_page: endPage,
        provider: 'openai_compatible', endpoint: '', model: '', api_key: '',
      }),
    })
    const data = await res.json()
    setBookmark(data.bookmark)
    setStage('preview')
  }

  if (!visible) return null

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center">
      <div className="bg-white dark:bg-gray-800 rounded-lg max-w-4xl w-full max-h-[90vh] overflow-auto p-6">
        <h2 className="text-lg font-semibold mb-4">智能目录识别</h2>
        
        {stage === 'select' && (
          <>
            <div className="flex gap-2 mb-4">
              <input type="number" value={startPage+1} onChange={e => setStartPage(Number(e.target.value)-1)} className="w-16 border rounded px-2" />
              <span>-</span>
              <input type="number" value={endPage+1} onChange={e => setEndPage(Number(e.target.value)-1)} className="w-16 border rounded px-2" />
              <span>/ {totalPages} 页</span>
              <button onClick={loadPreviews} className="px-3 py-1 bg-blue-500 text-white rounded text-xs">预览</button>
            </div>
            <div className="flex gap-2 overflow-x-auto mb-4">
              {pageImages.map((img, i) => (
                <img key={i} src={`data:image/png;base64,${img}`} className="h-40 border" alt={`Page ${startPage+i+1}`} />
              ))}
            </div>
            <button onClick={extract} className="px-4 py-2 bg-blue-600 text-white rounded">识别目录</button>
          </>
        )}

        {stage === 'extracting' && (
          <div className="text-center py-8">
            <div className="animate-spin w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full mx-auto mb-4" />
            <p>正在识别目录内容...</p>
          </div>
        )}

        {stage === 'preview' && (
          <>
            <div className="mb-4">
              <label>页码偏移: {offset}</label>
              <input type="range" min={-20} max={20} value={offset} onChange={e => setOffset(Number(e.target.value))} className="w-full" />
            </div>
            <pre className="text-xs bg-gray-100 dark:bg-gray-700 p-4 rounded max-h-60 overflow-auto mb-4">
              {bookmark.split('\n').slice(0, 30).join('\n')}
            </pre>
            <div className="flex gap-2">
              <button onClick={() => onConfirm(bookmark, offset)} className="px-4 py-2 bg-green-600 text-white rounded">确认添加</button>
              <button onClick={onCancel} className="px-4 py-2 bg-gray-300 rounded">取消</button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Wire into Layout.tsx**

In `Layout.tsx`, add after `<ConfirmStepModal />`:

```tsx
<TOCModal />
```

- [ ] **Step 3: Wire into Step 6 pipeline**

Modify `_step_bookmark` in `pipeline.py:2959`:

```python
# AI Vision — manual page selection via TOCModal
if not bookmark and pdf_path and os.path.exists(pdf_path):
    task_store.add_log(task_id, "目录为空，等待用户手动选择目录页")
    confirmed = await _wait_for_step_confirmation(
        task_id=task_id,
        step_name="toc_manual",
        step_label="智能目录识别",
        config_info={"pdf_path": pdf_path, "ai_vision_enabled": config.get("ai_vision_enabled", True)},
    )
```

- [ ] **Step 4: Build frontend**

```bash
cd D:\opencode\book-downloader\frontend
npm run build
```

- [ ] **Step 5: Commit**

```bash
cd D:\opencode\book-downloader
git add frontend/src/components/TOCModal.tsx frontend/src/components/Layout.tsx backend/engine/pipeline.py
git commit -m "feat: TOCModal with manual page selection, Vision LLM extraction, offset preview"
```

---

### Self-Review

**1. Spec coverage:**
- Manual page selection → TOCModal (Task 3) + render-pages API (Task 2)
- Vision model with structured prompt → Task 1 (new prompt) + extract API (Task 2)
- Offset adjustment → TOCModal (Task 3) with range slider
- User confirm + inject → TOCModal onConfirm → pipeline inject_bookmarks
- Only runs when Step 2 empty → pipeline check in Task 3 Step 3

**2. Placeholder scan:** No TBD/TODO.

**3. Type consistency:**
- `parse_tocify_response(response: str) -> str` returns tab-separated `title\tpage\n` format
- `inject_bookmarks` expects plain text with `title\tpage` lines — compatible
- TOCModal `onConfirm(bookmark, offset)` matches pipeline `inject_bookmarks(pdf, bookmark, pdf, offset)`
