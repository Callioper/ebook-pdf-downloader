import { useState, useEffect, useRef, useCallback } from 'react'

interface Props {
  pdfPath: string
  totalPages: number
  selectedStart: number
  selectedEnd: number
  onSelectionChange: (start: number, end: number) => void
}

const BATCH_SIZE = 20
const PAGE_WIDTH = 180

export default function PDFPageViewer({
  pdfPath, totalPages, selectedStart, selectedEnd, onSelectionChange,
}: Props) {
  const [loadedPages, setLoadedPages] = useState<Map<number, string>>(new Map())
  const [visibleRange, setVisibleRange] = useState({ start: 0, end: BATCH_SIZE - 1 })
  const [dragMode, setDragMode] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const dragStartRef = useRef(0)

  // Lazy load via IntersectionObserver
  useEffect(() => {
    if (!containerRef.current) return
    const observer = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue
        const el = e.target as HTMLElement
        const pi = Number(el.dataset.pageIndex)
        if (isNaN(pi)) continue
        setVisibleRange(r => {
          const ns = Math.max(0, pi - BATCH_SIZE / 2)
          const ne = Math.min(totalPages - 1, pi + BATCH_SIZE / 2)
          if (ns >= r.start && ne <= r.end) return r
          return { start: Math.min(r.start, ns), end: Math.max(r.end, ne) }
        })
      }
    }, { root: containerRef.current, rootMargin: '600px', threshold: 0.01 })

    const el = containerRef.current
    const elements = el.querySelectorAll('[data-page-index]')
    elements.forEach(child => observer.observe(child))
    return () => observer.disconnect()
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
        try {
          const res = await fetch('/api/v1/toc/render-page', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pdf_path: pdfPath, page }),
          })
          const d = await res.json()
          if (cancelled) return
          if (d.image) setLoadedPages(prev => new Map(prev).set(page, d.image))
        } catch { /* retry on next scroll */ }
      }
    }
    loadBatch()
    return () => { cancelled = true }
  }, [visibleRange, pdfPath])

  // Click to select page
  const handlePageClick = useCallback((pageIndex: number, e: React.MouseEvent) => {
    if (dragMode) return
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
  }, [selectedStart, selectedEnd, onSelectionChange, dragMode])

  // Drag to select range
  const handleMouseDown = (pageIndex: number) => {
    dragStartRef.current = pageIndex
    setDragMode(true)
    onSelectionChange(pageIndex, pageIndex)
  }

  useEffect(() => {
    if (!dragMode) return
    const onMove = (e: MouseEvent) => {
      const container = containerRef.current
      if (!container) return
      const rect = container.getBoundingClientRect()
      const y = e.clientY - rect.top + container.scrollTop
      const estimatedPageHeight = PAGE_WIDTH * 1.3 + 24
      const page = Math.floor(y / estimatedPageHeight)
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
                  alt={`Page ${i + 1}`}
                  draggable={false}
                />
              ) : (
                <div className="w-full bg-gray-200 dark:bg-gray-800 rounded-t animate-pulse flex items-center justify-center"
                  style={{ height: PAGE_WIDTH * 1.3 }}>
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
}
