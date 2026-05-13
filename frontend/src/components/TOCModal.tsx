import { useState, useEffect, useRef } from 'react'
import PDFPageViewer from './PDFPageViewer'

interface Props {
  pdfPath: string
  visible: boolean
  onCancel: () => void
  taskId?: string
  outputDir?: string
}

export default function TOCModal({ pdfPath, visible, onCancel, taskId, outputDir }: Props) {
  const [stage, setStage] = useState<'select' | 'extracting' | 'preview' | 'injecting' | 'done'>('select')
  const [injectMsg, setInjectMsg] = useState('')
  const [startPage, setStartPage] = useState(0)
  const [endPage, setEndPage] = useState(5)
  const [totalPages, setTotalPages] = useState(0)
  const [pageImages, setPageImages] = useState<string[]>([])
  const [bookmark, setBookmark] = useState('')
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState('')
  const [previewImages, setPreviewImages] = useState(false)
  const [previewPage, setPreviewPage] = useState(0)
  const [previewPageImg, setPreviewPageImg] = useState('')
  const [previewFullWidth, setPreviewFullWidth] = useState(false)
  const [alignedPage, setAlignedPage] = useState<number | null>(null)
  const [firstBookmarkPage, setFirstBookmarkPage] = useState(1)
  const previewBlobRef = useRef<string>('')

  useEffect(() => {
    return () => { if (previewBlobRef.current) URL.revokeObjectURL(previewBlobRef.current) }
  }, [])  // 1-indexed, extracted from bookmark line 1

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

  const loadPreviewPage = async (page: number) => {
    const clamped = Math.max(0, Math.min(totalPages - 1, page))
    setPreviewPage(clamped)
    const res = await fetch('/api/v1/toc/render-page', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pdf_path: pdfPath, page: clamped, dpi: 120 }),
    })
    if (res.ok) {
      const blob = await res.blob()
      if (previewBlobRef.current) URL.revokeObjectURL(previewBlobRef.current)
      const url = URL.createObjectURL(blob)
      previewBlobRef.current = url
      setPreviewPageImg(url)
    }
  }

  const extract = async () => {
    setStage('extracting')
    setError('')
    setAlignedPage(null)
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
    const lines = (data.bookmark || '').split('\n')
    const firstLine = lines[0] || ''
    const fields = firstLine.split('\t')
    const pageStr = fields.length >= 2 ? fields[1] : firstLine
    const pageMatch = pageStr.match(/^\s*(\d+)/)
    const firstAdvertisedPage = pageMatch ? parseInt(pageMatch[1], 10) - 1 : 0
    setFirstBookmarkPage(pageMatch ? parseInt(pageMatch[1], 10) : 1)
    setPreviewPage(firstAdvertisedPage)
    loadPreviewPage(firstAdvertisedPage)
    setStage('preview')
  }

  const handleInject = async () => {
    setStage('injecting')
    setInjectMsg('')
    const finalBookmark = buildFinalBookmark()
    try {
      const r = await fetch('/api/v1/toc/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pdf_path: pdfPath, bookmark: finalBookmark, offset }),
      })
      const d = await r.json()
      if (d.ok) {
        setInjectMsg(d.message || '完成')
        setStage('done')
        // Notify pipeline that user confirmed TOC injection
        if (taskId) {
          fetch('/api/v1/toc/notify-done', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_id: taskId }),
          }).catch(() => {})
        }
      } else {
        setError(d.message || '注入失败')
        setStage('preview')
      }
    } catch (e) {
      setError(String(e))
      setStage('preview')
    }
  }

  const buildFinalBookmark = (): string => {
    let lines: string[] = []
    if (startPage >= 0 && endPage >= startPage) {
      for (let i = startPage; i <= endPage; i++) {
        lines.push(`目录\t${i + 1}\t-1`)  // level -1 = absolute page, no offset
      }
    }
    for (const line of bookmark.split('\n')) {
      if (line.trim()) lines.push(line)
    }
    return lines.join('\n')
  }

  if (!visible) return null

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
      <div className="bg-white dark:bg-gray-800 rounded-lg max-w-5xl w-full max-h-[90vh] overflow-auto p-6 shadow-xl">
        <h2 className="text-lg font-semibold mb-4 dark:text-gray-100 flex items-center justify-between">
          <span>智能目录识别</span>
          <button onClick={onCancel}
            className="text-xs px-2 py-1 rounded border border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700">
            关闭
          </button>
        </h2>

        {error && (
          <div className="mb-3 p-2 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 rounded text-xs text-red-600 dark:text-red-400">
            {error}
          </div>
        )}

        {stage === 'select' && (
          <>
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
              选择<strong>目录页</strong>所在的页面范围（点击第一页开始，再点最后一页完成选择）。已选: 第 {startPage >= 0 ? startPage + 1 : '?'} – {endPage >= 0 ? endPage + 1 : '?'} 页
            </p>

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

            <div className="flex items-center gap-2 mt-3 mb-1">
              <span className="text-xs text-gray-600 dark:text-gray-300">页码:</span>
              <input type="number" min={1} max={totalPages} value={startPage >= 0 ? startPage + 1 : ''}
                onChange={(e) => { const v = Number(e.target.value); setStartPage(v > 0 ? Math.min(totalPages - 1, Math.max(0, v - 1)) : -1) }}
                className="w-16 border border-gray-300 dark:border-gray-600 rounded px-2 py-1 text-xs dark:bg-gray-700 dark:text-gray-100" />
              <span className="text-xs text-gray-400">–</span>
              <input type="number" min={1} max={totalPages} value={endPage >= 0 ? endPage + 1 : ''}
                onChange={(e) => { const v = Number(e.target.value); setEndPage(v > 0 ? Math.min(totalPages - 1, Math.max(0, v - 1)) : -1) }}
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
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">正在调用视觉模型识别目录内容...</p>
            <button onClick={onCancel}
              className="px-4 py-1.5 text-xs rounded border border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700">
              关闭
            </button>
          </div>
        )}

        {stage === 'preview' && (
          <>
            <div className="mb-3 p-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-700 rounded text-xs text-blue-700 dark:text-blue-300">
              请将右边 PDF 翻到<strong>第一条书签</strong>对应的实际页面，然后点击「以此为第一页」确认偏移量。
              {alignedPage !== null && (
                <span className="ml-2 text-green-700 dark:text-green-300">
                  ✓ 已定位 — 第 {alignedPage + 1} 页（偏移 {(alignedPage + 1) - firstBookmarkPage}）
                </span>
              )}
            </div>

            <div className={`flex gap-3 ${previewFullWidth ? 'flex-col' : ''}`}>
              {/* Left: bookmark text */}
              <div className={`${previewFullWidth ? 'w-full' : 'w-1/2'}`}>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-medium text-gray-600 dark:text-gray-300">提取的目录</label>
                  <button type="button"
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
                    <button type="button" onClick={() => loadPreviewPage(previewPage - 1)} disabled={previewPage <= 0}
                      className="px-1.5 py-0.5 text-xs rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-30">
                      −
                    </button>
                    <input type="number" min={1} max={totalPages} value={previewPage + 1}
                      onChange={(e) => loadPreviewPage(Number(e.target.value) - 1)}
                      className="w-16 border border-gray-300 dark:border-gray-600 rounded px-2 py-0.5 text-xs text-center dark:bg-gray-700 dark:text-gray-100" />
                    <span className="text-xs text-gray-400">/ {totalPages}</span>
                    <button type="button" onClick={() => loadPreviewPage(previewPage + 1)} disabled={previewPage >= totalPages - 1}
                      className="px-1.5 py-0.5 text-xs rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700 disabled:opacity-30">
                      +
                    </button>
                    <button type="button"
                      onClick={() => { setAlignedPage(previewPage); setOffset((previewPage + 1) - firstBookmarkPage) }}
                      className="ml-2 px-2 py-0.5 text-xs rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-900/60 border border-blue-300 dark:border-blue-600">
                      以此为第一页
                    </button>
                  </div>
                </div>
                {previewPageImg ? (
                  <div className="bg-gray-100 dark:bg-gray-900 border border-gray-200 dark:border-gray-600 rounded overflow-hidden flex items-center justify-center"
                    style={{ maxHeight: previewFullWidth ? '40vh' : '60vh' }}>
                    <img src={previewPageImg}
                      className="max-w-full max-h-full object-contain"
                      alt={`Page ${previewPage + 1}`}
                      draggable={false} />
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

            <div className="mt-3 mb-1">
              <label className="text-xs font-medium text-gray-600 dark:text-gray-300 block mb-1">
                页码偏移: {offset > 0 ? `+${offset}` : offset}
              </label>
              <input type="range" min={-50} max={50} value={offset}
                onChange={(e) => setOffset(Number(e.target.value))}
                className="w-full" />
            </div>

            <div className="flex gap-2">
              <button onClick={handleInject}
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

        {stage === 'injecting' && (
          <div className="text-center py-12">
            <div className="inline-block w-8 h-8 border-2 border-green-500 border-t-transparent rounded-full animate-spin mb-4" />
            <p className="text-sm text-gray-500 dark:text-gray-400 mb-4">正在注入书签...</p>
            <button onClick={onCancel}
              className="px-4 py-1.5 text-xs rounded border border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700">
              关闭
            </button>
          </div>
        )}

        {stage === 'done' && (
          <div className="text-center py-8">
            <div className="text-4xl mb-3">✅</div>
            <p className="text-sm font-medium text-green-700 dark:text-green-300 mb-6">{injectMsg}</p>
            <div className="flex justify-center gap-3">
              <button onClick={() => fetch('/api/v1/toc/open-pdf', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pdf_path: pdfPath }) })}
                className="px-4 py-2 text-sm rounded bg-blue-600 text-white hover:bg-blue-700">
                打开 PDF
              </button>
              <button onClick={() => {
                const dir = outputDir || pdfPath
                fetch('/api/v1/toc/open-folder', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pdf_path: dir }) })
              }}
                className="px-4 py-2 text-sm rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 border border-gray-300 dark:border-gray-600">
                打开文件夹
              </button>
              <button onClick={onCancel}
                className="px-4 py-2 text-sm rounded bg-gray-200 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600">
                关闭
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
