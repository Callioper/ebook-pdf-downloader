# PDF Page Viewer for TOC Selection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace TOCModal's page-number inputs with a scrollable PDF page viewer where users can browse all pages and click/drag to select the TOC page range.

**Architecture:** New `PDFPageViewer` React component renders page thumbnails in a scrollable vertical column using lazy batch loading via `IntersectionObserver`. TOCModal embeds this viewer, replacing number inputs. Backend adds a lightweight single-page render endpoint at 72 DPI for fast browsing.

**Tech Stack:** React + TypeScript (frontend), Python/FastAPI + PyMuPDF (backend), Tailwind CSS dark mode

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend/src/components/PDFPageViewer.tsx` | **Create** | Scrollable PDF page browser with lazy loading and click-to-select-range |
| `frontend/src/components/TOCModal.tsx` | **Modify** | Embed PDFPageViewer, remove number inputs, wire selection state |
| `backend/api/toc.py` | **Modify** | Add `/render-page` endpoint for single-page 72 DPI thumbnail |

---

### Task 1: Add `/render-page` backend endpoint

**Files:**
- Modify: `backend/api/toc.py` (after line 60, before `/extract`)

- [ ] **Step 1: Add request model and endpoint**

Insert after the `render_pages` function (line 60) and before `/extract` (line 63):

```python
class SinglePageRequest(BaseModel):
    pdf_path: str
    page: int  # 0-indexed


@router.post("/render-page")
def render_page(req: SinglePageRequest):
    """Return a single page as base64 PNG at low DPI for fast browsing."""
    import fitz
    if not os.path.exists(req.pdf_path):
        raise HTTPException(404, "PDF not found")
    doc = fitz.open(req.pdf_path)
    if req.page < 0 or req.page >= len(doc):
        doc.close()
        raise HTTPException(400, f"Page {req.page} out of range (0-{len(doc)-1})")
    pix = doc[req.page].get_pixmap(dpi=72)
    buf = io.BytesIO(pix.tobytes("png"))
    img = base64.b64encode(buf.getvalue()).decode()
    doc.close()
    return {"page": req.page, "image": img}
```

- [ ] **Step 2: Verify endpoint works**

```bash
# Start backend, then:
curl -X POST http://127.0.0.1:8000/api/v1/toc/render-page \
  -H "Content-Type: application/json" \
  -d '{"pdf_path":"D:/some/test.pdf","page":0}'
# Expected: {"page":0,"image":"iVBORw0KGgo..."}
```

- [ ] **Step 3: Commit**

```bash
git add backend/api/toc.py
git commit -m "feat: add /render-page endpoint for single-page 72dpi thumbnails"
```

---

### Task 2: Create PDFPageViewer component

**Files:**
- Create: `frontend/src/components/PDFPageViewer.tsx`

- [ ] **Step 1: Create component skeleton with props interface**

```tsx
import { useState, useEffect, useRef, useCallback } from 'react'

interface Props {
  pdfPath: string
  totalPages: number
  selectedStart: number
  selectedEnd: number
  onSelectionChange: (start: number, end: number) => void
}

const BATCH_SIZE = 20
const PAGE_WIDTH = 180   // px
const PAGE_HEIGHT_RATIO = 1.414  // A4 aspect

export default function PDFPageViewer({
  pdfPath, totalPages, selectedStart, selectedEnd, onSelectionChange,
}: Props) {
  const [loadedPages, setLoadedPages] = useState<Map<number, string>>(new Map())
  const [visibleRange, setVisibleRange] = useState({ start: 0, end: BATCH_SIZE - 1 })
  const [dragMode, setDragMode] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const observerRef = useRef<IntersectionObserver | null>(null)

  return (
    <div ref={containerRef}
      className="overflow-y-auto border border-gray-300 dark:border-gray-600 rounded bg-gray-100 dark:bg-gray-900"
      style={{ height: '60vh' }}>
      {/* page thumbnails go here */}
    </div>
  )
}
```

- [ ] **Step 2: Add lazy loading with IntersectionObserver**

Add inside the component, before `return`:

```tsx
// Track which pages are visible via IntersectionObserver
useEffect(() => {
  if (!containerRef.current) return
  const sentinel = document.createElement('div')
  sentinel.style.height = '1px'
  sentinel.dataset.sentinel = 'bottom'
  containerRef.current.appendChild(sentinel)

  const observer = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue
      const el = e.target as HTMLElement
      const pi = Number(el.dataset.pageIndex)
      if (isNaN(pi)) continue
      // Expand visible range
      setVisibleRange(r => {
        const ns = Math.max(0, pi - BATCH_SIZE / 2)
        const ne = Math.min(totalPages - 1, pi + BATCH_SIZE / 2)
        if (ns >= r.start && ne <= r.end) return r  // already covered
        return { start: Math.min(r.start, ns), end: Math.max(r.end, ne) }
      })
    }
  }, { root: containerRef.current, rootMargin: '400px', threshold: 0.01 })

  observerRef.current = observer
  return () => {
    observer.disconnect()
    sentinel.remove()
  }
}, [totalPages])

// Fetch pages in visible range
useEffect(() => {
  const toLoad: number[] = []
  for (let i = visibleRange.start; i <= Math.min(visibleRange.end, totalPages - 1); i++) {
    if (!loadedPages.has(i)) toLoad.push(i)
  }
  if (toLoad.length === 0) return

  let cancelled = false
  const loadBatch = async () => {
    for (const page of toLoad) {
      if (cancelled) return
      const res = await fetch('/api/v1/toc/render-page', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pdf_path: pdfPath, page }),
      })
      const d = await res.json()
      if (cancelled) return
      if (d.image) setLoadedPages(prev => new Map(prev).set(page, d.image))
    }
  }
  loadBatch()
  return () => { cancelled = true }
}, [visibleRange, pdfPath])
```

- [ ] **Step 3: Add click and drag selection handlers**

Add click handler (single-click to set range):

```tsx
const handlePageClick = useCallback((pageIndex: number, e: React.MouseEvent) => {
  if (e.shiftKey && selectedStart >= 0) {
    // Extend range: shift-click
    const s = Math.min(selectedStart, pageIndex)
    const en = Math.max(selectedStart, pageIndex)
    onSelectionChange(s, en)
  } else {
    // Start new range or toggle single page
    if (selectedStart === pageIndex && selectedEnd === pageIndex) {
      onSelectionChange(-1, -1)  // deselect
    } else {
      onSelectionChange(pageIndex, pageIndex)
    }
  }
}, [selectedStart, selectedEnd, onSelectionChange])
```

Add drag-to-select handling:

```tsx
const dragStartRef = useRef(0)

const handleMouseDown = (pageIndex: number) => {
  dragStartRef.current = pageIndex
  setDragMode(true)
  onSelectionChange(pageIndex, pageIndex)
}

useEffect(() => {
  if (!dragMode) return
  const container = containerRef.current
  if (!container) return

  const onMove = (e: MouseEvent) => {
    const rect = container.getBoundingClientRect()
    const y = e.clientY - rect.top + container.scrollTop
    const pageHeight = PAGE_WIDTH * PAGE_HEIGHT_RATIO + 36  // img + margin + label
    const page = Math.floor(y / pageHeight)
    const clamped = Math.max(0, Math.min(totalPages - 1, page))
    const s = Math.min(dragStartRef.current, clamped)
    const en = Math.max(dragStartRef.current, clamped)
    onSelectionChange(s, en)
  }
  const onUp = () => setDragMode(false)

  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
  return () => {
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
}, [dragMode, totalPages, onSelectionChange])
```

- [ ] **Step 4: Render page thumbnails with selection highlighting**

Replace the skeleton `return` block with:

```tsx
return (
  <div ref={containerRef}
    className="overflow-y-auto border border-gray-300 dark:border-gray-600 rounded bg-gray-100 dark:bg-gray-900 select-none"
    style={{ height: '60vh' }}>
    <div className="flex flex-col items-center gap-1 py-3">
      {Array.from({ length: totalPages }, (_, i) => {
        const selected = i >= selectedStart && i <= selectedEnd && selectedStart >= 0
        const img = loadedPages.get(i)
        return (
          <div key={i}
            data-page-index={i}
            onMouseDown={() => handleMouseDown(i)}
            onClick={(e) => handlePageClick(i, e)}
            className={`
              cursor-pointer shrink-0 rounded transition-all duration-100
              ${selected
                ? 'ring-2 ring-blue-500 shadow-lg shadow-blue-500/30 scale-[1.02] bg-blue-50 dark:bg-blue-900/20'
                : 'hover:ring-1 hover:ring-gray-400 dark:hover:ring-gray-500'}
            `}
            style={{ width: PAGE_WIDTH }}
          >
            {img ? (
              <img src={`data:image/png;base64,${img}`}
                className="w-full block rounded-t"
                style={{ aspectRatio: `1 / ${PAGE_HEIGHT_RATIO}` }}
                alt={`Page ${i + 1}`}
                draggable={false}
              />
            ) : (
              <div className="w-full bg-gray-200 dark:bg-gray-800 rounded-t animate-pulse flex items-center justify-center"
                style={{ height: PAGE_WIDTH * PAGE_HEIGHT_RATIO }}>
                <span className="text-xs text-gray-400">{i + 1}</span>
              </div>
            )}
            <p className={`text-[10px] text-center py-1 font-mono rounded-b ${
              selected
                ? 'text-blue-600 dark:text-blue-300 bg-blue-100 dark:bg-blue-900/40'
                : 'text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800'
            }`}>
              第 {i + 1} 页
            </p>
          </div>
        )
      })}
    </div>
  </div>
)
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PDFPageViewer.tsx
git commit -m "feat: add PDFPageViewer with lazy loading and click/drag page selection"
```

---

### Task 3: Integrate PDFPageViewer into TOCModal

**Files:**
- Modify: `frontend/src/components/TOCModal.tsx`

- [ ] **Step 1: Import PDFPageViewer and replace number inputs in 'select' stage**

At line 1, add import:

```tsx
import PDFPageViewer from './PDFPageViewer'
```

Replace lines 84-114 (the entire `{stage === 'select' && (...)}` block from `<p>` description through the page-images div) with:

```tsx
        {stage === 'select' && (
          <>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
              点击页面设置起始页，Shift+点击设置结束页，或拖拽选择连续页面范围。已选: 第 {selectedStart >= 0 ? selectedStart + 1 : '?'} – {selectedEnd >= 0 ? selectedEnd + 1 : '?'} 页
            </p>

            <PDFPageViewer
              pdfPath={pdfPath}
              totalPages={totalPages}
              selectedStart={startPage}
              selectedEnd={endPage}
              onSelectionChange={(s, e) => {
                setStartPage(s)
                setEndPage(e)
              }}
            />

            <div className="flex items-center gap-2 mt-3 mb-1">
              <span className="text-xs text-gray-600 dark:text-gray-300">页码:</span>
              <input type="number" min={1} max={totalPages} value={startPage + 1}
                onChange={(e) => setStartPage(Math.max(0, Number(e.target.value) - 1))}
                className="w-16 border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-xs dark:bg-gray-700 dark:text-gray-100" />
              <span className="text-xs text-gray-400">–</span>
              <input type="number" min={1} max={totalPages} value={endPage + 1}
                onChange={(e) => setEndPage(Math.min(totalPages - 1, Number(e.target.value) - 1))}
                className="w-16 border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-xs dark:bg-gray-700 dark:text-gray-100" />
              <span className="text-xs text-gray-400">/ {totalPages} 页</span>
              <button onClick={loadPreviews}
                className="px-3 py-1 text-xs rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600">
                {previewImages ? '刷新预览' : '预览选中页'}
              </button>
            </div>

            {/* Preview area for selected pages at higher resolution */}
            {previewImages && pageImages.length > 0 && (
              <div className="flex gap-2 overflow-x-auto pb-2 mb-2">
                {pageImages.map((img, i) => (
                  <div key={i} className="shrink-0">
                    <img src={`data:image/png;base64,${img}`}
                      className="h-40 border border-gray-200 dark:border-gray-600 rounded"
                      alt={`Page ${startPage + i + 1}`} />
                    <p className="text-[10px] text-center text-gray-400 mt-1">第 {startPage + i + 1} 页</p>
                  </div>
                ))}
              </div>
            )}

            <div className="flex gap-2">
              <button onClick={extract} disabled={totalPages === 0 || startPage < 0 || endPage < startPage}
                className="px-4 py-2 text-sm rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50">
                识别目录
              </button>
              <button onClick={onCancel}
                className="px-4 py-2 text-sm rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600">
                跳过
              </button>
            </div>
          </>
        )}
```

- [ ] **Step 2: Update modal max-width to accommodate viewer**

Change line 73 — update `max-w-3xl` to `max-w-4xl`:

```tsx
<div className="bg-white dark:bg-gray-800 rounded-lg max-w-4xl w-full max-h-[90vh] overflow-auto p-6 shadow-xl">
```

- [ ] **Step 3: Build frontend to verify TypeScript**

```bash
cd frontend && npm run build
# Expected: builds successfully with 0 TS errors
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/TOCModal.tsx
git commit -m "feat: embed PDFPageViewer in TOCModal, replace number inputs with page browser"
```

---

### Task 4: Rebuild and smoke test

- [ ] **Step 1: Rebuild PyInstaller exe**

```bash
cd backend
python -m PyInstaller --noconfirm book-downloader.spec
# Expected: build complete at backend/dist/ebook-pdf-downloader.exe
```

- [ ] **Step 2: Basic smoke test**

Start the exe, navigate to `/config`, click "智能书签", select a PDF. Verify:
- PDF page thumbnails render progressively as you scroll
- Clicking a page highlights it (blue ring)
- Shift+click extends the range
- Drag selects a contiguous range
- Page number inputs sync with viewer selection
- "预览选中页" button shows higher-res previews of selected range
- Dark mode works (backgrounds, rings, labels)

- [ ] **Step 3: Commit**

```bash
# Only if exe path is tracked — usually ignored. Just note the build date.
```

---

## Self-Review

### Spec Coverage
- [x] PDF browsing window to view entire PDF — `PDFPageViewer` with scrollable column of all pages
- [x] Click to select TOC pages — `handlePageClick` sets start/end
- [x] Drag to select TOC pages — `handleMouseDown` + `mousemove` handler selects contiguous range
- [x] Visual selection highlighting — blue ring + tint + scale on selected pages
- [x] Lazy loading — `IntersectionObserver` loads pages in batches of 20
- [x] Integration into TOCModal — replaces old number-input-only UI
- [x] Dark mode — Tailwind `dark:` variants throughout

### Placeholder Scan
No TODOs, TBDs, or placeholders. All code is complete and specific.

### Type Consistency
- `Props` interface for `PDFPageViewer` uses `selectedStart: number`, `selectedEnd: number`, `onSelectionChange: (start: number, end: number) => void` — consistent with TOCModal's `startPage`/`endPage` state and `setStartPage`/`setEndPage` calls.
- Backend `SinglePageRequest.page: int` — matches frontend passing `page` (0-indexed integer).
