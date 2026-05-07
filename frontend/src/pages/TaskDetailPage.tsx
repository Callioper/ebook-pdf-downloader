import { useEffect, useState, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import axios from 'axios'
import { API_BASE, PIPELINE_STEPS, STATUS_LABELS } from '../constants'
import type { TaskItem, AppConfig, WSMessage } from '../types'
import { statusBadge } from '../utils/statusBadge'
import { useTaskWebSocket } from '../hooks/useTaskWebSocket'
import StepProgressBar from '../components/StepProgressBar'
import LogStream from '../components/LogStream'
import TaskReport from '../components/TaskReport'
import TaskListPanel from '../components/TaskListPanel'

export default function TaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const [task, setTask] = useState<TaskItem | null>(null)
  const [loading, setLoading] = useState(true)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')
  const [cfg, setCfg] = useState<AppConfig | null>(null)

  useEffect(() => {
    axios.get(`${API_BASE}/config`).then(r => setCfg(r.data)).catch(() => {})
  }, [])

  const fetchTask = useCallback(async () => {
    if (!taskId) return
    try {
      const { data } = await axios.get(`${API_BASE}/tasks/${taskId}`)
      setTask(data)
      setLoading(false)
    } catch (e: any) {
      setError(e.message)
      setLoading(false)
    }
  }, [taskId])

  useEffect(() => {
    fetchTask()
    const interval = setInterval(fetchTask, 8000)
    return () => clearInterval(interval)
  }, [fetchTask])

  const lastProgressRef = useRef(0)
  const onUpdateRef = useRef<(t: TaskItem) => void>()

  const handleWSMessage = useCallback((msg: WSMessage) => {
    if (msg.type === 'task_update' && msg.task) {
      setTask((prev) => {
        const merged = prev ? { ...prev, ...msg.task } : (msg.task as TaskItem)
        if (merged.logs && merged.logs.length > 1000) {
          merged.logs = merged.logs.slice(-1000)
        }
        return merged
      })
    }
    if (msg.type === 'step_progress') {
      const now = Date.now()
      if (now - lastProgressRef.current < 500) {
        return
      }
      lastProgressRef.current = now
      setTask((prev) =>
        prev
          ? {
              ...prev,
              current_step: msg.step || prev.current_step,
              progress: msg.progress || prev.progress,
              step_detail: (msg.detail as string) || prev.step_detail,
              step_eta: (msg.eta as string) || prev.step_eta,
            }
          : prev
      )
    }
    if (msg.type === 'task_completed') {
      fetchTask()
    }
    if (msg.type === 'task_failed') {
      fetchTask()
    }
  }, [fetchTask])

  onUpdateRef.current = (t) => setTask((prev) => prev ? { ...prev, ...t } : t)

  const stableOnUpdate = useCallback((t: TaskItem) => {
    onUpdateRef.current?.(t)
  }, [])

  useTaskWebSocket({ taskId: taskId || null, onUpdate: stableOnUpdate, onMessage: handleWSMessage })

  const handleStart = async () => {
    if (!taskId) return
    setStarting(true)
    try {
      await axios.post(`${API_BASE}/tasks/${taskId}/start`)
      await fetchTask()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setStarting(false)
    }
  }

  const handleCancel = async () => {
    if (!taskId) return
    try {
      await axios.post(`${API_BASE}/tasks/${taskId}/cancel`)
      await fetchTask()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleRetry = async () => {
    if (!taskId) return
    try {
      await axios.post(`${API_BASE}/tasks/${taskId}/retry`)
      await fetchTask()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleOpenPdf = async () => {
    if (!taskId) return
    try {
      await axios.get(`${API_BASE}/tasks/${taskId}/open`)
    } catch (e: any) {
      alert('无法打开PDF: ' + e.message)
    }
  }

  const handleOpenFolder = async () => {
    if (!taskId) return
    try {
      await axios.get(`${API_BASE}/tasks/${taskId}/open-folder`)
    } catch (e: any) {
      alert('无法打开文件夹: ' + e.message)
    }
  }

  if (loading) {
    return <div className="text-center py-10 text-gray-400">加载中...</div>
  }

  if (error || !task) {
    return (
      <div className="text-center py-10">
        <p className="text-red-500 mb-4">{error || '任务未找到'}</p>
        <button
          onClick={() => navigate('/tasks')}
          className="text-blue-600 hover:text-blue-800 text-sm"
        >
          返回任务列表
        </button>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 space-y-4">
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-semibold text-gray-800">{task.title || '(无标题)'}</h2>
              {statusBadge(task.status)}
                {task.status === 'running' && task.step_eta && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-blue-50 text-blue-600 border border-blue-200">
                    <svg className="w-3 h-3 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    剩余 {task.step_eta}
                  </span>
                )}
              </div>
              <span className="text-xs text-gray-400">ID: {task.task_id}</span>
          </div>

          <div className="flex flex-wrap gap-x-6 gap-y-1 mb-4 text-xs text-gray-500">
            {task.isbn && <span>ISBN: {task.isbn}</span>}
            {task.ss_code && <span>SS: {task.ss_code}</span>}
            {task.book_id && <span>Book ID: {task.book_id}</span>}
            <span>来源: {task.source}</span>
            {task.publisher && <span>出版社: {task.publisher}</span>}
          </div>

          {error && (
            <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-600">
              {error}
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            {(task.status === 'pending') && (
              <button
                onClick={handleStart}
                disabled={starting}
                className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {starting ? '启动中...' : '开始任务'}
              </button>
            )}
            {(task.status === 'running') && (
              <button
                onClick={handleCancel}
                className="px-4 py-1.5 bg-yellow-600 text-white text-sm rounded-md hover:bg-yellow-700"
              >
                取消任务
              </button>
            )}
            {task.status === 'failed' && (
              <button
                onClick={handleRetry}
                className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded-md hover:bg-blue-700"
              >
                重试
              </button>
            )}
            {task.status === 'completed' && task.report?.pdf_path && (
              <button
                onClick={handleOpenPdf}
                className="px-4 py-1.5 bg-green-600 text-white text-sm rounded-md hover:bg-green-700"
              >
                打开PDF
              </button>
            )}
            {task.status === 'completed' && (
              <button
                onClick={handleOpenFolder}
                className="px-4 py-1.5 border border-gray-300 text-gray-700 text-sm rounded-md hover:bg-gray-50"
              >
                打开文件夹
              </button>
            )}
          </div>
        </div>

        <StepProgressBar task={task} />

        <div>
          <h4 className="text-sm font-semibold text-gray-700 mb-2">运行日志</h4>
          <LogStream logs={task.logs || []} />
        </div>

        <TaskReport report={task.report || {}} finishedDir={cfg?.finished_dir} createdAt={task.created_at} />
      </div>

      <div className="space-y-4">
        <TaskListPanel compact />
      </div>
    </div>
  )
}
