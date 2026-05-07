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
  const pingIntervalRef = useRef<ReturnType<typeof setInterval>>()
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const connect = useCallback(() => {
    if (!taskId) return
    if (wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/api/v1/ws`

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: 'subscribe', task_id: taskId }))

        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }))
          }
        }, 30000)
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
                step_detail: msg.detail as string | undefined,
                step_eta: msg.eta as string | undefined,
              } as TaskItem
              onUpdate(pendingTask as TaskItem)
            }
          }
        } catch {}
      }

      ws.onerror = () => {
        if (mountedRef.current) {
          reconnectTimer.current = setTimeout(connect, 3000)
        }
      }

      ws.onclose = () => {
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current)
        if (mountedRef.current) {
          reconnectTimer.current = setTimeout(connect, 3000)
        }
      }
    } catch {
      if (mountedRef.current) {
        reconnectTimer.current = setTimeout(connect, 3000)
      }
    }
  }, [taskId, onUpdate, onMessage])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectTimer.current)
      clearInterval(pingIntervalRef.current)
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  return wsRef
}
