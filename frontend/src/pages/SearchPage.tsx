import { useState } from 'react'
import { useStore } from '../stores/useStore'
import BasicSearchForm from '../components/BasicSearchForm'
import AdvancedSearchForm from '../components/AdvancedSearchForm'
import TaskListPanel from '../components/TaskListPanel'

export default function SearchPage() {
  const [mode, setMode] = useState<'basic' | 'advanced'>('basic')
  const error = useStore((s) => s.error)

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <div className="flex items-center gap-4 mb-4">
          <h2 className="text-lg font-semibold text-gray-800">图书搜索</h2>
          <div className="flex rounded-md border border-gray-200 overflow-hidden">
            <button
              onClick={() => setMode('basic')}
              className={`px-3 py-1 text-xs font-medium ${
                mode === 'basic' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              基本
            </button>
            <button
              onClick={() => setMode('advanced')}
              className={`px-3 py-1 text-xs font-medium ${
                mode === 'advanced' ? 'bg-blue-600 text-white' : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              高级
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-600">
            {error}
          </div>
        )}

        {mode === 'basic' ? <BasicSearchForm /> : <AdvancedSearchForm />}
      </div>

      <div className="bg-white rounded-lg border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-4">最近任务</h2>
        <TaskListPanel compact />
      </div>
    </div>
  )
}
