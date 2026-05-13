# Enhanced TOC Page Selection & Preview — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-click page selection with two-click range selection, add full-width preview toggle, and create a side-by-side preview stage where users align bookmark entries to actual PDF pages to set offset precisely, then merge TOC pages into the final bookmark.

**Architecture:** PDFPageViewer gets a `twoClick` prop enabling first-click-start/second-click-end range selection. TOCModal's preview stage splits into left (bookmark list with first entry highlighted) and right (single-page PDF viewer with +/- navigation). The user navigates to the actual PDF page matching bookmark entry #1; the offset is `actualPage - extractedPageNumber`. TOC pages are prepended to the bookmark string before injection.

**Tech Stack:** React + TypeScript (frontend), Python/FastAPI (backend unchanged)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend/src/components/PDFPageViewer.tsx` | Modify | Add `twoClick` prop for two-click range selection |
| `frontend/src/components/TOCModal.tsx` | Modify | Side-by-side preview, full-width toggle, offset alignment, TOC-page merge |

---

### Task 1: Two-click range selection in PDFPageViewer

**Files:**
- Modify: `frontend/src/components/PDFPageViewer.tsx`

- [ ] **Step 1: Add `twoClick` prop to Props**

At line 3, add the `twoClick` prop:

```tsx
interface Props {
  pdfPath: string
  totalPages: number
  selectedStart: number
  selectedEnd: number
  onSelectionChange: (start: number, end: number) => void
  twoClick?: boolean  // if true: first click = start, second click = end
}
```

- [ ] **Step 2: Add internal state for pending start in two-click mode**

After line 19 (`const dragStartRef = useRef(0)`), add:

```tsx
const [pendingStart, setPendingStart] = useState<number | null>(null)
```

- [ ] **Step 3: Modify `handlePageClick` to support two-click mode**

Replace the existing `handlePageClick` (lines 82-95) with:

```tsx
const handlePageClick = useCallback((pageIndex: number, e: React.MouseEvent) => {
    if (dragMode) return
    if (twoClick) {
      if (pendingStart === null) {
        setPendingStart(pageIndex)
        onSelectionChange(pageIndex, pageIndex)
        return
      }
      const s = Math.min(pendingStart, pageIndex)
      const en = Math.max(pendingStart, pageIndex)
      onSelectionChange(s, en)
      setPendingStart(null)
      return
    }
    if (e.shiftKey && selectedStart >= 0) {
      const s = Math.min(selectedStart, pageIndex)
      const en = Math.max(selectedStart, pageIndex)
      onSelectionChange(s, en)
    } else {
      if (selectedStart === pageIndex && selectedEnd === pageIndex) {
        onSelectionChange(-1, -1)
      } else {
        onSelectionChange(pageIndex, pageIndex)
      }
    }
  }, [selectedStart, selectedEnd, onSelectionChange, dragMode, twoClick, pendingStart])
```

- [ ] **Step 4: Add visual indicator for pending start page**

In the rendering section, after the `selected` check (around line 142), add a `pending` indicator. Update the className for each page item to include:

```tsx
const selected = i >= selectedStart && i <= selectedEnd && selectedStart >= 0
const pending = twoClick && pendingStart === i
// then in className add:
// ${pending ? 'ring-2 ring-amber-400 shadow-lg shadow-amber-400/30 scale-[1.02] bg-amber-50 dark:bg-amber-900/20' : ''}
```

Replace this block (the className template literal around line 134-138):

```tsx
className={`
  cursor-pointer shrink-0 rounded transition-all duration-100
  ${selected
    ? 'ring-2 ring-blue-500 shadow-lg shadow-blue-500/30 scale-[1.02] bg-blue-50 dark:bg-blue-900/20'
    : pending
    ? 'ring-2 ring-amber-400 shadow-lg shadow-amber-400/30 scale-[1.02] bg-amber-50 dark:bg-amber-900/20'
    : 'hover:ring-1 hover:ring-gray-400 dark:hover:ring-gray-500'}
`}
```

- [ ] **Step 5: Build and commit**

```bash
cmd /c "cd /d D:\opencode\book-downloader\frontend && npm run build"
git add frontend/src/components/PDFPageViewer.tsx
git commit -m "feat: add two-click range selection mode to PDFPageViewer"
```

---

### Task 2: Side-by-side preview with PDF page navigator

**Files:**
- Modify: `frontend/src/components/TOCModal.tsx`

- [ ] **Step 1: Add new state variables for preview stage**

After the existing state (around line 19-20), add:

```tsx
const [previewPage, setPreviewPage] = useState(0)  // currently shown page in preview
const [previewPageImg, setPreviewPageImg] = useState('')  // base64 image of that page
const [previewFullWidth, setPreviewFullWidth] = useState(false)
const [alignedPage, setAlignedPage] = useState<number | null>(null)  // user-confirmed actual page for bookmark line 1
```

- [ ] **Step 2: Load first bookmark page when entering preview**

Modify the `extract` function (around line 48-67) — add after `setBookmark`:

```tsx
// After setBookmark(data.bookmark || ''), load first advertised page
const lines = (data.bookmark || '').split('\n')
const firstLine = lines[0] || ''
const pageMatch = firstLine.match(/^\s*(\d+)/)
const firstAdvertisedPage = pageMatch ? parseInt(pageMatch[1], 10) - 1 : 0
setPreviewPage(firstAdvertisedPage)
loadPreviewPage(firstAdvertisedPage)
```

Add the `loadPreviewPage` function before `extract`:

```tsx
const loadPreviewPage = async (page: number) => {
  const clamped = Math.max(0, Math.min(totalPages - 1, page))
  setPreviewPage(clamped)
  setPreviewPageImg('')
  const res = await fetch('/api/v1/toc/render-page', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pdf_path: pdfPath, page: clamped }),
  })
  const d = await res.json()
  if (d.image) setPreviewPageImg(d.image)
}
```

- [ ] **Step 3: Replace the 'preview' stage with side-by-side layout**

Replace the entire `{stage === 'preview' && (...)}` block (lines 149-183) with:

```tsx
        {stage === 'preview' && (
          <>
            {/* Offset alignment guide */}
            <div className="mb-3 p-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded text-xs text-blue-700 dark:text-blue-300">
              请将右边 PDF 翻到<strong>第一条书签</strong>对应的实际页面，然后点击「以此为第一页」确认偏移量。
              {alignedPage !== null && (
                <span className="ml-2 text-green-700 dark:text-green-300">
                  ✓ 已定位 — 第 {alignedPage + 1} 页（偏移 {alignedPage - previewPage}）
                </span>
              )}
            </div>

            <div className={`flex gap-3 ${previewFullWidth ? 'flex-col' : ''}`}>
              {/* Left: bookmark text */}
              <div className={`${previewFullWidth ? 'w-full' : 'w-1/2'}`}>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-medium text-gray-600 dark:text-gray-300">提取的目录</label>
                  <button
                    onClick={() => setPreviewFullWidth(!previewFullWidth)}
                    className="text-[11px] text-blue-500 hover:text-blue-600">
                    {previewFullWidth ? '分栏' : '全宽'}
                  </button>
                </div>
                <pre className="text-xs bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded p-3 overflow-auto font-mono dark:text-gray-200"
                  style={{ maxHeight: previewFullWidth ? '30vh' : '50vh' }}>
                  {bookmark.split('\n').map((line, i) => (
                    <div key={i} className={i === 0 ? 'bg-yellow-100 dark:bg-yellow-900/30 -mx-1 px-1 rounded' : ''}>
                      {line}
                    </div>
                  ))}
                </pre>
              </div>

              {/* Right: PDF page navigator */}
              <div className={`${previewFullWidth ? 'w-full' : 'w-1/2'}`}>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-medium text-gray-600 dark:text-gray-300">PDF 页面</label>
                  <div className="flex items-center gap-1">
                    <button onClick={() => loadPreviewPage(previewPage - 1)} disabled={previewPage <= 0}
                      className="px-1.5 py-0.5 text-xs rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-30">
                      −
                    </button>
                    <input type="number" min={1} max={totalPages} value={previewPage + 1}
                      onChange={(e) => loadPreviewPage(Number(e.target.value) - 1)}
                      className="w-16 border border-gray-300 dark:border-gray-600 rounded px-2 py-0.5 text-xs text-center dark:bg-gray-700 dark:text-gray-100" />
                    <span className="text-xs text-gray-400">/ {totalPages}</span>
                    <button onClick={() => loadPreviewPage(previewPage + 1)} disabled={previewPage >= totalPages - 1}
                      className="px-1.5 py-0.5 text-xs rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-30">
                      +
                    </button>
                    <button onClick={() => { setAlignedPage(previewPage); setOffset(previewPage - (startPage >= 0 ? startPage : 0)) }}
                      className="ml-2 px-2 py-0.5 text-xs rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-900/60 border border-blue-300 dark:border-blue-600">
                      以此为第一页
                    </button>
                  </div>
                </div>
                {previewPageImg ? (
                  <div className="bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-600 rounded overflow-hidden flex items-center justify-center"
                    style={{ maxHeight: previewFullWidth ? '40vh' : '60vh' }}>
                    <img src={`data:image/png;base64,${previewPageImg}`}
                      className="max-w-full max-h-full object-contain"
                      alt={`Page ${previewPage + 1}`} />
                  </div>
                ) : (
                  <div className="bg-gray-200 dark:bg-gray-800 rounded animate-pulse flex items-center justify-center"
                    style={{ height: previewFullWidth ? '40vh' : '60vh' }}>
                    <span className="text-xs text-gray-400">加载中...</span>
                  </div>
                )}
                <p className="text-[10px] text-center text-gray-400 mt-1">第 {previewPage + 1} 页</p>
              </div>
            </div>

            {/* Offset slider (kept for fine-tuning) */}
            <div className="mt-3 mb-1">
              <label className="text-xs font-medium text-gray-600 dark:text-gray-300 block mb-1">
                页码偏移: {offset > 0 ? `+${offset}` : offset}
              </label>
              <input type="range" min={-50} max={50} value={offset}
                onChange={(e) => setOffset(Number(e.target.value))}
                className="w-full" />
            </div>

            <div className="flex gap-2">
              <button onClick={() => onConfirm(bookmark, offset)}
                className="px-4 py-2 text-sm rounded bg-green-600 text-white hover:bg-green-700">
                确认添加 ({bookmark.split('\n').filter(l => l.trim()).length} 条)
              </button>
              <button onClick={() => { setStage('select'); setBookmark(''); setAlignedPage(null); }}
                className="px-4 py-2 text-sm rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600">
                重新选择
              </button>
            </div>
          </>
        )}
```

- [ ] **Step 4: Build and commit**

```bash
cmd /c "cd /d D:\opencode\book-downloader\frontend && npm run build"
git add frontend/src/components/TOCModal.tsx
git commit -m "feat: side-by-side preview with page navigator and first-entry alignment"
```

---

### Task 3: Merge TOC pages into bookmark

**Files:**
- Modify: `frontend/src/components/TOCModal.tsx`

- [ ] **Step 1: Add prop for additional pages and merge on confirm**

Modify the `onConfirm` call in the preview stage to prepend the selected TOC pages as bookmark entries. Update the state variable usage to include TOC page markers.

Add a helper function before the `return`:

```tsx
const buildFinalBookmark = (): string => {
  let header = ''
  if (startPage >= 0 && endPage >= startPage) {
    header += '----- 目录页 -----\n'
    for (let i = startPage; i <= endPage; i++) {
      header += `第 ${i + 1} 页\n`
    }
    header += '---------------------\n\n'
  }
  return header + bookmark
}
```

- [ ] **Step 2: Use merged bookmark on confirm**

Change the confirm button's onClick (in the preview stage) from:
```tsx
onClick={() => onConfirm(bookmark, offset)}
```
to:
```tsx
onClick={() => onConfirm(buildFinalBookmark(), offset)}
```

- [ ] **Step 3: Build and commit**

```bash
cmd /c "cd /d D:\opencode\book-downloader\frontend && npm run build"
git add frontend/src/components/TOCModal.tsx
git commit -m "feat: merge TOC page markers into final bookmark"
```

---

### Task 4: Wire twoClick prop and rebuild

- [ ] **Step 1: Pass `twoClick` to PDFPageViewer in TOCModal**

In `TOCModal.tsx`, find the `<PDFPageViewer` usage (around line 89) and add `twoClick`:

```tsx
<PDFPageViewer
  pdfPath={pdfPath}
  totalPages={totalPages}
  selectedStart={startPage}
  selectedEnd={endPage}
  twoClick
  onSelectionChange={(s, e) => {
    setStartPage(s)
    setEndPage(e)
  }}
/>
```

- [ ] **Step 2: Update instruction text**

Change line 86's instruction text from:
```
点击页面设置起始页，Shift+点击设置结束页，或拖拽选择连续页面范围。
```
to:
```
点击第一页设置起始页，再点击最后一页完成选择，或拖拽选择连续页面范围。
```

- [ ] **Step 3: Build, commit, rebuild exe, smoke test**

```bash
cmd /c "cd /d D:\opencode\book-downloader\frontend && npm run build"
git add frontend/src/components/TOCModal.tsx
git commit -m "feat: enable two-click range selection for TOC modal"

cd backend
python -m PyInstaller --noconfirm book-downloader.spec
```

Smoke test checklist:
1. Open exe → Settings → 智能书签 → select PDF
2. First click on a page → amber ring (pending start)
3. Second click on a later page → blue ring on range
4. Click "识别目录" → extraction spinner → preview stage
5. Preview shows left (bookmark, first line highlighted) / right (PDF page)
6. Click +/- to navigate pages, click "以此为第一页" → offset updates
7. Toggle "全宽" / "分栏" button
8. Click "确认" → bookmarks injected with TOC pages prepended

---

## Self-Review

### Spec Coverage
- [x] Two-click range selection (not single-click) → Task 1 + Task 4
- [x] Full-width preview option → Task 2 (previewFullWidth toggle)
- [x] Side-by-side offset alignment: left=bookmark, right=PDF → Task 2
- [x] +/- page navigation in preview → Task 2 (loadPreviewPage)
- [x] "以此为第一页" button to set offset from actual page → Task 2
- [x] Merge manually-determined TOC pages into final bookmark → Task 3

### Placeholder Scan
No TODOs, TBDs, or placeholders.

### Type Consistency
- `twoClick?: boolean` added to PDFPageViewer Props, used in TOCModal — consistent
- `loadPreviewPage(page: number)` added to TOCModal, uses `/api/v1/toc/render-page` — consistent with backend
- `buildFinalBookmark(): string` uses `startPage`/`endPage` state — consistent
- `alignedPage: number | null` — consistent usage across preview stage
