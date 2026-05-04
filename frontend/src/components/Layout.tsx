import { useEffect, useState, useRef } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { API_BASE } from '../constants'
import ConfirmDownloadModal from './ConfirmDownloadModal'
import type { TaskItem } from '../types'

interface UpdateInfo {
  current: string
  latest: string
  has_update: boolean
  download_url?: string
  setup_url?: string
  body?: string
}

let cachedUpdate: UpdateInfo | null = null
declare const APP_VERSION: string
let cachedVersion = APP_VERSION

export default function Layout() {
  const location = useLocation()
  const isTaskDetail = location.pathname.startsWith('/tasks/') && location.pathname !== '/tasks'
  const [version, setVersion] = useState(cachedVersion)
  const [updateInfo, setUpdateInfo] = useState<UpdateInfo | null>(null)
  const [dismissed, setDismissed] = useState(false)
  const [checking, setChecking] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [downloadingPct, setDownloadingPct] = useState(0)
  const [installing, setInstalling] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Backend terminal state
  const [terminalOpen, setTerminalOpen] = useState(false)
  const [runningTasks, setRunningTasks] = useState<TaskItem[]>([])
  const [taskLogs, setTaskLogs] = useState<Record<string, string[]>>({})
  const logEndRef = useRef<HTMLDivElement>(null)

  const statusBadge = (status: string) => {
    const base = 'px-2 py-0.5 rounded-full text-xs font-medium '
    if (status === 'running') return base + 'bg-blue-100 text-blue-700'
    if (status === 'pending') return base + 'bg-yellow-100 text-yellow-700'
    if (status === 'completed') return base + 'bg-green-100 text-green-700'
    if (status === 'failed') return base + 'bg-red-100 text-red-700'
    return base + 'bg-gray-100 text-gray-600'
  }

  const fetchRunningTasks = async () => {
    try {
      const res = await fetch(`${API_BASE}/tasks`)
      const data = await res.json()
      if (!data.tasks) return
      const running = (data.tasks as TaskItem[]).filter(
        (t: TaskItem) => t.status === 'running' || t.status === 'pending'
      )
      setRunningTasks(running)
      // Collect logs from running tasks
      const logsMap: Record<string, string[]> = {}
      for (const t of running) {
        if (t.logs && t.logs.length > 0) {
          logsMap[t.task_id] = t.logs.slice(-50)
        }
      }
      setTaskLogs(logsMap)
    } catch (e) { console.warn('[Layout] fetch running tasks:', e) }
  }

  useEffect(() => {
    fetchRunningTasks()
    const interval = setInterval(fetchRunningTasks, 3000)
    return () => clearInterval(interval)
  }, [])

  useEffect(() => {
    if (terminalOpen && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [runningTasks, taskLogs, terminalOpen])

  const checkUpdate = () => {
    setChecking(true)
    fetch(`${API_BASE}/check-update`)
      .then((r) => r.json())
      .then((data: UpdateInfo) => {
        cachedUpdate = data
        cachedVersion = data.current || '...'
        setVersion(cachedVersion)
        if (data.has_update) {
          const lastSeen = localStorage.getItem('last_update_seen')
          if (lastSeen !== data.latest) {
            setUpdateInfo(data)
            setDismissed(false)
          } else {
            setUpdateInfo(null)
          }
        } else {
          setUpdateInfo(null)
        }
      })
      .catch(() => {})
      .finally(() => setChecking(false))
  }

  // Shutdown backend when page/electron window is closed
  useEffect(() => {
    const handleBeforeUnload = () => {
      // Use sendBeacon — reliable during page unload (unlike fetch)
      navigator.sendBeacon('/api/v1/shutdown', '')
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [])

  useEffect(() => {
    checkUpdate()

    const heartbeat = setInterval(() => {
      fetch(`${API_BASE}/heartbeat`).catch(() => {})
    }, 10000)
    return () => clearInterval(heartbeat)
  }, [])

  const handleDismiss = () => {
    setDismissed(true)
    if (updateInfo?.latest) {
      localStorage.setItem('last_update_seen', updateInfo.latest)
    }
  }

  const handleDownload = async () => {
    setDownloading(true)
    setDownloadingPct(0)
    try {
      const res = await fetch(`${API_BASE}/download-update`)
      if (!res.ok) {
        alert('启动下载失败: HTTP ' + res.status)
        setDownloading(false)
        return
      }
      pollRef.current = setInterval(async () => {
        try {
          const r = await fetch(`${API_BASE}/download-progress`)
          const p = await r.json()
          if (p.done) {
            clearInterval(pollRef.current!)
            pollRef.current = null
            setDownloading(false)
            if (p.error) {
              alert('下载失败: ' + p.error)
            } else {
              setDownloadingPct(100)
            }
            return
          }
          setDownloadingPct(p.total > 0 ? Math.round((p.downloaded / p.total) * 100) : 0)
        } catch (e) { console.warn('[Layout] download poll:', e) }
      }, 500)
    } catch (e: any) {
      setDownloading(false)
      alert('启动下载失败: ' + (e.message || ''))
    }
  }

  const handleInstall = async () => {
    setInstalling(true)
    try {
      const res = await fetch(`${API_BASE}/install-update`, { method: 'POST' })
      const data = await res.json()
      if (data.ok) {
        setTimeout(() => window.close(), 1500)
      } else {
        alert('安装失败: ' + (data.error || '未知错误'))
        setInstalling(false)
      }
    } catch (e) {
      console.warn('[Layout] install update:', e)
      setInstalling(false)
    }
  }

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const showBanner = updateInfo && updateInfo.has_update && !dismissed
  const downloadDone = downloadingPct >= 100 && !downloading

  return (
    <div className="min-h-screen flex flex-col">
      {showBanner && (
        <div className="bg-blue-600 text-white px-4 py-2 flex items-center justify-between gap-2 flex-wrap">
          <span className="text-sm">
            新版本 v{updateInfo.latest} 可用
          </span>
          <div className="flex items-center gap-2">
            {downloading ? (
              <div className="flex items-center gap-2">
                <div className="w-24 h-1.5 bg-white/30 rounded-full overflow-hidden">
                  <div className="h-full bg-white rounded-full transition-all" style={{ width: `${downloadingPct}%` }} />
                </div>
                <span className="text-xs">{downloadingPct}%</span>
              </div>
            ) : downloadDone ? (
              <button
                onClick={handleInstall}
                disabled={installing}
                className="px-3 py-1 text-xs rounded bg-white text-blue-700 hover:bg-blue-50 disabled:opacity-50 font-medium"
              >
                {installing ? '安装中...' : '安装并重启'}
              </button>
            ) : (
              <button
                onClick={handleDownload}
                disabled={checking}
                className="px-3 py-1 text-xs rounded bg-white text-blue-700 hover:bg-blue-50 disabled:opacity-50 font-medium"
              >
                下载更新
              </button>
            )}
            <button
              onClick={checkUpdate}
              disabled={checking}
              className="text-white/80 hover:text-white text-xs underline shrink-0"
            >
              {checking ? '检测中...' : '重新检测'}
            </button>
            <button
              onClick={handleDismiss}
              className="text-white/80 hover:text-white text-lg leading-none"
              aria-label="关闭"
            >
              ×
            </button>
          </div>
        </div>
      )}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-1">
              <NavLink to="/" className="text-base font-semibold text-gray-800 mr-4 hover:text-blue-600 transition-colors">Book Downloader</NavLink>
              <NavLink
                to="/"
                className={({ isActive }) =>
                  `px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    isActive ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                  }`
                }
              >
                搜索
              </NavLink>
              <NavLink
                to="/tasks"
                className={({ isActive }) =>
                  `px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    isActive || isTaskDetail ? 'bg-blue-50 text-blue-700' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                  }`
                }
              >
                任务
              </NavLink>
            </div>
            <NavLink
              to="/config"
              className="text-sm text-gray-500 hover:text-blue-600"
            >
              设置
            </NavLink>
          </div>
        </div>
      </header>

      <main className="flex-1">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <Outlet />
          <ConfirmDownloadModal />
        </div>
      </main>

      <footer className="bg-white border-t border-gray-200 py-2">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between text-xs text-gray-400">
          <div className="flex items-center gap-2">
            <button
              onClick={checkUpdate}
              disabled={checking}
              className="hover:text-gray-600 disabled:opacity-50"
              title="检查更新"
            >
              {checking ? '↻' : '🔄'}
            </button>
            <span>v{version || '...'}</span>
            <button
              onClick={() => setTerminalOpen((v) => !v)}
              className={`ml-2 px-2 py-0.5 rounded text-xs ${runningTasks.length > 0 ? 'bg-blue-100 text-blue-700 hover:bg-blue-200' : 'hover:bg-gray-100 text-gray-400'}`}
              title="任务状态终端"
            >
              {runningTasks.length > 0 ? `⚙ ${runningTasks.length} 任务运行中` : '终端'}
            </button>
          </div>
          <a href="https://github.com/Callioper/book-downloader" target="_blank" rel="noopener noreferrer" className="hover:text-gray-600">
            github.com/Callioper/book-downloader
          </a>
        </div>

        {/* Backend Terminal Panel */}
        {terminalOpen && (
          <div className="border-t border-gray-200 bg-gray-900 text-gray-300" style={{ maxHeight: '320px' }}>
            <div className="flex items-center justify-between px-4 py-1.5 border-b border-gray-700">
              <span className="text-xs font-medium text-gray-400">任务终端</span>
              <button
                onClick={() => setTerminalOpen(false)}
                className="text-gray-500 hover:text-gray-300 text-lg leading-none"
              >
                ×
              </button>
            </div>
            <div className="overflow-y-auto" style={{ maxHeight: '280px' }}>
              {runningTasks.length === 0 ? (
                <div className="px-4 py-3 text-xs text-gray-500">暂无运行中的任务</div>
              ) : (
                runningTasks.map((task) => {
                  const logs = taskLogs[task.task_id] || []
                  return (
                    <div key={task.task_id} className="border-b border-gray-800 last:border-b-0">
                      <div className="flex items-center gap-2 px-4 py-1.5 bg-gray-800/50">
                        <span className={`text-xs font-medium ${statusBadge(task.status).replace('px-2 py-0.5 rounded-full text-xs font-medium ', '')}`}>
                          {statusBadge(task.status)}
                        </span>
                        <span className="text-xs font-medium text-gray-300 truncate max-w-[200px]">
                          {task.title || '(无标题)'}
                        </span>
                        <span className="text-xs text-gray-500 ml-auto">{task.progress}%</span>
                        <span className="text-xs text-gray-600">{task.current_step || '等待中'}</span>
                      </div>
                      <div className="px-4 py-1 font-mono text-xs space-y-0.5">
                        {logs.length === 0 ? (
                          <div className="text-gray-600">等待日志...</div>
                        ) : (
                          logs.map((line, i) => (
                            <div
                              key={i}
                              className={
                                line.includes('ERROR') || line.includes('error') || line.includes('失败')
                                  ? 'text-red-400'
                                  : line.includes('WARN')
                                  ? 'text-yellow-400'
                                  : line.includes('成功') || line.includes('completed')
                                  ? 'text-green-400'
                                  : 'text-gray-400'
                              }
                            >
                              {line}
                            </div>
                          ))
                        )}
                        <div ref={logEndRef} />
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        )}
      </footer>
    </div>
  )
}
