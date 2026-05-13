import { useState, useEffect, useCallback } from 'react'
import { API_BASE } from '../constants'
import { playNotificationSound } from '../utils/sound'

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
            playNotificationSound()
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
    <div className="fixed bottom-6 right-6 z-[9999] bg-white dark:bg-gray-800 rounded-xl shadow-2xl border border-gray-200 dark:border-gray-700 p-5 max-w-[420px] w-full max-h-[80vh] overflow-y-auto">
      <div className="text-base font-semibold mb-3 dark:text-gray-100">
        {icon} {info.step_label}
      </div>

      <div className="mb-3 p-2.5 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-sm text-blue-700 dark:text-blue-300 leading-relaxed">
        <div className="font-semibold mb-1.5 dark:text-blue-200">当前配置</div>
        {configEntries.map(([key, value]) => (
          <div key={key} className="flex gap-2 mb-0.5">
            <span className="text-gray-500 dark:text-gray-400 min-w-[80px]">{key}</span>
            <span className="font-mono text-xs dark:text-blue-200">{value || '-'}</span>
          </div>
        ))}
      </div>

      <div className="mb-3 p-2 bg-amber-50 dark:bg-amber-900/20 rounded-md text-amber-800 dark:text-amber-300 text-xs">
        ⏱ 超时 300 秒后自动跳过此步骤。
      </div>

      <div className="flex gap-2 justify-end">
        <button
          onClick={() => handleConfirm(false)}
          disabled={pending}
          className="px-4 py-1.5 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-600 disabled:opacity-50 text-sm"
        >
          跳过
        </button>
        <button
          onClick={() => handleConfirm(true)}
          disabled={pending}
          className="px-4 py-1.5 rounded-md bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 text-sm font-semibold"
        >
          {pending ? '处理中...' : '确认执行'}
        </button>
      </div>
    </div>
  )
}
