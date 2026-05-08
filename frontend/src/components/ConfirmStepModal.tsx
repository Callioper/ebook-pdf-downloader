import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../constants'

interface ConfirmStepInfo {
  task_id: string
  step_name: string
  step_label: string
  config_info: Record<string, string>
}

const STEP_ICONS: Record<string, string> = {
  ocr: '🔍',
  bookmark: '📑',
}

export default function ConfirmStepModal() {
  const [info, setInfo] = useState<ConfirmStepInfo | null>(null)
  const [pending, setPending] = useState(false)

  const wsUrl = API_BASE.replace(/^http/, 'ws') + '/ws?client_id=confirm_step_modal'

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
          if (data.type === 'confirm_step') {
            setInfo({
              task_id: data.task_id,
              step_name: data.step_name,
              step_label: data.step_label,
              config_info: data.config_info || {},
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
      await fetch(`${API_BASE}/tasks/${info.task_id}/confirm-step`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm }),
      })
    } catch { /* ignore */ }
    setInfo(null)
    setPending(false)
  }, [info, pending])

  if (!info) return null

  const icon = STEP_ICONS[info.step_name] || '⚙'
  const configEntries = Object.entries(info.config_info)

  return (
    <div style={{
      position: 'fixed', bottom: 24, right: 24, zIndex: 9999,
      background: '#fff', borderRadius: 12, boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
      padding: '20px 24px', maxWidth: 420, width: '100%',
      border: '1px solid #e5e7eb',
      maxHeight: '80vh', overflowY: 'auto',
    }}>
      <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 12 }}>
        {icon} {info.step_label}
      </div>

      <div style={{ marginBottom: 12, padding: '10px 12px', background: '#f0f9ff', borderRadius: 8, fontSize: 13, color: '#1e40af', lineHeight: 1.6 }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>当前配置</div>
        {configEntries.map(([key, value]) => (
          <div key={key} style={{ display: 'flex', gap: 8, marginBottom: 2 }}>
            <span style={{ color: '#6b7280', minWidth: 80 }}>{key}</span>
            <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{value || '-'}</span>
          </div>
        ))}
      </div>

      <div style={{ marginBottom: 12, padding: 8, background: '#fff7ed', borderRadius: 6, color: '#9a3412', fontSize: 12 }}>
        ⏱ 超时 300 秒后自动跳过此步骤。
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
            background: '#2563eb', color: '#fff', cursor: 'pointer',
            fontSize: 13, fontWeight: 600,
          }}
        >
          {pending ? '处理中...' : '确认执行'}
        </button>
      </div>
    </div>
  )
}
