import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import type { TaskItem } from '../types'
import { useStore } from '../stores/useStore'
import { statusBadge } from '../utils/statusBadge'
import { PIPELINE_STEPS, STATUS_LABELS } from '../constants'

interface TaskListPanelProps {
  compact?: boolean
}

export default function TaskListPanel({ compact }: TaskListPanelProps) {
  const navigate = useNavigate()
  const tasks = useStore((s) => s.tasks)
  const fetchTasks = useStore((s) => s.fetchTasks)

  useEffect(() => {
    fetchTasks()
    const interval = setInterval(fetchTasks, 5000)
    return () => clearInterval(interval)
  }, [fetchTasks])

  const activeTasks = tasks.filter((t) => t.status === 'pending' || t.status === 'running')
  const recentTasks = tasks.slice(0, compact ? 5 : tasks.length)

  return (
    <div className="space-y-4">

      {activeTasks.length > 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">
            进行中 ({activeTasks.length})
          </h3>
          <div className="space-y-2">
            {activeTasks.map((task) => (
              <TaskRow key={task.task_id} task={task} onClick={() => navigate(`/tasks/${task.task_id}`)} />
            ))}
          </div>
        </div>
      )}

      {!compact && (
        <div className="bg-white rounded-lg border border-gray-200 p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-gray-700">
              所有任务 ({tasks.length})
            </h3>
            <button
              onClick={() => navigate('/tasks')}
              className="text-xs text-blue-600 hover:text-blue-800"
            >
              查看全部
            </button>
          </div>
          {recentTasks.length === 0 ? (
            <p className="text-xs text-gray-400">暂无任务</p>
          ) : (
            <div className="space-y-2">
              {recentTasks.map((task) => (
                <TaskRow key={task.task_id} task={task} onClick={() => navigate(`/tasks/${task.task_id}`)} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function TaskRow({ task, onClick }: { task: TaskItem; onClick: () => void }) {
  const stepLabel = PIPELINE_STEPS.find((s) => s.key === task.current_step)?.label || task.current_step

  return (
    <div
      onClick={onClick}
      className="flex items-center gap-3 p-2 rounded-md hover:bg-gray-50 cursor-pointer border border-gray-100"
    >
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-800 truncate">{task.title || '(无标题)'}</p>
        <div className="flex items-center gap-2 mt-0.5">
          {statusBadge(task.status)}
          {task.status === 'running' && stepLabel && (
            <span className="text-xs text-gray-400">{stepLabel}</span>
          )}
        </div>
      </div>
      {task.status === 'running' && (
        <div className="w-16">
          <div className="h-1.5 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-500"
              style={{ width: `${task.progress}%` }}
            />
          </div>
          <p className="text-xs text-gray-400 text-center mt-0.5">{task.progress}%</p>
        </div>
      )}
    </div>
  )
}
