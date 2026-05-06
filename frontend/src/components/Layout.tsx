import { useEffect, useState, useRef } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { API_BASE } from '../constants'
import ConfirmDownloadModal from './ConfirmDownloadModal'

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
          </div>
          <a href="https://github.com/Callioper/book-downloader" target="_blank" rel="noopener noreferrer" className="hover:text-gray-600">
            github.com/Callioper/book-downloader
          </a>
        </div>
      </footer>
    </div>
  )
}
