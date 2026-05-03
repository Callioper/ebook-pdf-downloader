import { useEffect, useRef, useCallback } from 'react'
import type { TaskItem, WSMessage } from '../types'

interface UseTaskWebSocketOptions {
  taskId: string | null
  onUpdate?: (task: TaskItem) => void
  onMessage?: (msg: WSMessage) => void
}

export function useTaskWebSocket({ taskId, onUpdate, onMessage }: UseTaskWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>()

  const connect = useCallback(() => {
    if (!taskId) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/api/v1/ws`

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'subscribe', task_id: taskId }))

        const pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)

        ws.addEventListener('close', () => {
          clearInterval(pingInterval)
        })
      }

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data)
          onMessage?.(msg)

          if (msg.type === 'task_update' && msg.task) {
            onUpdate?.(msg.task)
          }
          if (msg.type === 'task_completed' && msg.task) {
            onUpdate?.(msg.task)
          }
          if (msg.type === 'step_progress' && msg.task_id === taskId) {
            if (onUpdate) {
              const pendingTask: Partial<TaskItem> = {
                task_id: taskId,
                current_step: msg.step || '',
                progress: msg.progress || 0,
              } as TaskItem
              onUpdate(pendingTask as TaskItem)
            }
          }
        } catch {}
      }

      ws.onerror = () => {
        reconnectTimer.current = setTimeout(connect, 3000)
      }

      ws.onclose = () => {
        reconnectTimer.current = setTimeout(connect, 3000)
      }
    } catch {
      reconnectTimer.current = setTimeout(connect, 3000)
    }
  }, [taskId, onUpdate, onMessage])

  useEffect(() => {
    connect()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  return wsRef
}
