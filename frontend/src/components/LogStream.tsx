import { useRef, useEffect } from 'react'

interface LogStreamProps {
  logs: string[]
}

export default function LogStream({ logs }: LogStreamProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (containerRef.current) {
      const el = containerRef.current
      // Only auto-scroll if user is already near the bottom (within 30px)
      const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 30
      if (isNearBottom) {
        el.scrollTop = el.scrollHeight
      }
    }
  }, [logs])

  return (
    <div
      ref={containerRef}
      className="bg-gray-900 text-gray-300 rounded-lg border border-gray-700 p-3 h-64 overflow-y-auto task-log-stream"
    >
      {logs.length === 0 ? (
        <p className="text-gray-500 text-xs">等待日志输出...</p>
      ) : (
        logs.map((line, i) => (
          <div key={i} className="hover:bg-gray-800/50 px-1 rounded">
            <span className="text-gray-500 mr-2">{i + 1}</span>
            <span
              className={
                line.includes('ERROR') || line.includes('error') || line.includes('失败')
                  ? 'text-red-400'
                  : line.includes('WARN')
                  ? 'text-yellow-400'
                  : line.includes('成功') || line.includes('completed')
                  ? 'text-green-400'
                  : 'text-gray-300'
              }
            >
              {line}
            </span>
          </div>
        ))
      )}
    </div>
  )
}
