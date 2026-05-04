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
            // Reset selection for new request
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

      ws.onclose = () => {
        reconnectTimer = setTimeout(connect, 3000)
      }

      ws.onerror = () => {
        ws?.close()
      }
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
      // If user selected a candidate, include its id/hash
      if (confirm && selectedCandidate && info.candidates) {
        const sel = info.candidates.find(c => c.id === selectedCandidate)
        if (sel) {
          body.book_id = sel.id
          body.book_hash = sel.hash
        }
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
    <div style={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 9999,
      background: '#fff', borderRadius: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
      padding: '20px 24px', maxWidth: 460, width: '100%',
      border: '1px solid #e5e7eb',
      maxHeight: '80vh', overflowY: 'auto',
    }}>
      <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
        ⚠️ 选择下载来源
      </div>

      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 12, lineHeight: 1.6 }}>
        <div><strong>书名：</strong>{info.title || '未知'}</div>
        {info.isbn && <div><strong>ISBN：</strong>{info.isbn}</div>}
        {info.authors.length > 0 && <div><strong>作者：</strong>{info.authors.join('、')}</div>}
        {info.publisher && <div><strong>出版社：</strong>{info.publisher}</div>}
      </div>

      {/* ZL candidates list */}
      {hasCandidates && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 6 }}>
            📚 在 Z-Library 找到以下书籍，请选择要下载的版本：
          </div>
          <div style={{ maxHeight: 260, overflowY: 'auto', border: '1px solid #e5e7eb', borderRadius: 8 }}>
            {info.candidates!.map((c) => (
              <div
                key={c.id}
                onClick={() => setSelectedCandidate(c.id)}
                style={{
                  padding: '10px 12px',
                  cursor: 'pointer',
                  background: selectedCandidate === c.id ? '#eff6ff' : '#fff',
                  borderBottom: '1px solid #f3f4f6',
                  borderLeft: selectedCandidate === c.id ? '3px solid #3b82f6' : '3px solid transparent',
                }}
              >
                <div style={{ fontSize: 13, fontWeight: 500, color: '#111827' }}>{c.title || '无标题'}</div>
                <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
                  {c.authors && <span>{c.authors} · </span>}
                  {c.year && <span>{c.year} · </span>}
                  {c.extension && <span>{c.extension.toUpperCase()} · </span>}
                  {c.size > 0 && <span>{(c.size / 1024 / 1024).toFixed(1)} MB · </span>}
                  <span style={{ color: '#9ca3af' }}>{TIER_LABELS[c.tier] || `第${c.tier}层`}</span>
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 6, padding: '6px 8px', background: '#fff7ed', borderRadius: 6, color: '#9a3412', fontSize: 12 }}>
            ⚡ 将消耗 Z-Library 每日下载额度。
            {selectedCandidate ? '已选择一本书。' : '请点击选择一本要下载的书。'}
          </div>
        </div>
      )}

      {!hasCandidates && (
        <div style={{ marginTop: 8, padding: 8, background: '#fff7ed', borderRadius: 6, color: '#9a3412', fontSize: 12 }}>
          ⚡ 将消耗 Z-Library 每日下载额度。确认继续？
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 8 }}>
        <button
          onClick={() => handleConfirm(false)}
          disabled={pending}
          style={{
            padding: '6px 16px', borderRadius: 6, border: '1px solid #d1d5db',
            background: '#fff', cursor: 'pointer', fontSize: 13,
          }}
        >
          跳过
        </button>
        <button
          onClick={() => handleConfirm(true)}
          disabled={pending || (hasCandidates && !selectedCandidate)}
          style={{
            padding: '6px 16px', borderRadius: 6, border: 'none',
            background: hasCandidates && !selectedCandidate ? '#d1d5db' : '#f97316',
            color: '#fff', cursor: hasCandidates && !selectedCandidate ? 'not-allowed' : 'pointer',
            fontSize: 13, fontWeight: 600,
          }}
        >
          {pending ? '处理中...' : hasCandidates ? '下载选中条目' : '确认下载'}
        </button>
      </div>
    </div>
  )
}
