import { PIPELINE_STEPS } from '../constants'
import type { TaskItem } from '../types'

interface StepProgressBarProps {
  task: TaskItem
}

export default function StepProgressBar({ task }: StepProgressBarProps) {
  const currentStepIdx = PIPELINE_STEPS.findIndex((s) => s.key === task.current_step)

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <h4 className="text-xs font-semibold text-gray-600 mb-3">处理步骤</h4>
      <div className="flex items-center gap-0">
        {PIPELINE_STEPS.map((step, idx) => {
          const isDone = idx < currentStepIdx || (idx === currentStepIdx && task.status === 'completed')
          const isActive = idx === currentStepIdx && task.status === 'running'
          const isPending = idx > currentStepIdx || (task.status === 'pending' && idx > 0)
          const isFailed = idx === currentStepIdx && task.status === 'failed'

          return (
            <div key={step.key} className="flex-1 flex flex-col items-center">
              {idx > 0 && (
                <div className="absolute left-0 right-0 top-3 -z-10 flex h-0.5">
                  <div className={`flex-1 ${isDone || isActive ? 'bg-blue-400' : 'bg-gray-200'}`} />
                </div>
              )}
              <div className="relative flex flex-col items-center">
                <div
                  className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold ${
                    isFailed
                      ? 'bg-red-500 text-white'
                      : isDone
                      ? 'bg-green-500 text-white'
                      : isActive
                      ? 'bg-blue-500 text-white ring-2 ring-blue-200'
                      : 'bg-gray-200 text-gray-400'
                  }`}
                >
                  {isDone ? '✓' : idx + 1}
                </div>
                <span
                  className={`mt-1 text-xs text-center max-w-[80px] leading-tight ${
                    isActive ? 'text-blue-600 font-medium' : 'text-gray-400'
                  }`}
                >
                  {step.label}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
