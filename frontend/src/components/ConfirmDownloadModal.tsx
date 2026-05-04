import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../constants'

interface ConfirmInfo {
  task_id: string
  key: string
  title: string
  isbn: string
  authors: string[]
  publisher: string
  download_source: string
  file_size: string
}

export default function ConfirmDownloadModal() {
  const [info, setInfo] = useState<ConfirmInfo | null>(null)
  const [pending, setPending] = useState(false)

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
            setInfo({
              task_id: data.task_id,
              key: data.key || 'zl_confirm',
              title: data.title || '',
              isbn: data.isbn || '',
              authors: data.authors || [],
              publisher: data.publisher || '',
              download_source: data.download_source || '',
              file_size: data.file_size || '',
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
      await fetch(`${API_BASE}/tasks/${info.task_id}/confirm-download`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm }),
      })
    } catch { /* ignore */ }
    setInfo(null)
    setPending(false)
  }, [info, pending])

  if (!info) return null

  return (
    <div style={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 9999,
      background: '#fff', borderRadius: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
      padding: '20px 24px', maxWidth: 400, width: '100%',
      border: '1px solid #e5e7eb',
    }}>
      <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
        ⚠️ 确认下载消耗
      </div>

      <div style={{ fontSize: 13, color: '#6b7280', marginBottom: 12, lineHeight: 1.6 }}>
        <div><strong>书名：</strong>{info.title || '未知'}</div>
        {info.isbn && <div><strong>ISBN：</strong>{info.isbn}</div>}
        {info.authors.length > 0 && <div><strong>作者：</strong>{info.authors.join('、')}</div>}
        {info.publisher && <div><strong>出版社：</strong>{info.publisher}</div>}
        <div style={{ marginTop: 8, padding: 8, background: '#fff7ed', borderRadius: 6, color: '#9a3412', fontSize: 12 }}>
          ⚡ 将消耗 Z-Library 每日下载额度。确认继续？
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
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
          disabled={pending}
          style={{
            padding: '6px 16px', borderRadius: 6, border: 'none',
            background: '#f97316', color: '#fff', cursor: 'pointer', fontSize: 13, fontWeight: 600,
          }}
        >
          {pending ? '处理中...' : '确认下载'}
        </button>
      </div>
    </div>
  )
}
