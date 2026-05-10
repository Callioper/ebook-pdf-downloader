import { PIPELINE_STEPS } from '../constants'
import type { TaskItem } from '../types'

interface StepProgressBarProps {
  task: TaskItem
}

export default function StepProgressBar({ task }: StepProgressBarProps) {
  const currentStepIdx = PIPELINE_STEPS.findIndex((s) => s.key === task.current_step)

  const stepProgress = (idx: number): number => {
    if (idx < currentStepIdx) return 100
    if (idx > currentStepIdx) return 0
    if (task.status === 'completed') return 100
    return task.progress ?? 0
  }

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-xs font-semibold text-gray-600">处理步骤</h4>
        {task.step_detail && (
          <span className="text-xs text-gray-500 truncate max-w-[200px]">
            {task.step_detail}
          </span>
        )}
      </div>

      <div className="flex items-center gap-0">
        {PIPELINE_STEPS.map((step, idx) => {
          const isDone = idx < currentStepIdx || (idx === currentStepIdx && task.status === 'completed')
          const isActive = idx === currentStepIdx && task.status === 'running'
          const isFailed = idx === currentStepIdx && task.status === 'failed'

          return (
            <div key={step.key} className="flex-1 flex flex-col items-center relative">
              {idx > 0 && (
                <div className="absolute" style={{ left: '-50%', right: '50%', top: 12, height: 2, zIndex: 0 }}>
                  {isDone ? (
                    <div className="h-full bg-green-500 transition-all duration-500" style={{ width: '100%' }} />
                  ) : isActive ? (
                    <>
                      <div className="h-full bg-blue-400 transition-all duration-500" style={{ width: `${stepProgress(idx)}%` }} />
                      <div className="h-full bg-gray-200" style={{ width: `${100 - stepProgress(idx)}%` }} />
                    </>
                  ) : (
                    <div className="h-full bg-gray-200" style={{ width: '100%' }} />
                  )}
                </div>
              )}

              <div className="relative z-10 flex flex-col items-center">
                <div
                  className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold transition-all ${
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
                <span className={`mt-1 text-[10px] text-center max-w-[72px] leading-tight ${isActive ? 'text-blue-600 font-medium' : 'text-gray-400'}`}>
                  {step.label}
                </span>
              </div>
            </div>
          )
        })}
      </div>

      {task.status === 'running' && currentStepIdx >= 0 && (
        <div className="mt-3">
          {task.stage && (
            <div className="flex items-center justify-between mb-1">
              <span className="text-[11px] text-gray-500">
                {task.stage === 'convert' ? 'PDF 光栅化' : task.stage === 'detect' ? '版面检测' : task.stage === 'ocr' ? 'LLM 逐框识别' : task.stage === 'refine' ? '补漏重识别' : task.stage === 'embed' ? '嵌入文字层' : task.stage}
              </span>
              <span className="text-[11px] text-gray-400">{task.stage_progress ?? 0}%</span>
            </div>
          )}
          {task.stage && (
            <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden mb-2">
              <div className="h-full bg-blue-400 rounded-full transition-all duration-300" style={{ width: `${task.stage_progress ?? 0}%` }} />
            </div>
          )}
          <div className="flex items-center justify-between mb-1">
            <span className="text-[11px] text-gray-500">
              {task.stage ? '总体进度' : `${PIPELINE_STEPS[currentStepIdx]?.label} 进度`}
            </span>
            <span className="text-[11px] text-gray-400">{stepProgress(currentStepIdx)}%</span>
          </div>
          <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
            <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${stepProgress(currentStepIdx)}%` }} />
          </div>
          {task.step_eta && (
            <div className="flex items-center gap-1 mt-1">
              <svg className="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="text-[11px] text-gray-400">预计剩余 {task.step_eta}</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
