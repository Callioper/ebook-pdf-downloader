import React, { useState, useEffect, useRef, useCallback } from 'react'
import { SectionProps } from './types'

function FolderPicker({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  const [picking, setPicking] = useState(false)
  const pickingRef = useRef(false)

  const pickFolder = async () => {
    if (pickingRef.current) return
    pickingRef.current = true
    setPicking(true)
    try {
      const res = await fetch('/api/v1/browse-folder')
      const data = await res.json()
      if (data.path) {
        onChange(data.path)
      }
    } catch (e) {
    }
    pickingRef.current = false
    setPicking(false)
  }

  return (
    <div className="flex gap-1">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
      />
      <button
        type="button"
        onClick={pickFolder}
        disabled={picking}
        className="px-2 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50 text-gray-600 shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
        title="打开文件夹选择对话框"
      >
        {picking ? '选择中...' : '浏览...'}
      </button>
    </div>
  )
}

function StatusDot({ status }: { status: 'green' | 'red' | 'yellow' | null }) {
  const colors: Record<string, string> = {
    green: 'bg-green-500',
    red: 'bg-red-500',
    yellow: 'bg-yellow-500',
  }
  return (
    <span className={`inline-block w-2 h-2 rounded-full ${status ? colors[status] : 'bg-gray-300'}`} />
  )
}

function DatabaseSection({ form, updateForm, mountedRef }: SectionProps) {
  const [dbDetecting, setDbDetecting] = useState(false)
  const [dbStatus, setDbStatus] = useState<'green' | 'red' | 'yellow' | null>(null)
  const [dbNames, setDbNames] = useState<string[]>([])
  const [detectedPaths, setDetectedPaths] = useState<string[]>([])

  const checkDbConnectivity = useCallback(async () => {
    setDbDetecting(true)
    try {
      const res = await fetch('/api/v1/available-dbs')
      const data = await res.json()
      if (!mountedRef.current) return
      const dbs = data.dbs || []
      setDbNames(dbs)
      setDbStatus(dbs.length > 0 ? 'green' : 'yellow')
    } catch (e) {
      if (mountedRef.current) setDbStatus('red')
    } finally {
      if (mountedRef.current) setDbDetecting(false)
    }
  }, [mountedRef])

  const handleDetectPaths = useCallback(async () => {
    setDbDetecting(true)
    try {
      const [pathsRes, statusRes] = await Promise.all([
        fetch('/api/v1/detect-paths'),
        fetch('/api/v1/status'),
      ])
      const pathsData = await pathsRes.json()
      const statusData = await statusRes.json()
      if (!mountedRef.current) return
      const db = statusData.ebookDatabase || {}
      setDbNames(db.dbs || [])
      setDbStatus(db.dbs?.length > 0 ? 'green' : 'yellow')
      const allPaths = [...(pathsData.paths || [])]
      if (statusData.ebookDatabase?.dbs?.length > 0) {
        for (const p of statusData.ebookDatabase.dbs) {
          if (!allPaths.includes(p)) allPaths.push(p)
        }
      }
      setDetectedPaths(allPaths)
    } catch (e) {
      if (mountedRef.current) setDbStatus('red')
    } finally {
      if (mountedRef.current) setDbDetecting(false)
    }
  }, [mountedRef])

  // Auto-detect on mount
  useEffect(() => {
    const autoDetectDb = async () => {
      try {
        const res = await fetch('/api/v1/available-dbs')
        const data = await res.json()
        if (!mountedRef.current) return
        const dbs = data.dbs || []
        setDbNames(dbs)
        setDbStatus(dbs.length > 0 ? 'green' : 'yellow')
      } catch (e) {
        if (mountedRef.current) setDbStatus('red')
      }
    }
    autoDetectDb()
  }, [mountedRef])

  return (
    <div className="space-y-3">
      {/* SQLite DB path */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">SQLite 数据库路径</label>
        <div className="flex items-center gap-2">
          <div className="flex-1">
            <FolderPicker
              value={form.ebook_db_path || ''}
              onChange={(v) => updateForm({ ebook_db_path: v })}
              placeholder="选择数据库目录..."
            />
          </div>
          <StatusDot status={dbStatus} />
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleDetectPaths}
          disabled={dbDetecting}
          className="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {dbDetecting ? '检测中...' : '智能检测'}
        </button>
        <button
          type="button"
          onClick={checkDbConnectivity}
          className="px-3 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100 text-gray-600"
        >
          重新检测
        </button>
      </div>

      {Array.isArray(detectedPaths) && detectedPaths.length > 0 && (
        <div className="text-xs text-gray-500 space-y-1">
          <span className="font-medium">检测到的路径:</span>
          {detectedPaths.filter(p => p && typeof p === 'string').map((p, i) => (
            <button
              key={i}
              type="button"
              onClick={() => updateForm({ ebook_db_path: p })}
              className={`block w-full text-left px-2 py-1 rounded hover:bg-blue-50 ${p === form.ebook_db_path ? 'bg-blue-50 text-blue-700' : ''}`}
            >
              {p}
            </button>
          ))}
        </div>
      )}

      <div className="border-t border-gray-200 pt-3">
        <label className="block text-xs font-medium text-gray-600 mb-1">下载目录 (PDF 临时存放)</label>
        <FolderPicker
          value={form.download_dir || ''}
          onChange={(v) => updateForm({ download_dir: v })}
          placeholder="下载临时目录..."
        />
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">完成目录 (最终输出)</label>
        <FolderPicker
          value={form.finished_dir || ''}
          onChange={(v) => updateForm({ finished_dir: v })}
          placeholder="完成输出目录..."
        />
      </div>
    </div>
  )
}

export default React.memo(DatabaseSection)
