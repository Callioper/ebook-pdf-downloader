import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../constants'

interface ZLCandidate {
  id: string
  hash: string
  title: string
  authors: string
  publisher: string
  year: string
  extension: string
  size: number
  tier: number
  strategy: string
}

interface ConfirmInfo {
  task_id: string
  key: string
  title: string
  isbn: string
  authors: string[]
  publisher: string
  download_source: string
  file_size: string
  candidates?: ZLCandidate[]
}

const TIER_LABELS: Record<number, string> = {
  1: 'ISBN 精确匹配',
  2: '书名+作者',
  3: '书名检索',
}

export default function ConfirmDownloadModal() {
  const [info, setInfo] = useState<ConfirmInfo | null>(null)
  const [pending, setPending] = useState(false)
  const [selectedCandidate, setSelectedCandidate] = useState<string | null>(null)

  const wsUrl = API_BASE.replace(/^http/, 'ws') + '/ws?client_id=confirm_modal'

  useEffect(() => {
    let ws: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    function connect() {
      try {
        ws = new WebSocket(wsUrl)
      } catch {
        reconnectTimer = setTimeout(connect, 3000)
        return
      }

      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data)
          if (data.type === 'confirm_download') {
            setSelectedCandidate(null)
            setInfo({
              task_id: data.task_id,
              key: data.key || 'zl_confirm',
              title: data.title || '',
              isbn: data.isbn || '',
              authors: data.authors || [],
              publisher: data.publisher || '',
              download_source: data.download_source || '',
              file_size: data.file_size || '',
              candidates: data.candidates || undefined,
            })
          }
        } catch { /* ignore */ }
      }

      ws.onclose = () => { reconnectTimer = setTimeout(connect, 3000) }
      ws.onerror = () => { ws?.close() }
    }

    connect()
    return () => {
      if (reconnectTimer) clearTimeout(reconnectTimer)
      ws?.close()
    }
  }, [wsUrl])

  const handleConfirm = useCallback(async (confirm: boolean) => {
    if (!info || pending) return
    setPending(true)
    try {
      const body: Record<string, unknown> = { confirm }
      if (confirm && selectedCandidate && info.candidates) {
        const sel = info.candidates.find(c => c.id === selectedCandidate)
        if (sel) { body.book_id = sel.id; body.book_hash = sel.hash }
      }
      await fetch(`${API_BASE}/tasks/${info.task_id}/confirm-download`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
    } catch { /* ignore */ }
    setInfo(null)
    setPending(false)
  }, [info, pending, selectedCandidate])

  if (!info) return null

  const hasCandidates = info.candidates && info.candidates.length > 0

  return (
    <div className="fixed bottom-6 right-6 z-[9999] bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 p-5 max-w-[460px] w-full max-h-[80vh] overflow-y-auto">
      <div className="text-base font-semibold mb-3 dark:text-gray-100">
        ⚠️ 选择下载来源
      </div>

      <div className="text-sm text-gray-500 dark:text-gray-400 mb-3 leading-relaxed">
        <div><strong className="dark:text-gray-300">书名：</strong>{info.title || '未知'}</div>
        {info.isbn && <div><strong className="dark:text-gray-300">ISBN：</strong>{info.isbn}</div>}
        {info.authors.length > 0 && <div><strong className="dark:text-gray-300">作者：</strong>{info.authors.join('、')}</div>}
        {info.publisher && <div><strong className="dark:text-gray-300">出版社：</strong>{info.publisher}</div>}
      </div>

      {hasCandidates && (
        <div className="mb-3">
          <div className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-1.5">
            📚 在 Z-Library 找到以下书籍，请选择要下载的版本：
          </div>
          <div className="max-h-[260px] overflow-y-auto border border-gray-200 dark:border-gray-600 rounded-lg">
            {info.candidates!.map((c) => (
              <div
                key={c.id}
                onClick={() => setSelectedCandidate(c.id)}
                className={`p-2.5 cursor-pointer border-b border-gray-100 dark:border-gray-700 last:border-b-0
                  ${selectedCandidate === c.id
                    ? 'bg-blue-50 dark:bg-blue-900/20 border-l-[3px] border-l-blue-500'
                    : 'bg-white dark:bg-gray-800 border-l-[3px] border-l-transparent hover:bg-gray-50 dark:hover:bg-gray-750'}`}
              >
                <div className="text-sm font-medium text-gray-900 dark:text-gray-100">{c.title || '无标题'}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {c.authors && <span>{c.authors} · </span>}
                  {c.year && <span>{c.year} · </span>}
                  {c.extension && <span>{c.extension.toUpperCase()} · </span>}
                  {c.size > 0 && <span>{(c.size / 1024 / 1024).toFixed(1)} MB · </span>}
                  <span className="text-gray-400 dark:text-gray-500">{TIER_LABELS[c.tier] || `第${c.tier}层`}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-1.5 p-2 bg-amber-50 dark:bg-amber-900/20 rounded-md text-amber-800 dark:text-amber-300 text-xs">
            ⚡ 将消耗 Z-Library 每日下载额度。
            {selectedCandidate ? '已选择一本书。' : '请点击选择一本要下载的书。'}
          </div>
        </div>
      )}

      {!hasCandidates && (
        <div className="mt-2 p-2 bg-amber-50 dark:bg-amber-900/20 rounded-md text-amber-800 dark:text-amber-300 text-xs">
          ⚡ 将消耗 Z-Library 每日下载额度。确认继续？
        </div>
      )}

      <div className="flex gap-2 justify-end mt-2">
        <button
          onClick={() => handleConfirm(false)}
          disabled={pending}
          className="px-4 py-1.5 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 text-sm"
        >
          跳过
        </button>
        <button
          onClick={() => handleConfirm(true)}
          disabled={pending || (hasCandidates && !selectedCandidate)}
          className={`px-4 py-1.5 rounded-md text-white text-sm font-semibold disabled:opacity-50
            ${hasCandidates && !selectedCandidate
              ? 'bg-gray-400 dark:bg-gray-600 cursor-not-allowed'
              : 'bg-orange-500 hover:bg-orange-600 cursor-pointer'}`}
        >
          {pending ? '处理中...' : hasCandidates ? '下载选中条目' : '确认下载'}
        </button>
      </div>
    </div>
  )
}
