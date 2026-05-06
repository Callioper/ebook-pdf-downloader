import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useStore } from '../stores/useStore'
import { API_BASE, STATUS_LABELS } from '../constants'
import { statusBadge } from '../utils/statusBadge'

export default function TaskListPage() {
  const navigate = useNavigate()
  const tasks = useStore((s) => s.tasks)
  const fetchTasks = useStore((s) => s.fetchTasks)
  const setError = useStore((s) => s.setError)

  useEffect(() => {
    fetchTasks()
    const interval = setInterval(fetchTasks, 5000)
    return () => clearInterval(interval)
  }, [fetchTasks])

  const handleClearCompleted = async () => {
    try {
      await axios.delete(`${API_BASE}/tasks/completed`)
      fetchTasks()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleClearAll = async () => {
    if (!confirm('确定要清空所有任务？')) return
    try {
      await axios.delete(`${API_BASE}/tasks`)
      fetchTasks()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleDelete = async (taskId: string) => {
    try {
      await axios.delete(`${API_BASE}/tasks/${taskId}`)
      fetchTasks()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleRetry = async (taskId: string) => {
    try {
      await axios.post(`${API_BASE}/tasks/${taskId}/retry`)
      fetchTasks()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const handleCancel = async (taskId: string) => {
    try {
      await axios.post(`${API_BASE}/tasks/${taskId}/cancel`)
      fetchTasks()
    } catch (e: any) {
      setError(e.message)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-gray-800">
          任务列表 ({tasks.length})
        </h2>
        <div className="flex gap-2">
          <button
            onClick={handleClearCompleted}
            className="px-3 py-1.5 text-xs border border-gray-300 rounded-md text-gray-600 hover:bg-gray-50"
          >
            清除已完成
          </button>
          <button
            onClick={handleClearAll}
            className="px-3 py-1.5 text-xs border border-red-300 rounded-md text-red-600 hover:bg-red-50"
          >
            清空全部
          </button>
        </div>
      </div>

      {tasks.length === 0 ? (
        <div className="text-center py-10 text-gray-400">暂无任务</div>
      ) : (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                <th className="text-left px-4 py-2 text-xs font-medium text-gray-500">状态</th>
                <th className="text-left px-4 py-2 text-xs font-medium text-gray-500">书名</th>
                <th className="text-left px-4 py-2 text-xs font-medium text-gray-500">进度</th>
                <th className="text-left px-4 py-2 text-xs font-medium text-gray-500">来源</th>
                <th className="text-left px-4 py-2 text-xs font-medium text-gray-500">时间</th>
                <th className="text-right px-4 py-2 text-xs font-medium text-gray-500">操作</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => (
                <tr
                  key={task.task_id}
                  className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer"
                  onClick={() => navigate(`/tasks/${task.task_id}`)}
                >
                  <td className="px-4 py-3">{statusBadge(task.status)}</td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-gray-800 truncate block max-w-[300px]">
                      {task.title || '(无标题)'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-blue-500 rounded-full transition-all"
                          style={{ width: `${task.progress}%` }}
                        />
                      </div>
                      <div className="flex flex-col">
                        <span className="text-xs text-gray-400">{task.progress}%</span>
                        {task.status === 'running' && task.step_eta && (
                          <span className="text-[10px] text-gray-400 whitespace-nowrap">
                            {task.step_eta}
                          </span>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{task.source}</td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {new Date(task.created_at * 1000).toLocaleString('zh-CN', { hour12: false })}
                  </td>
                  <td className="px-4 py-3 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                      {task.status === 'failed' && (
                        <button
                          onClick={() => handleRetry(task.task_id)}
                          className="text-xs text-blue-600 hover:text-blue-800 px-1"
                        >
                          重试
                        </button>
                      )}
                      {(task.status === 'pending' || task.status === 'running') && (
                        <button
                          onClick={() => handleCancel(task.task_id)}
                          className="text-xs text-yellow-600 hover:text-yellow-800 px-1"
                        >
                          取消
                        </button>
                      )}
                      {task.status !== 'running' && (
                        <button
                          onClick={() => handleDelete(task.task_id)}
                          className="text-xs text-red-500 hover:text-red-700 px-1"
                        >
                          删除
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
