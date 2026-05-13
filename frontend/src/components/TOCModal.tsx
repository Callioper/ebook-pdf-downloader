import { useState, useEffect } from 'react'
import PDFPageViewer from './PDFPageViewer'

interface Props {
  pdfPath: string
  visible: boolean
  onConfirm: (bookmark: string, offset: number) => void
  onCancel: () => void
}

export default function TOCModal({ pdfPath, visible, onConfirm, onCancel }: Props) {
  const [stage, setStage] = useState<'select' | 'extracting' | 'preview'>('select')
  const [startPage, setStartPage] = useState(0)
  const [endPage, setEndPage] = useState(5)
  const [totalPages, setTotalPages] = useState(0)
  const [pageImages, setPageImages] = useState<string[]>([])
  const [bookmark, setBookmark] = useState('')
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState('')
  const [previewImages, setPreviewImages] = useState(false)

  useEffect(() => {
    if (!visible || !pdfPath) return
    fetch('/api/v1/toc/info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_path: pdfPath }),
    })
      .then((r) => r.json())
      .then((d) => {
        setTotalPages(d.pages)
        if (d.pages < 10) setEndPage(d.pages - 1)
      })
      .catch(() => setError('无法获取 PDF 信息'))
  }, [visible, pdfPath])

  const loadPreviews = async () => {
    setPreviewImages(true)
    const res = await fetch('/api/v1/toc/render-pages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_path: pdfPath, start_page: startPage, end_page: endPage }),
    })
    const data = await res.json()
    setPageImages(data.pages || [])
  }

  const extract = async () => {
    setStage('extracting')
    setError('')
    const res = await fetch('/api/v1/toc/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pdf_path: pdfPath,
        start_page: startPage,
        end_page: endPage,
      }),
    })
    const data = await res.json()
    if (data.error) {
      setError(data.error)
      setStage('select')
      return
    }
    setBookmark(data.bookmark || '')
    setStage('preview')
  }

  if (!visible) return null

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg max-w-4xl w-full max-h-[90vh] overflow-auto p-6 shadow-xl">
        <h2 className="text-lg font-semibold mb-4 dark:text-gray-100">智能目录识别</h2>

        {error && (
          <div className="mb-3 p-2 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 rounded text-xs text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {stage === 'select' && (
          <>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
              点击页面设置起始页，Shift+点击设置结束页，或拖拽选择连续页面范围。已选: 第 {startPage >= 0 ? startPage + 1 : '?'} – {endPage >= 0 ? endPage + 1 : '?'} 页
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
              <input type="number" min={1} max={totalPages} value={startPage >= 0 ? startPage + 1 : 1}
                onChange={(e) => setStartPage(Math.max(0, Number(e.target.value) - 1))}
                className="w-16 border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-xs dark:bg-gray-700 dark:text-gray-100" />
              <span className="text-xs text-gray-400">–</span>
              <input type="number" min={1} max={totalPages} value={endPage >= 0 ? endPage + 1 : 1}
                onChange={(e) => setEndPage(Math.min(totalPages - 1, Number(e.target.value) - 1))}
                className="w-16 border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-xs dark:bg-gray-700 dark:text-gray-100" />
              <span className="text-xs text-gray-400">/ {totalPages} 页</span>
              <button onClick={loadPreviews}
                className="px-3 py-1 text-xs rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600">
                {previewImages ? '刷新预览' : '预览选中页'}
              </button>
            </div>

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

        {stage === 'extracting' && (
          <div className="text-center py-12">
            <div className="inline-block w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mb-4" />
            <p className="text-sm text-gray-500 dark:text-gray-400">正在调用视觉模型识别目录内容...</p>
          </div>
        )}

        {stage === 'preview' && (
          <>
            <div className="mb-4">
              <label className="text-xs font-medium text-gray-600 dark:text-gray-300 block mb-1">
                页码偏移: {offset > 0 ? `+${offset}` : offset}
              </label>
              <input type="range" min={-20} max={20} value={offset}
                onChange={(e) => setOffset(Number(e.target.value))}
                className="w-full" />
              <p className="text-[11px] text-gray-400 mt-0.5">
                若目录页数与正文实际页数不符，拖动滑块调整
              </p>
            </div>

            <pre className="text-xs bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded p-3 max-h-60 overflow-auto mb-4 dark:text-gray-200 font-mono">
              {bookmark.split('\n').slice(0, 30).map((line, i) => (
                <div key={i}>{line}</div>
              ))}
              {bookmark.split('\n').length > 30 && (
                <div className="text-gray-400">... 共 {bookmark.split('\n').length} 条</div>
              )}
            </pre>

            <div className="flex gap-2">
              <button onClick={() => onConfirm(bookmark, offset)}
                className="px-4 py-2 text-sm rounded bg-green-600 text-white hover:bg-green-700">
                确认添加 ({bookmark.split('\n').filter(l => l.trim()).length} 条)
              </button>
              <button onClick={() => { setStage('select'); setBookmark(''); }}
                className="px-4 py-2 text-sm rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600">
                重新选择
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
