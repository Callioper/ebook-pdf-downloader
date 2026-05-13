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
