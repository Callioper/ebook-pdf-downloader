import { useEffect, useState, useRef } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { API_BASE } from '../constants'
import ConfirmDownloadModal from './ConfirmDownloadModal'
import ConfirmStepModal from './ConfirmStepModal'

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
  const [checkResult, setCheckResult] = useState('')
  const resultTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // System status check
  const [sysStatus, setSysStatus] = useState<{all_ok?: boolean; failures?: string[]; ocr_engine?: string; components?: Record<string, {ok:boolean;detail:string}>} | null>(null)
  const [sysChecking, setSysChecking] = useState(false)
  const sysCheckedRef = useRef(false)

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
          }
          setCheckResult(`新版本 v${data.latest} 可用`)
        } else {
          setUpdateInfo(null)
          setCheckResult(`已是最新 v${cachedVersion}`)
        }
        if (resultTimerRef.current) clearTimeout(resultTimerRef.current)
        resultTimerRef.current = setTimeout(() => setCheckResult(''), 3000)
      })
      .catch(() => {
        setCheckResult('检查失败')
        if (resultTimerRef.current) clearTimeout(resultTimerRef.current)
        resultTimerRef.current = setTimeout(() => setCheckResult(''), 3000)
      })
      .finally(() => setChecking(false))
  }

  const checkSystemStatus = () => {
    setSysChecking(true)
    fetch('/api/v1/system-status')
      .then(r => r.json())
      .then(data => { setSysStatus(data); sysCheckedRef.current = true })
      .catch(() => setSysStatus(null))
      .finally(() => setSysChecking(false))
  }

  // Auto-run system status check on mount
  useEffect(() => { checkSystemStatus() }, [])

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
      if (pollRef.current) clearInterval(pollRef.current)
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
              <NavLink to="/" className="text-base font-semibold text-gray-800 mr-4 hover:text-blue-600 transition-colors">Ebook PDF Downloader</NavLink>
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
          <ConfirmStepModal />
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
              <svg className={`w-3.5 h-3.5 ${checking ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
             <span>v{version || '...'}</span>
             <button
               onClick={checkSystemStatus}
               disabled={sysChecking}
               className="hover:text-gray-600 disabled:opacity-50 ml-1 px-1.5 py-0.5 rounded border border-gray-300 text-[10px]"
               title="检测所有组件状态"
             >
               {sysChecking ? '⏳' : '状态检测'}
             </button>
             {sysStatus && sysCheckedRef.current && (
               <span className={`text-[10px] ${sysStatus.all_ok ? 'text-green-500' : 'text-orange-500'}`}>
                 {sysStatus.all_ok
                   ? `√ 全部正常 (${sysStatus.ocr_engine})`
                   : `× ${sysStatus.failures?.join(', ')}`
                 }
               </span>
             )}
            {checkResult && (
              <span className={`text-xs ${checkResult.includes('失败') ? 'text-red-400' : checkResult.includes('新版本') ? 'text-blue-500 font-semibold' : 'text-green-400'}`}>
                {checkResult}
              </span>
            )}
          </div>
            <a href="https://github.com/Callioper/ebook-pdf-downloader" target="_blank" rel="noopener noreferrer" className="hover:text-gray-600">
              github.com/Callioper/ebook-pdf-downloader
            </a>
        </div>
      </footer>
    </div>
  )
}
