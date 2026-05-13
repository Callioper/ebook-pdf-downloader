# PDF Preview Panel in Task Detail — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a PDF page preview panel with prev/next navigation to the right column of the task detail page, below the "进行中" task list.

**Architecture:** New `PDFPreviewPanel` component renders a single PDF page image with left/right arrow navigation and a page number input. Fetches total pages via `/api/v1/toc/info` and individual pages via `/api/v1/toc/render-page`. Placed in `TaskDetailPage.tsx` right column below `TaskListPanel`, conditionally shown when `task.report?.pdf_path` exists.

**Tech Stack:** React + TypeScript + Tailwind CSS, existing `/api/v1/toc/info` and `/api/v1/toc/render-page` endpoints

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `frontend/src/components/PDFPreviewPanel.tsx` | **Create** | Single-page PDF viewer with prev/next nav |
| `frontend/src/pages/TaskDetailPage.tsx` | **Modify** | Add PDFPreviewPanel to right column |

---

### Task 1: Create PDFPreviewPanel component

**Files:**
- Create: `frontend/src/components/PDFPreviewPanel.tsx`

- [ ] **Step 1: Write the full component**

```tsx
import { useState, useEffect, useRef } from 'react'

interface Props {
  pdfPath: string
}

export default function PDFPreviewPanel({ pdfPath }: Props) {
  const [totalPages, setTotalPages] = useState(0)
  const [currentPage, setCurrentPage] = useState(0)
  const [imageUrl, setImageUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const blobRef = useRef<string>('')
  const loadedPages = useRef<Set<number>>(new Set())

  // Get total pages on mount / pdfPath change
  useEffect(() => {
    if (!pdfPath) return
    fetch('/api/v1/toc/info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_path: pdfPath }),
    })
      .then(r => r.json())
      .then(d => { setTotalPages(d.pages || 0) })
      .catch(() => setTotalPages(0))
  }, [pdfPath])

  const loadPage = async (page: number) => {
    const clamped = Math.max(0, Math.min(totalPages - 1, page))
    setCurrentPage(clamped)
    setLoading(true)
    try {
      const res = await fetch('/api/v1/toc/render-page', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pdf_path: pdfPath, page: clamped }),
      })
      if (!res.ok) { setLoading(false); return }
      const blob = await res.blob()
      if (blobRef.current) URL.revokeObjectURL(blobRef.current)
      const url = URL.createObjectURL(blob)
      blobRef.current = url
      setImageUrl(url)
      loadedPages.current.add(clamped)
    } catch { /* ignore */ }
    setLoading(false)
  }

  // Load first page when totalPages known
  useEffect(() => {
    if (totalPages > 0) loadPage(0)
  }, [totalPages])

  // Cleanup
  useEffect(() => {
    const u = blobRef.current
    return () => { if (u) URL.revokeObjectURL(u) }
  }, [])

  if (!pdfPath || totalPages <= 0) return null

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-3">
      <h4 className="text-sm font-semibold text-gray-700 mb-2">PDF 预览</h4>

      <div className="flex items-center justify-between mb-2">
        <button
          onClick={() => loadPage(currentPage - 1)}
          disabled={currentPage <= 0 || loading}
          className="p-1 rounded border border-gray-300 hover:bg-gray-100 disabled:opacity-30 dark:border-gray-600 dark:hover:bg-gray-700"
        >
          <svg className="w-4 h-4 text-gray-600 dark:text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>

        <div className="flex items-center gap-1">
          <input
            type="number" min={1} max={totalPages} value={currentPage + 1}
            onChange={e => loadPage(Number(e.target.value) - 1)}
            className="w-14 border border-gray-300 dark:border-gray-600 rounded px-1.5 py-0.5 text-xs text-center dark:bg-gray-700 dark:text-gray-100"
          />
          <span className="text-xs text-gray-400">/ {totalPages}</span>
        </div>

        <button
          onClick={() => loadPage(currentPage + 1)}
          disabled={currentPage >= totalPages - 1 || loading}
          className="p-1 rounded border border-gray-300 hover:bg-gray-100 disabled:opacity-30 dark:border-gray-600 dark:hover:bg-gray-700"
        >
          <svg className="w-4 h-4 text-gray-600 dark:text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>
      </div>

      <div className="bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-600 rounded overflow-hidden flex items-center justify-center"
        style={{ minHeight: '300px', maxHeight: '60vh' }}>
        {loading && !imageUrl ? (
          <div className="flex items-center justify-center w-full h-64">
            <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : imageUrl ? (
          <img src={imageUrl} alt={`Page ${currentPage + 1}`}
            className="max-w-full max-h-full object-contain" draggable={false} />
        ) : (
          <span className="text-xs text-gray-400">PDF 不可用</span>
        )}
      </div>

      <p className="text-[10px] text-center text-gray-400 mt-1">第 {currentPage + 1} 页</p>
    </div>
  )
}
```

- [ ] **Step 2: Build frontend to verify TypeScript**

```bash
cmd /c "cd /d D:\opencode\book-downloader\frontend && npm run build"
```

Expected: 119 modules transformed, 0 TS errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/PDFPreviewPanel.tsx
git commit -m "feat: add PDFPreviewPanel component for single-page PDF preview"
```

---

### Task 2: Add PDFPreviewPanel to TaskDetailPage

**Files:**
- Modify: `frontend/src/pages/TaskDetailPage.tsx:3` (imports), `:325-327` (right column)

- [ ] **Step 1: Import PDFPreviewPanel**

At line 3 (after `import LogStream from '../components/LogStream'`), add:

```tsx
import PDFPreviewPanel from '../components/PDFPreviewPanel'
```

- [ ] **Step 2: Add PDFPreviewPanel to right column**

Replace lines 325-327:

```tsx
      <div className="space-y-4">
        <TaskListPanel compact />
        {task.report?.pdf_path && (
          <PDFPreviewPanel pdfPath={task.report.pdf_path} />
        )}
      </div>
```

- [ ] **Step 3: Build frontend to verify**

```bash
cmd /c "cd /d D:\opencode\book-downloader\frontend && npm run build"
```

Expected: 119 modules transformed, 0 TS errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/TaskDetailPage.tsx
git commit -m "feat: add PDF preview panel to task detail right column"
```

---

### Task 3: Rebuild and smoke test

- [ ] **Step 1: Rebuild exe**

```bash
cd backend
python -m PyInstaller --noconfirm book-downloader.spec
```

- [ ] **Step 2: Smoke test**

1. Start exe, navigate to any task with a completed PDF download
2. Verify right column shows "PDF 预览" panel below "进行中"
3. Click left/right arrows — page changes
4. Type page number in input — page changes
5. Verify loading spinner shows briefly on page change

- [ ] **Step 3: Done**

---

## Self-Review

### Spec Coverage
- [x] PDF preview in task detail page — `PDFPreviewPanel` component placed in right column
- [x] Left/right arrows for navigation — `<button>` with SVG chevron icons
- [x] Similar to offset confirmation preview — same `/api/v1/toc/render-page` endpoint, same blob URL pattern, same prev/next + page number input pattern
- [x] Below "进行中" indicator — placed after `TaskListPanel` in the same `space-y-4` container

### Placeholder Scan
No TODOs, TBDs, or placeholders. All code is complete.

### Type Consistency
- `pdfPath: string` prop — consistent with `task.report?.pdf_path` (string | undefined)
- `totalPages` from `/api/v1/toc/info` response — matches backend `{"pages": int}`
- `/api/v1/toc/render-page` — matches existing endpoint, uses default 48 DPI
