import { useState, useEffect, useRef, useCallback, type ReactNode } from 'react'
import { LLM_OCR_RECOMMENDED } from '../constants'

interface AppConfig {
  host: string
  port: number
  download_dir: string
  finished_dir: string
  tmp_dir: string
  stacks_base_url: string
  stacks_username: string
  stacks_password: string
  zfile_base_url: string
  zfile_external_url: string
  zfile_storage_key: string
  http_proxy: string
  ocr_jobs: number
  ocr_languages: string
  ocr_timeout: number
  ebook_db_path: string
  zlib_email: string
  zlib_password: string
  aa_membership_key: string
  ocr_engine: string
  ocr_oversample: number
  ai_vision_enabled: boolean
  ai_vision_endpoint: string
  ai_vision_model: string
  ai_vision_api_key: string
  ai_vision_provider: string
  ai_vision_messages_api: boolean  // custom: use Anthropic Messages API instead of OpenAI
  ai_vision_max_pages: number
  ai_vision_dpi: number
  llm_ocr_endpoint: string
  llm_ocr_model: string
  llm_ocr_concurrency: number
  [key: string]: unknown
}

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
      } else if (data.error) {
        console.warn('Folder picker:', data.error)
      }
    } catch (e) {
      console.warn('Folder picker failed:', e)
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

function SectionHeader({ title, summary, color, expanded, onToggle }: {
  title: string
  summary: ReactNode
  color: string
  expanded: boolean
  onToggle: () => void
}) {
  const borderMap: Record<string, string> = {
    blue: 'border-l-blue-500',
    green: 'border-l-green-500',
    purple: 'border-l-purple-500',
    orange: 'border-l-orange-500',
    gray: 'border-l-gray-400',
  }
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`w-full text-left bg-white border border-gray-200 rounded-lg ${borderMap[color]} border-l-4 p-4 hover:shadow-sm transition-shadow`}
    >
      <div className="flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <span className="text-sm font-medium text-gray-800">{title}</span>
          <span className="text-xs text-gray-400 ml-2 truncate">{summary}</span>
        </div>
        <svg
          className={`w-4 h-4 text-gray-400 transition-transform shrink-0 ml-2 ${expanded ? 'rotate-180' : ''}`}
          fill="none" viewBox="0 0 24 24" stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </button>
  )
}

const DEFAULT_CONFIG: AppConfig = {
  host: '0.0.0.0',
  port: 8000,
  download_dir: '',
  finished_dir: '',
  tmp_dir: '',
  stacks_base_url: 'http://localhost:7788',
  stacks_username: '',
  stacks_password: '',
  zfile_base_url: 'http://192.168.0.7:32771',
  zfile_external_url: '',
  zfile_storage_key: '1',
  http_proxy: '',
  ocr_jobs: 1,
  ocr_languages: 'chi_sim+eng',
  ocr_timeout: 3600,
  ebook_db_path: '',
  zlib_email: '',
  zlib_password: '',
  aa_membership_key: '',
  ocr_engine: 'tesseract',
  ocr_oversample: 200,
  ai_vision_enabled: true,
  ai_vision_endpoint: '',
  ai_vision_model: '',
  ai_vision_api_key: '',
  ai_vision_provider: 'openai_compatible',
  ai_vision_messages_api: false,
  ai_vision_max_pages: 5,
  ai_vision_dpi: 150,
  llm_ocr_endpoint: 'http://127.0.0.1:1234/v1',
  llm_ocr_model: '',
  llm_ocr_concurrency: 1,
}

const OCR_ENGINES = [
  { key: 'tesseract', name: 'Tesseract OCR', desc: '内置引擎，需 chi_sim 语言包' },
  { key: 'paddleocr', name: 'PaddleOCR', desc: '百度引擎，需 Python 3.11 虚拟环境' },
]

const OCR_INSTALL_GUIDE = `## 安装 OCR 引擎

**注意**：Python 3.14 与 \`paddlepaddle\` 不兼容。建议使用 Python 3.11 创建虚拟环境。

---

### 1. 创建/重建虚拟环境（Python 3.11）

\`\`\`powershell
# 如果原 venv 不支持 Python 3.11，先删除
Remove-Item -Recurse -Force backend\\venv

# 使用 Python 3.11 创建新 venv
C:\\Python311\\python.exe -m venv backend\\venv
\`\`\`

### 2. 激活虚拟环境（PowerShell）

\`\`\`powershell
# 方法一：PowerShell 执行策略问题
powershell -ExecutionPolicy Bypass -Command "backend\\venv\\Scripts\\Activate.ps1"

# 方法二：直接用 python 运行（无需激活）
C:\\Python311\\python.exe -m pip install ...
\`\`\`

### 3. 安装 OCRmyPDF 核心

\`\`\`powershell
python -m pip install ocrmypdf
\`\`\`

### 4. 安装引擎插件

\`\`\`powershell
# 安装所有 OCR 引擎（推荐，一步到位）
python -m pip install ocrmypdf-paddleocr paddleocr

# 或分开安装
python -m pip install paddleocr
python -m pip install ocrmypdf-paddleocr  # 需要先装好 paddleocr
\`\`\`

### 5. 安装 Tesseract OCR 系统依赖

\`\`\`powershell
winget install --id UB-Mannheim.TesseractOCR --accept-package-agreements --accept-source-agreements
\`\`\`

### 6. 将 Tesseract 添加到 PATH

\`\`\`powershell
[Environment]::SetEnvironmentVariable("Path", [Environment]::GetEnvironmentVariable("Path", "User") + ";C:\\Program Files\\Tesseract-OCR", "User")
\`\`\`

> ⚠️ 添加后需**重启终端或 IDE**使 PATH 生效，或使用完整路径验证：
> \`\`\`powershell
> & "C:\\Program Files\\Tesseract-OCR\\tesseract.exe" --version
> \`\`\`

### 7. 验证安装

\`\`\`powershell
python -c "import ocrmypdf; print('ocrmypdf:', ocrmypdf.__version__)"
python -c "from paddle import paddle; print('paddle:', paddle.__version__)"
"C:\\Program Files\\Tesseract-OCR\\tesseract.exe" --version
\`\`\`

### 常见问题

| 问题 | 解决 |
|------|------|
| \`ModuleNotFoundError: No module named 'paddlepaddle'\` | \`import paddle\` 而非 \`import paddlepaddle\` |
| \`ocrmypdf-paddleocr\` 依赖冲突 | 先装 \`paddleocr\`，再装 \`ocrmypdf-paddleocr\` |
| Tesseract 找不到 | 重启终端，或使用完整路径 \`C:\\Program Files\\Tesseract-OCR\\tesseract.exe\` |`

const STACKS_INSTALL_GUIDE = `## 安装 stacks + FlareSolverr（Docker Compose）

1. 创建目录并进入：
   mkdir ~/stacks && cd ~/stacks

2. 创建 docker-compose.yml：
   notepad docker-compose.yml

3. 粘贴以下内容：

   services:
     stacks:
       image: zelest/stacks:latest
       container_name: stacks
       ports:
         - "7788:7788"
       volumes:
         - ./config:/opt/stacks/config
         - ./download:/opt/stacks/download
         - ./logs:/opt/stacks/logs
       restart: unless-stopped
       environment:
         - USERNAME=admin
         - PASSWORD=stacks
         - TZ=Asia/Shanghai

     flaresolverr:
       image: ghcr.io/flaresolverr/flaresolverr:latest
       container_name: flaresolverr
       ports:
         - "8191:8191"
       environment:
         - LOG_LEVEL=info
       restart: unless-stopped

4. 启动：
   docker compose up -d

5. 访问 http://localhost:7788
   默认密码：admin / stacks

6. 获取 API Key：
   Settings → Authentication → Admin API Key`

const FLARESOLVERR_DOCKER_GUIDE = `## 安装 FlareSolverr（Docker）

1. 创建 docker-compose.yml：
   notepad docker-compose.yml

2. 粘贴以下内容：

   services:
     flaresolverr:
       image: ghcr.io/flaresolverr/flaresolverr:latest
       container_name: flaresolverr
       ports:
         - "8191:8191"
       environment:
         - LOG_LEVEL=info
       restart: unless-stopped

3. 启动：
   docker compose up -d

4. 验证：
   curl http://localhost:8191/v1`

const AI_VISION_ENDPOINTS: Record<string, string> = {
  openai_compatible: 'https://api.openai.com/v1',
  openai_responses: 'https://api.openai.com/v1',
  azure: 'https://RESOURCE_NAME.openai.azure.com',
  anthropic: 'https://api.anthropic.com',
  gemini: 'https://generativelanguage.googleapis.com/v1beta',
  minimax_openai: 'https://api.minimaxi.com/v1',
  minimax_anthropic: 'https://api.minimaxi.com',
  custom: '',
}

export default function ConfigSettings() {
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [form, setForm] = useState<AppConfig>({ ...DEFAULT_CONFIG })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [aiModels, setAiModels] = useState<{ id: string; name: string }[]>([])
  const [fetchingModels, setFetchingModels] = useState(false)
  const [fetchModelsMsg, setFetchModelsMsg] = useState('')

  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    database: false,
    download: false,
    proxy: false,
    ocr: false,
    llm_ocr: true,
    bookmarks: false,
  })

  const [aiVisionTest, setAiVisionTest] = useState<'testing' | 'ok' | 'fail' | null>(null)
  const [aiVisionMsg, setAiVisionMsg] = useState('')

  const [dbDetecting, setDbDetecting] = useState(false)
  const [dbStatus, setDbStatus] = useState<'green' | 'red' | 'yellow' | null>(null)
  const [dbNames, setDbNames] = useState<string[]>([])
  const [detectedPaths, setDetectedPaths] = useState<string[]>([])

  const [zlibChecking, setZlibChecking] = useState(false)
  const [zlibConnected, setZlibConnected] = useState(false)
  const [zlibMsg, setZlibMsg] = useState('')
  const [zlibChecked, setZlibChecked] = useState(false)
  const [zlibBalance, setZlibBalance] = useState('')

  const [flareRunning, setFlareRunning] = useState(false)
  const [flareInstalled, setFlareInstalled] = useState(false)
  const [flareChecking, setFlareChecking] = useState(true)
  const [flareInstalling, setFlareInstalling] = useState(false)
  const [flareProgress, setFlareProgress] = useState(0)
  const [flareStatusText, setFlareStatusText] = useState('')
  const [flareInstallFailed, setFlareInstallFailed] = useState(false)
  const [flareManualPath, setFlareManualPath] = useState('')
  const [stacksStatus, setStacksStatus] = useState<'green' | 'red' | 'yellow' | null>(null)
  const [stacksChecking, setStacksChecking] = useState(false)
  const flarePollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [proxyChecking, setProxyChecking] = useState(false)
  const [proxyStatus, setProxyStatus] = useState<'green' | 'red' | 'yellow' | null>(null)
  const [proxyMsg, setProxyMsg] = useState('')
  const [proxyChecked, setProxyChecked] = useState(false)
  const [aaProxyStatus, setAaProxyStatus] = useState<'green' | 'red' | 'yellow' | null>(null)
  const [zlProxyStatus, setZlProxyStatus] = useState<'green' | 'red' | 'yellow' | null>(null)
  const [aaProxyDetail, setAaProxyDetail] = useState('')
  const [zlProxyDetail, setZlProxyDetail] = useState('')

  const [ocrChecking, setOcrChecking] = useState(false)
  const [ocrStatus, setOcrStatus] = useState<'green' | 'red' | 'yellow' | null>(null)
  const [ocrMsg, setOcrMsg] = useState('')
  const [ocrEngines, setOcrEngines] = useState<Record<string, { installed: boolean; installing: boolean; msg: string }>>({})

  const [llmModels, setLlmModels] = useState<any[]>([])
  const [llmFetchMsg, setLlmFetchMsg] = useState('')
  const [llmFetching, setLlmFetching] = useState(false)
  const [llmTestMsg, setLlmTestMsg] = useState('')
  const [llmTesting, setLlmTesting] = useState(false)

  const [updateChecking, setUpdateChecking] = useState(false)
  const [updateResult, setUpdateResult] = useState('')

  const mountedRef = useRef(true)

  const handleCheckUpdate = async () => {
    setUpdateChecking(true)
    setUpdateResult('')
    try {
      const res = await fetch('/api/v1/check-update')
      const data = await res.json()
      if (!mountedRef.current) return
      if (data.has_update) {
        setUpdateResult(`新版本 v${data.latest} 可用 (当前 v${data.current})`)
      } else {
        setUpdateResult(`已是最新版本 v${data.current}`)
      }
    } catch (e) {
      console.warn('[ConfigSettings] check update:', e)
      if (mountedRef.current) setUpdateResult('检查失败')
    } finally {
      if (mountedRef.current) setUpdateChecking(false)
    }
  }

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (flarePollRef.current) clearInterval(flarePollRef.current)
    }
  }, [])

  const fetchConfig = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/config')
      const data = await res.json()
      if (!mountedRef.current) return
      setConfig(data)
      const merged = { ...DEFAULT_CONFIG, ...data }
      setForm(merged)
    } catch (e) {
      console.warn('[ConfigSettings] fetch config:', e)
      if (mountedRef.current) setConfig(DEFAULT_CONFIG)
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => { fetchConfig() }, [fetchConfig])

  // Restore Z-Lib login state from stored credentials
  useEffect(() => {
    if (!config || !form.zlib_email || !form.zlib_password) return
    if (zlibChecked) return // already manually checked
    const restoreZlib = async () => {
      try {
        const res = await fetch('/api/v1/check-zlib')
        const data = await res.json()
        if (!mountedRef.current) return
        if (data.ok) {
          setZlibConnected(true)
          setZlibMsg('已连接')
          setZlibChecked(true)
          if (data.balance) setZlibBalance(data.balance)
        }
      } catch (e) { console.warn('[ConfigSettings] restore zlib:', e) }
    }
    restoreZlib()
  }, [config, form.zlib_email, form.zlib_password, zlibChecked])

  // Restore proxy state from stored config
  useEffect(() => {
    if (!config || !form.http_proxy) return
    if (proxyChecked) return // already manually checked
    const restoreProxy = async () => {
      try {
        const res = await fetch('/api/v1/check-proxy-status')
        const data = await res.json()
        if (!mountedRef.current) return
        if (data.ok) {
          setProxyStatus('green')
          setProxyMsg(data.message || '代理可用')
        } else {
          setProxyStatus('red')
          setProxyMsg(data.message || '代理不可用')
        }
        setProxyChecked(true)
      } catch (e) { console.warn('[ConfigSettings] restore proxy:', e) }
    }
    restoreProxy()
  }, [config, form.http_proxy, proxyChecked])

  // Restore source connectivity state (runs once on mount)
  const sourceRestoredRef = useRef(false)
  useEffect(() => {
    if (!config || sourceRestoredRef.current) return
    sourceRestoredRef.current = true
    const restoreSourceStatus = async () => {
      try {
        const res = await fetch('/api/v1/check-proxy-sources', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ http_proxy: form.http_proxy || '' }),
        })
        const data = await res.json()
        if (!mountedRef.current) return
        const results = data.results || {}
        const details = data.details || {}
        setAaProxyStatus(results.annas_archive ? 'green' : 'red')
        setZlProxyStatus(results.zlibrary ? 'green' : 'red')
        setAaProxyDetail(details.annas_archive || '')
        setZlProxyDetail(details.zlibrary || '')
      } catch (e) { console.warn('[ConfigSettings] restore source:', e) }
    }
    restoreSourceStatus()
  }, [config])

  const checkFlare = useCallback(async (manualPath?: string) => {
    setFlareChecking(true)
    setFlareInstallFailed(false)
    try {
      const path = manualPath || flareManualPath.trim() || ''
      const res = await fetch('/api/v1/check-flare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ manual_path: path }),
      })
      const data = await res.json()
      if (!mountedRef.current) return
      setFlareRunning(data.available || false)
      setFlareInstalled(data.installed || false)
      if (data.exe_path) setFlareStatusText(`已找到: ${data.exe_path}`)
    } catch (e) {
      console.warn('[ConfigSettings] check flare:', e)
      if (mountedRef.current) {
        setFlareRunning(false)
        setFlareInstalled(false)
      }
    } finally {
      if (mountedRef.current) setFlareChecking(false)
    }
  }, [flareManualPath])

  const flareAutoRef = useRef(false)
  useEffect(() => {
    if (flareAutoRef.current) return
    flareAutoRef.current = true
    checkFlare()
  }, [checkFlare])

  // Auto-detect SQLite database status after config loads
  useEffect(() => {
    if (!config) return
    const autoDetectDb = async () => {
      try {
        const res = await fetch('/api/v1/available-dbs')
        const data = await res.json()
        if (!mountedRef.current) return
        const dbs = data.dbs || []
        setDbNames(dbs)
        setDbStatus(dbs.length > 0 ? 'green' : 'yellow')
      } catch (e) {
        console.warn('[ConfigSettings] auto detect db:', e)
        if (mountedRef.current) setDbStatus('red')
      }
    }
    autoDetectDb()
  }, [config])

  // Auto-detect OCR engine statuses after config + form are ready
  const autoOcrRef = useRef(false)
  useEffect(() => {
    if (!config || autoOcrRef.current) return
    autoOcrRef.current = true
    const engines = ['tesseract', 'paddleocr']
    engines.forEach((eng) => {
      fetch(`/api/v1/check-ocr?engine=${encodeURIComponent(eng)}`)
        .then((r) => r.json())
        .then((data) => {
          if (!mountedRef.current) return
          setOcrEngines((prev) => ({
            ...prev,
            [eng]: {
              installed: data.ok || false,
              installing: false,
              msg: data.version || data.message || (data.ok ? '已安装' : '未检测到'),
              has_chi_sim: data.has_chi_sim,
              languages: data.languages,
              venv: data.venv,
            },
          }))
        })
        .catch((e) => console.warn(`[ConfigSettings] auto detect ${eng}:`, e))
    })
    // Also check the default OCR engine for the main OCR status
    const defaultEngine = form.ocr_engine || 'tesseract'
    fetch(`/api/v1/check-ocr?engine=${encodeURIComponent(defaultEngine)}`)
      .then((r) => r.json())
      .then((data) => {
        if (!mountedRef.current) return
        setOcrStatus(data.ok ? 'green' : 'red')
        setOcrMsg(data.version || data.message || (data.ok ? '已安装' : '未检测到'))
      })
      .catch(() => {})
  }, [config, form.ocr_engine])


  // Update OCR header status when engine selection or engine states change
  useEffect(() => {
    const eng = form.ocr_engine || 'tesseract'
    const info = ocrEngines[eng]
    if (info) {
      setOcrStatus(info.installed ? 'green' : 'red')
      setOcrMsg(info.msg || (info.installed ? '已安装' : '未检测到'))
    }
  }, [form.ocr_engine, ocrEngines])

  // Auto-detect stacks on config load
  const autoStacksRef = useRef(false)
  useEffect(() => {
    if (!config || autoStacksRef.current) return
    autoStacksRef.current = true
    const check = async () => {
      setStacksChecking(true)
      try {
        const url = form.stacks_base_url || 'http://localhost:7788'
        const health = await fetch(url + '/api/health', { signal: AbortSignal.timeout(3000) })
        if (!mountedRef.current) return
        if (!health.ok) { setStacksStatus('red'); return }

        const key = form.stacks_api_key || ''
        if (key) {
          try {
            const kt = await fetch(url + '/api/key/test', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ key }), signal: AbortSignal.timeout(3000),
            })
            const kd = await kt.json()
            if (mountedRef.current) setStacksStatus(kd.valid ? 'green' : 'yellow')
          } catch { if (mountedRef.current) setStacksStatus('yellow') }
        } else {
          if (mountedRef.current) setStacksStatus('yellow')
        }
      } catch { if (mountedRef.current) setStacksStatus('red') }
      finally { if (mountedRef.current) setStacksChecking(false) }
    }
    check()
  }, [config])

  const checkOcr = useCallback(async (engine?: string) => {
    setOcrChecking(true)
    try {
      const eng = engine || form.ocr_engine || 'tesseract'
      const res = await fetch(`/api/v1/check-ocr?engine=${encodeURIComponent(eng)}`)
      const data = await res.json()
      if (!mountedRef.current) return
      setOcrStatus(data.ok ? 'green' : 'red')
      setOcrMsg(data.message || (data.ok ? data.version || '已安装' : '未检测到'))
    } catch (e) {
      console.warn('[ConfigSettings] check ocr:', e)
      if (mountedRef.current) {
        setOcrStatus('red')
        setOcrMsg('检测失败')
      }
    } finally {
      if (mountedRef.current) setOcrChecking(false)
    }
}, [form.ocr_engine])

  const handleDetectPaths = async () => {
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
      console.warn('[ConfigSettings] detect paths:', e)
      if (mountedRef.current) setDbStatus('red')
    } finally {
      if (mountedRef.current) setDbDetecting(false)
    }
  }

  const checkDbConnectivity = async () => {
    setDbDetecting(true)
    try {
      const res = await fetch('/api/v1/available-dbs')
      const data = await res.json()
      if (!mountedRef.current) return
      const dbs = data.dbs || []
      setDbNames(dbs)
      setDbStatus(dbs.length > 0 ? 'green' : 'yellow')
    } catch (e) {
      console.warn('[ConfigSettings] check db:', e)
      if (mountedRef.current) setDbStatus('red')
    } finally {
      if (mountedRef.current) setDbDetecting(false)
    }
  }

  const handleZlibCheck = async () => {
    if (!form.zlib_email || !form.zlib_password) {
      setZlibMsg('请输入邮箱和密码')
      return
    }
    setZlibChecking(true)
    setZlibBalance('')
    setZlibMsg('')
    try {
      const res = await fetch('/api/v1/zlib-fetch-tokens', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: form.zlib_email, password: form.zlib_password }),
      })
      const data = await res.json()
      if (!mountedRef.current) return
      setZlibChecked(true)
      if (data.ok) {
        setZlibConnected(true)
        setZlibMsg('已连接')
        if (data.balance) setZlibBalance(data.balance)
      } else {
        setZlibConnected(false)
        setZlibMsg(data.message || '登录失败')
      }
    } catch (e) {
      console.warn('[ConfigSettings] zlib check:', e)
      if (mountedRef.current) {
        setZlibChecked(true)
        setZlibConnected(false)
        setZlibMsg('请求失败')
      }
    } finally {
      if (mountedRef.current) setZlibChecking(false)
    }
  }

  const handleCheckProxy = async () => {
    setProxyChecking(true)
    setProxyMsg('')
    try {
      const res = await fetch('/api/v1/check-proxy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ http_proxy: form.http_proxy || '' }),
      })
      const data = await res.json()
      if (!mountedRef.current) return
      setProxyChecked(true)
      if (data.ok) {
        setProxyStatus('green')
        setProxyMsg(data.message || '代理可用')
      } else {
        setProxyStatus('red')
        setProxyMsg(data.message || '代理不可用')
      }
    } catch (e) {
      console.warn('[ConfigSettings] check proxy:', e)
      if (mountedRef.current) {
        setProxyChecked(true)
        setProxyStatus('red')
        setProxyMsg('检测失败')
      }
    } finally {
      if (mountedRef.current) setProxyChecking(false)
    }
  }

  const handleCheckProxySources = async () => {
    try {
      const res = await fetch('/api/v1/check-proxy-sources', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ http_proxy: form.http_proxy || '' }),
      })
      const data = await res.json()
      if (!mountedRef.current) return
      const results = data.results || {}
      const details = data.details || {}
      setAaProxyStatus(results.annas_archive ? 'green' : 'red')
      setZlProxyStatus(results.zlibrary ? 'green' : 'red')
      setAaProxyDetail(details.annas_archive || '')
      setZlProxyDetail(details.zlibrary || '')
    } catch (e) { console.warn('[ConfigSettings] check proxy sources:', e) }
  }

  const handleInstallFlare = async () => {
    setFlareInstalling(true)
    setFlareProgress(0)
    setFlareStatusText('准备下载...')
    setFlareInstallFailed(false)
    try {
      const installPath = flareManualPath.trim() || ''
      const res = await fetch('/api/v1/install-flare', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ install_path: installPath }),
      })
      const data = await res.json()
      if (!data.success) {
        setFlareStatusText(data.error || '安装失败')
        setFlareInstallFailed(true)
        return
      }
      // Poll download progress
      if (flarePollRef.current) clearInterval(flarePollRef.current)
      flarePollRef.current = setInterval(async () => {
        try {
          const pr = await fetch('/api/v1/flare-download-progress')
          const pd = await pr.json()
          if (!mountedRef.current) return
          if (pd.total > 0) {
            setFlareProgress(Math.round((pd.downloaded / pd.total) * 100))
          }
          if (pd.status === 'downloading') {
            setFlareStatusText(`下载中... ${Math.round(pd.downloaded / 1024)} KB / ${Math.round(pd.total / 1024)} KB`)
          } else if (pd.status === 'extracting') {
            setFlareStatusText('解压中...')
          } else if (pd.done) {
            if (pd.error) {
              setFlareStatusText(`下载失败: ${pd.error}`)
              setFlareInstallFailed(true)
              if (flarePollRef.current) clearInterval(flarePollRef.current)
              return
            }
            // Finalize installation
            const fin = await fetch('/api/v1/install-flare-complete', { method: 'POST' })
            const fd = await fin.json()
            if (!mountedRef.current) return
            if (fd.success) {
              setFlareInstalled(true)
              if (fd.started) {
                setFlareRunning(true)
                setFlareStatusText('安装完成，已启动')
              } else {
                setFlareRunning(false)
                setFlareStatusText('安装完成（点击"启动"运行）')
              }
            } else {
              setFlareStatusText(fd.error || '安装失败')
              setFlareInstallFailed(true)
            }
            if (flarePollRef.current) clearInterval(flarePollRef.current)
          }
        } catch (e) { console.warn('[ConfigSettings] flare poll:', e) }
}, 1500)
    } catch (e) {
      console.warn('[ConfigSettings] install flare:', e)
      if (mountedRef.current) {
        setFlareStatusText('安装请求失败')
        setFlareInstallFailed(true)
      }
    } finally {
      if (mountedRef.current) setFlareInstalling(false)
    }
  }

  const handleStartFlare = async () => {
    setFlareChecking(true)
    try {
      const res = await fetch('/api/v1/start-flare', { method: 'POST' })
      const data = await res.json()
      if (!mountedRef.current) return
      if (data.success) {
        setFlareRunning(true)
        setFlareStatusText('已启动')
      } else {
        setFlareStatusText(data.message || data.error || '启动失败')
        if (data.message) setFlareInstallFailed(true)
      }
    } catch (e) {
      console.warn('[ConfigSettings] start flare:', e)
      if (mountedRef.current) setFlareStatusText('启动请求失败')
    } finally {
      if (mountedRef.current) setFlareChecking(false)
    }
  }

  const handleStopFlare = async () => {
    try {
      const res = await fetch('/api/v1/stop-flare', { method: 'POST' })
      const data = await res.json()
      if (!mountedRef.current) return
      if (data.success) {
        setFlareRunning(false)
        setFlareStatusText('已停止')
      }
    } catch (e) {
      console.warn('[ConfigSettings] stop flare:', e)
      if (mountedRef.current) setFlareStatusText('停止请求失败')
    }
  }

  const handleDetectOcrEngine = async (engine: string) => {
    setOcrEngines(prev => ({ ...prev, [engine]: { ...prev[engine], installing: false, msg: '检测中...' } }))
    try {
      const res = await fetch(`/api/v1/check-ocr?engine=${encodeURIComponent(engine)}`)
      const data = await res.json()
      if (!mountedRef.current) return
      setOcrEngines(prev => ({
        ...prev,
        [engine]: {
          installed: data.ok || false,
          installing: false,
          msg: data.version || data.message || (data.ok ? '已安装' : '未检测到'),
          has_chi_sim: data.has_chi_sim,
          languages: data.languages,
          venv: data.venv,
        },
      }))
    } catch (e) {
      console.warn('[ConfigSettings] detect ocr engine:', e)
      if (mountedRef.current) {
        setOcrEngines(prev => ({
          ...prev,
          [engine]: { installed: false, installing: false, msg: '检测失败' },
        }))
      }
    }
  }

  const handleInstallOcrEngine = async (engine: string) => {
    setOcrEngines(prev => ({ ...prev, [engine]: { ...prev[engine], installing: true, msg: '安装中...' } }))
    try {
      const res = await fetch('/api/v1/install-ocr', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ engine }),
      })
      const data = await res.json()
      if (!mountedRef.current) return
      setOcrEngines(prev => ({
        ...prev,
        [engine]: {
          installed: data.ok || false,
          installing: false,
          msg: data.message || (data.ok ? '安装成功' : '安装失败'),
        },
      }))
    } catch (e) {
      console.warn('[ConfigSettings] install ocr engine:', e)
      if (mountedRef.current) {
        setOcrEngines(prev => ({
          ...prev,
          [engine]: { installed: false, installing: false, msg: '安装请求失败' },
        }))
      }
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setSaveMsg('')
    try {
      const body = JSON.stringify(form)
      const res = await fetch('/api/v1/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body,
      })
      if (!res.ok) {
        setSaveMsg('保存失败: HTTP ' + res.status)
        setSaving(false)
        return
      }
      const data = await res.json()
      setConfig(data)
      setSaveMsg('保存成功')
      setTimeout(() => setSaveMsg(''), 2000)
    } catch (e: any) {
      setSaveMsg('保存失败: ' + (e.message || '未知错误'))
    }
    setSaving(false)
  }

  const toggleSection = (key: string) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const updateForm = (patch: Partial<AppConfig>) => {
    setForm((prev) => ({ ...prev, ...patch }))
  }

  if (loading) {
    return (
      <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-xs text-gray-400">
        加载配置中...
      </div>
    )
  }

  const flareStatusSummary = flareChecking
    ? '检测中...'
    : flareRunning
      ? '运行中'
      : flareInstalled
        ? '已安装(未启动)'
        : '未安装'

  return (
    <div className="space-y-3">
      {/* ============ 数据库 ============ */}
      <SectionHeader
        title="数据库"
        summary={<><StatusDot status={dbStatus} /> {dbStatus === 'green' && dbNames.length > 0 ? `已连接 ${dbNames.join(', ')}` : dbStatus === 'red' ? '未连接' : dbStatus === 'yellow' ? '已连接(空)' : '检测中...'}</>}
        color="blue"
        expanded={expanded.database}
        onToggle={() => toggleSection('database')}
      />
      {expanded.database && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 space-y-3">
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
              {dbDetecting ? '检测中...' : '智能检测路径'}
            </button>
            <button
              type="button"
              onClick={checkDbConnectivity}
              className="px-3 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100 text-gray-600"
            >
              重新检测连接
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
        </div>
      )}

      {/* ============ 下载 ============ */}
      <SectionHeader
        title="下载"
        summary={<><StatusDot status={form.download_dir && form.finished_dir ? 'green' : 'yellow'} /> {form.download_dir && form.finished_dir ? '配置完成' : '请设置下载目录和完成目录'}</>}
        color="green"
        expanded={expanded.download}
        onToggle={() => toggleSection('download')}
      />
      {expanded.download && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 space-y-3">
          <div>
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

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Anna's Archive 会员密钥
            </label>
            <input
              type="text"
              value={form.aa_membership_key || ''}
              onChange={(e) => updateForm({ aa_membership_key: e.target.value })}
              placeholder="AA 会员密钥..."
              spellCheck={false}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div className="border-t border-gray-200 pt-3">
            <span className="text-xs font-medium text-gray-600">Z-Library 账户</span>
            <div className="grid grid-cols-2 gap-2 mt-1.5">
              <input
                type="text"
                value={form.zlib_email || ''}
                onChange={(e) => updateForm({ zlib_email: e.target.value })}
                placeholder="邮箱"
                spellCheck={false}
                className="rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
              <input
                type="password"
                value={form.zlib_password || ''}
                onChange={(e) => updateForm({ zlib_password: e.target.value })}
                placeholder="密码"
                className="rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div className="flex items-center gap-2 mt-2">
              <button
                type="button"
                onClick={handleZlibCheck}
                disabled={zlibChecking}
                className="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {zlibChecking ? '登录中...' : '登录'}
              </button>
              {zlibChecking ? (
                <span className="text-xs text-blue-500">登录中...</span>
              ) : zlibChecked && (
                <span className={`text-xs font-medium ${zlibConnected ? 'text-green-600' : 'text-red-500'}`}>
                  {zlibConnected ? '已连接' : '未连接'}
                </span>
              )}
              {zlibBalance && (
                <span className="text-xs text-gray-500">{zlibBalance}</span>
              )}
            </div>
            {!zlibChecking && zlibMsg && !zlibConnected && (
                <span className="text-xs text-red-500">{zlibMsg}</span>
              )}
          </div>

          {/* ============ stacks ============ */}
          <div className="border-t border-gray-200 pt-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-gray-600">stacks 下载管理器（Anna's Archive）</span>
              <StatusDot status={stacksChecking ? 'yellow' : stacksStatus} />
            </div>
            {/* Service URL + health check */}
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={form.stacks_base_url || ''}
                onChange={(e) => setForm((prev) => ({ ...prev, stacks_base_url: e.target.value }))}
                placeholder="http://localhost:7788"
                spellCheck={false}
                className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
              <button
                type="button"
                onClick={async () => {
                  setStacksChecking(true)
                  try {
                    const url = form.stacks_base_url || 'http://localhost:7788'
                    const health = await fetch(url + '/api/health', { signal: AbortSignal.timeout(3000) })
                    if (!health.ok) { setStacksStatus('red'); return }
                    const uname = form.stacks_username
                    const passwd = form.stacks_password
                    if (uname && passwd) {
                      const loginRes = await fetch('/api/v1/check-stacks', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ url, username: uname, password: passwd }),
                        signal: AbortSignal.timeout(5000),
                      })
                      const ld = await loginRes.json()
                      setStacksStatus(ld.ok ? 'green' : 'yellow')
                    } else {
                      setStacksStatus('yellow')
                    }
                  } catch { setStacksStatus('red') }
                  finally { setStacksChecking(false) }
                }}
                className="px-2 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100 text-gray-600 shrink-0"
              >
                {stacksChecking ? '检测中...' : '检测'}
              </button>
            </div>
            {/* API Key */}
            <input
              type="password"
              value={String(form.stacks_api_key || '')}
              onChange={(e) => setForm((prev) => ({ ...prev, stacks_api_key: e.target.value }))}
              placeholder="Admin API Key（可选，填写账号密码后优先使用 session 登录）"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500 mt-1.5"
            />
            {/* Account login (unified with ZLibrary style) */}
            <span className="block text-xs font-medium text-gray-600 mt-2">账户登录</span>
            <div className="grid grid-cols-2 gap-2 mt-1">
              <input
                type="text" value={form.stacks_username || ''}
                onChange={(e) => updateForm({ stacks_username: e.target.value })}
                placeholder="用户名" spellCheck={false}
                className="rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
              <input
                type="password" value={form.stacks_password || ''}
                onChange={(e) => updateForm({ stacks_password: e.target.value })}
                placeholder="密码"
                className="rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div className="flex items-center gap-2 mt-2">
              <button
                type="button"
                onClick={async () => {
                  setStacksChecking(true)
                  try {
                    const res = await fetch('/api/v1/check-stacks', {
                      method: 'POST', headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ url: form.stacks_base_url || 'http://localhost:7788', username: form.stacks_username || '', password: form.stacks_password || '' }),
                      signal: AbortSignal.timeout(5000),
                    })
                    const d = await res.json()
                    setStacksStatus(d.ok ? 'green' : 'red')
                  } catch { setStacksStatus('red') }
                  finally { setStacksChecking(false) }
                }}
                disabled={stacksChecking}
                className="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {stacksChecking ? '登录中...' : '登录'}
              </button>
              {!stacksChecking && stacksStatus === 'green' && (
                <span className="text-xs font-medium text-green-600">已连接</span>
              )}
              {!stacksChecking && stacksStatus === 'red' && (
                <span className="text-xs font-medium text-red-500">未连接</span>
              )}
              {!stacksChecking && stacksStatus === 'yellow' && (
                <span className="text-xs text-gray-500">需要登录</span>
              )}
            </div>
            <details className="mt-2">
              <summary className="text-xs font-medium text-gray-600 cursor-pointer list-none flex items-center gap-1 select-none hover:text-gray-800">
                <svg className="w-3 h-3 text-gray-400 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
                stacks 安装指引
              </summary>
              <div className="mt-2 bg-blue-50 border border-blue-200 rounded p-3">
                <p className="text-xs text-blue-800 font-medium mb-2">? 将以下提示词复制并发送给 OpenCode：</p>
                <pre className="text-xs text-blue-700 bg-blue-100 rounded p-2 overflow-x-auto whitespace-pre-wrap font-mono">{STACKS_INSTALL_GUIDE}</pre>
                <p className="text-xs text-blue-600 mt-2">安装并启动后，点击"检测"确认连接状态。</p>
              </div>
            </details>
          </div>

          <div className="border-t border-gray-200 pt-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-medium text-gray-600">FlareSolverr</span>
              <StatusDot status={flareChecking ? 'yellow' : flareRunning ? 'green' : flareInstalled ? 'yellow' : 'red'} />
            </div>
            {flareChecking ? (
              <span className="text-xs text-gray-400">检测中...</span>
            ) : flareInstalling ? (
              <div className="space-y-1.5">
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div className="bg-blue-500 h-2 rounded-full transition-all duration-300" style={{ width: `${flareProgress}%` }} />
                </div>
                <span className="text-xs text-blue-600">{flareStatusText}</span>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-600">
                    {flareRunning ? '运行中' : flareInstalled ? '已安装 (未启动)' : '未安装'}
                  </span>
                  <span className="text-xs text-gray-400">{flareStatusText}</span>
                </div>
                {/* Always-visible folder picker + install row */}
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={flareManualPath}
                    onChange={(e) => setFlareManualPath(e.target.value)}
                    placeholder="选择 FlareSolverr 安装目录..."
                    spellCheck={false}
                    className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                  <button
                    type="button"
                    onClick={async () => {
                      try {
                        const res = await fetch('/api/v1/browse-folder')
                        const data = await res.json()
                        if (data.path) setFlareManualPath(data.path)
                      } catch (e) { console.warn('[ConfigSettings] browse folder:', e) }
                    }}
                    className="px-2 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100 text-gray-600 shrink-0"
                    title="选择安装目录..."
                  >
                    ...
                  </button>
                  {!flareRunning && !flareInstalled && (
                    <button
                      type="button"
                      onClick={handleInstallFlare}
                      className="px-3 py-1.5 text-xs rounded bg-green-600 text-white hover:bg-green-700 shrink-0"
                    >
                      一键安装
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {!flareRunning && flareInstalled && (
                    <button
                      type="button"
                      onClick={handleStartFlare}
                      className="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-700"
                    >
                      启动
                    </button>
                  )}
                  {flareRunning && (
                    <button
                      type="button"
                      onClick={handleStopFlare}
                      className="px-3 py-1.5 text-xs rounded bg-red-500 text-white hover:bg-red-600"
                    >
                      停止
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => checkFlare()}
                    disabled={flareChecking}
                    className="px-3 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100 text-gray-600 disabled:opacity-50"
                  >
                    重新检测
                  </button>
                </div>
                {flareInstallFailed && (
                  <div className="bg-yellow-50 border border-yellow-200 rounded p-2">
                    <p className="text-xs text-yellow-800">下载失败，请检查网络或重试</p>
                  </div>
                )}
              </div>
                    )}
                  </div>
                  {/* FlareSolverr 端口 */}
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      value={Number(form.flaresolverr_port) || 8191}
                      onChange={(e) => setForm((prev) => ({ ...prev, flaresolverr_port: parseInt(e.target.value) || 8191 }))}
                      placeholder="端口号"
                      min={1}
                      max={65535}
                      className="w-24 rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                    />
                    <span className="text-xs text-gray-400">FlareSolverr 端口（默认 8191）</span>
                  </div>
                  {/* Docker 安装引导 */}
                  <details className="mt-2">
                    <summary className="text-xs text-blue-600 cursor-pointer hover:text-blue-800">📦 查看 Docker 安装指引</summary>
                    <div className="mt-2 bg-blue-50 border border-blue-200 rounded p-3">
                      <p className="text-xs text-blue-800 font-medium mb-2">📋 将以下提示词复制并发送给 OpenCode：</p>
                      <pre className="text-xs text-blue-700 bg-blue-100 rounded p-2 overflow-x-auto whitespace-pre-wrap font-mono">{FLARESOLVERR_DOCKER_GUIDE}</pre>
                      <p className="text-xs text-blue-600 mt-2">启动后返回设置页点击"重新检测"确认连接状态。</p>
                    </div>
                  </details>
                  {/* PDF 压缩 */}
                  <div className="border-t border-gray-200 pt-2 mt-2">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={!!form.pdf_compress}
                        onChange={(e) => setForm((prev) => ({ ...prev, pdf_compress: e.target.checked }))}
                        className="rounded border-gray-300"
                      />
                      <span className="text-xs font-medium text-gray-600">PDF 压缩（OCR 后执行 qpdf 结构压缩）</span>
                    </label>
                    <p className="text-xs text-gray-400 mt-0.5 ml-5">使用 qpdf 纯结构压缩，零文字层损失。</p>
                  </div>
                </div>
      )}

      {/* ============ 网络代理 ============ */}
      <SectionHeader
        title="网络代理"
        summary={<><StatusDot status={aaProxyStatus} /> AA · <StatusDot status={zlProxyStatus} /> ZL{form.http_proxy ? ` · ${form.http_proxy}` : ''}</>}
        color="purple"
        expanded={expanded.proxy}
        onToggle={() => toggleSection('proxy')}
      />
      {expanded.proxy && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">HTTP 代理地址（可选）</label>
            <input
              type="text"
              value={form.http_proxy || ''}
              onChange={(e) => updateForm({ http_proxy: e.target.value })}
              placeholder="http://127.0.0.1:10809"
              spellCheck={false}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleCheckProxy}
              disabled={proxyChecking}
              className="px-3 py-1.5 text-xs rounded bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50"
            >
              {proxyChecking ? '检测中...' : '检测'}
            </button>
            {proxyChecking ? (
              <span className="text-xs text-purple-500">检测中...</span>
            ) : proxyChecked ? (
              <>
                <StatusDot status={proxyStatus} />
                {proxyStatus === 'green' && (
                  <span className="text-xs text-green-600 font-medium">已连接</span>
                )}
                {!proxyStatus && <span className="text-xs text-red-500">{proxyMsg}</span>}
              </>
            ) : (
              <StatusDot status={proxyStatus} />
            )}
          </div>

          <div className="border-t border-gray-200 pt-3">
            <span className="text-xs font-medium text-gray-600">源站连通性</span>
            <div className="flex items-center gap-4 mt-2">
              <div className="flex items-center gap-1.5">
                <StatusDot status={aaProxyStatus} />
                <span className="text-xs text-gray-500">Anna's Archive</span>
                {aaProxyDetail && <span className="text-xs text-gray-400">({aaProxyDetail})</span>}
              </div>
              <div className="flex items-center gap-1.5">
                <StatusDot status={zlProxyStatus} />
                <span className="text-xs text-gray-500">Z-Library</span>
                {zlProxyDetail && <span className="text-xs text-gray-400">({zlProxyDetail})</span>}
              </div>
              <button
                type="button"
                onClick={handleCheckProxySources}
                className="px-2 py-1 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100 text-gray-500"
              >
                检测
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ============ OCR ============ */}
      <SectionHeader
        title="OCR"
        summary={<>
  <StatusDot status={ocrEngines['ocrmypdf']?.installed ? 'green' : ocrEngines['ocrmypdf']?.msg ? 'red' : null} />
  <span className="text-xs">OCRmyPDF {ocrEngines['ocrmypdf']?.installed ? (ocrEngines['ocrmypdf']?.msg || '已安装') : '未安装'}</span>
  <span className="text-xs text-gray-300 mx-1">·</span>
  <StatusDot status={ocrStatus} />
  <span className="text-xs">{form.ocr_engine === 'ocrmypdf' ? 'OCRmyPDF' : (OCR_ENGINES.find(e => e.key === form.ocr_engine)?.name || form.ocr_engine)} {ocrStatus === 'green' ? (ocrMsg || '已安装') : '未安装'}</span>
</>}
        color="orange"
        expanded={expanded.ocr}
        onToggle={() => toggleSection('ocr')}
      />
      {expanded.ocr && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 space-y-3">
          {/* OCRmyPDF 独立状态区 */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">OCRmyPDF 状态</label>
            <div className="flex items-center gap-2">
              <StatusDot status={ocrEngines['ocrmypdf']?.installed ? 'green' : ocrEngines['ocrmypdf']?.msg ? 'red' : null} />
              <span className="text-xs text-gray-500">
                {ocrEngines['ocrmypdf']?.msg || '点击检测'}
              </span>
              <button
                type="button"
                onClick={() => handleDetectOcrEngine('ocrmypdf')}
                className="px-2 py-1 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100 text-gray-500"
              >
                检测
              </button>
              <button
                type="button"
                onClick={() => handleInstallOcrEngine('ocrmypdf')}
                disabled={ocrEngines['ocrmypdf']?.installing}
                className="px-2 py-1 text-xs rounded bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-50"
              >
                {ocrEngines['ocrmypdf']?.installing ? '安装中...' : '一键安装'}
              </button>
            </div>
          </div>

          {/* Tesseract 语言包状态 */}
          <div className="border-t border-gray-200 pt-3">
            <span className="text-xs font-medium text-gray-600 mb-2 block">Tesseract 语言包</span>
            <div className="flex items-center gap-2">
              <StatusDot status={
                form.ocr_engine === 'tesseract' && (ocrEngines['tesseract'] as any)?.has_chi_sim
                  ? 'green'
                  : form.ocr_engine === 'tesseract'
                    ? 'red'
                    : null
              } />
              <span className="text-xs text-gray-500">
                {(ocrEngines['tesseract'] as any)?.has_chi_sim
                  ? 'chi_sim 已安装'
                  : (ocrEngines['tesseract'] as any)?.languages
                    ? 'chi_sim 未安装'
                    : '请先检测 Tesseract'}
              </span>
              {!((ocrEngines['tesseract'] as any)?.has_chi_sim) && (
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      await fetch('/api/v1/install-tesseract-lang?lang=chi_sim')
                      handleDetectOcrEngine('tesseract')
                    } catch (e) {
                      console.warn('[ConfigSettings] install tess lang:', e)
                    }
                  }}
                  className="px-2 py-1 text-xs rounded bg-orange-500 text-white hover:bg-orange-600"
                >
                  安装中文语言包
                </button>
              )}
            </div>
          </div>

          {/* 引擎切换区 */}
          <div className="border-t border-gray-200 pt-3">
            <span className="text-xs font-medium text-gray-600 mb-2 block">引擎切换</span>
            <div className="grid grid-cols-2 gap-2">
              {OCR_ENGINES.map((eng) => {
                const info = ocrEngines[eng.key]
                const isSelected = form.ocr_engine === eng.key
                return (
                  <div
                    key={eng.key}
                    className={`rounded border p-2.5 ${isSelected ? 'border-orange-400 bg-orange-50' : 'border-gray-200 bg-white'}`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium text-gray-700">{eng.name}</span>
                      <div className="flex items-center gap-1">
                        <StatusDot status={info?.installed ? 'green' : info?.msg ? 'red' : null} />
                      </div>
                    </div>
                    <p className="text-xs text-gray-400 mb-2">{eng.desc}</p>
                    {info?.msg && (
                      <p className={`text-xs mb-1.5 ${info.installed ? 'text-green-600' : 'text-red-500'}`}>
                        {info.msg}
                      </p>
                    )}
                    {eng.key === 'paddleocr' && !info?.installed && (
                      <p className="text-xs text-gray-400 mb-1.5">需要 Python 3.11 虚拟环境，点击安装自动搭建</p>
                    )}
                    {eng.key === 'paddleocr' && info?.installed && (info as any)?.venv && (
                      <p className="text-xs text-green-600 mb-1.5">运行环境: {(info as any).venv}</p>
                    )}
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => handleDetectOcrEngine(eng.key)}
                        className="px-2 py-0.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100 text-gray-500"
                      >
                        检测
                      </button>
                      <button
                        type="button"
                        onClick={() => handleInstallOcrEngine(eng.key)}
                        disabled={info?.installing}
                        className="px-2 py-0.5 text-xs rounded bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-50"
                      >
                        {info?.installing ? '安装中...' : '安装'}
                      </button>
                      {eng.key === form.ocr_engine ? (
                        <span className="text-xs text-orange-600 font-medium ml-auto">当前</span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => updateForm({ ocr_engine: eng.key })}
                          className="px-2 py-0.5 text-xs rounded text-orange-600 hover:bg-orange-50 ml-auto"
                        >
                          选用
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
          </div>
          </div>



          <div className="grid grid-cols-4 gap-3 pt-2">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">语言</label>
              <select
                value={form.ocr_languages || 'chi_sim+eng'}
                onChange={(e) => updateForm({ ocr_languages: e.target.value })}
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              >
                <option value="chi_sim+eng">chi_sim+eng</option>
                <option value="chi_sim">chi_sim</option>
                <option value="eng">eng</option>
                <option value="chi_sim+eng+jpn">chi_sim+eng+jpn</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">并行线程</label>
              <select
                value={form.ocr_jobs ?? 1}
                onChange={(e) => updateForm({ ocr_jobs: parseInt(e.target.value) || 1 })}
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              >
                <option value={1}>1</option>
                <option value={2}>2</option>
                <option value={4}>4</option>
              </select>
              <p className="text-[10px] text-gray-400 mt-0.5 leading-tight">Tesseract 支持多线程，PaddleOCR 仅单线程</p>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">超时 (秒)</label>
              <input
                type="number"
                value={form.ocr_timeout ?? 1800}
                  onChange={(e) => updateForm({ ocr_timeout: parseInt(e.target.value) || 3600 })}
                min={60}
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">OCR 采样 DPI</label>
              <input
                type="number"
                min={150}
                max={400}
                step={50}
                value={form.ocr_oversample || 200}
                onChange={(e) => updateForm({ocr_oversample: parseInt(e.target.value)})}
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
              <span className="text-xs text-gray-400">越低越快，150-400，推荐 200</span>
            </div>
          </div>

          {/* ---------- OCR 安装引导 ---------- */}
          <details className="group">
            <summary className="text-xs font-medium text-gray-600 cursor-pointer list-none flex items-center gap-1 select-none hover:text-gray-800">
              <svg className="w-3 h-3 text-gray-400 transition-transform group-open:rotate-90" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
              OCR 命令行安装指引
            </summary>
            <div className="mt-2 bg-blue-50 border border-blue-200 rounded p-3">
              <p className="text-xs text-blue-800 font-medium mb-2">📋 将以下提示词复制并发送给 OpenCode：</p>
              <pre className="text-xs text-blue-700 bg-blue-100 rounded p-2 overflow-x-auto whitespace-pre-wrap font-mono">{OCR_INSTALL_GUIDE}</pre>
              <p className="text-xs text-blue-600 mt-2">安装后返回设置页点击"检测"按钮确认状态。</p>
            </div>
          </details>
        </div>
      )}

      {/* ============ LLM OCR ============ */}
      <SectionHeader
        title="LLM OCR"
        summary={<>
          <StatusDot status={form.llm_ocr_endpoint ? 'green' : null} />
          <span className="text-xs">{form.llm_ocr_endpoint ? '已配置' : '未配置'}</span>
        </>}
        color="blue"
        expanded={expanded.llm_ocr}
        onToggle={() => toggleSection('llm_ocr')}
      />
      {expanded.llm_ocr && (
      <div className="space-y-3">
        <p className="text-xs text-gray-500">
          使用视觉大模型逐框识别文字层（dense mode）。需要运行 lmstudio / ollama 加载对应模型。
          推荐模型已验证中文 PDF 可用。
        </p>

        <div>
          <label className="text-xs text-gray-500 block mb-1">接口地址</label>
          <div className="flex gap-2">
            <input value={form.llm_ocr_endpoint || 'http://127.0.0.1:1234/v1'}
              onChange={(e) => updateForm({ llm_ocr_endpoint: e.target.value })}
              placeholder="http://127.0.0.1:1234/v1"
              className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
            <button onClick={async () => {
              setLlmTesting(true); setLlmTestMsg('');
              try {
                const r = await fetch('/api/v1/check-llm-ocr', {
                  method: 'POST',
                  headers: {'Content-Type':'application/json'},
                  body: JSON.stringify({ endpoint: form.llm_ocr_endpoint, model: form.llm_ocr_model })
                });
                const d = await r.json();
                setLlmTestMsg(d.message || (d.ok ? 'OK' : 'Failed'));
              } catch(e) { setLlmTestMsg(String(e)); }
              setLlmTesting(false);
            }} disabled={llmTesting}
              className="px-3 py-1.5 text-xs rounded border border-blue-500 text-blue-600 hover:bg-blue-50 disabled:opacity-50 whitespace-nowrap">
              {llmTesting ? '测试中...' : '测试连接'}
            </button>
          </div>
          {llmTestMsg && <p className={`text-xs mt-1 ${llmTestMsg.includes('成功')||llmTestMsg.includes('OK') ? 'text-green-600' : 'text-red-500'}`}>{llmTestMsg}</p>}
        </div>

        <div>
          <label className="text-xs text-gray-500 block mb-1">模型名称</label>
          <div className="flex gap-2">
            <input value={form.llm_ocr_model || ''}
              onChange={(e) => updateForm({ llm_ocr_model: e.target.value })}
              placeholder="qwen3-vl-4b-instruct"
              className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
            <button onClick={async () => {
              setLlmFetching(true); setLlmFetchMsg('');
              try {
                const r = await fetch('/api/v1/fetch-llm-models', {
                  method: 'POST',
                  headers: {'Content-Type':'application/json'},
                  body: JSON.stringify({ endpoint: form.llm_ocr_endpoint })
                });
                const d = await r.json();
                if (d.ok && d.models.length > 0) {
                  setLlmModels(d.models);
                  setLlmFetchMsg(`${d.models.length} 个模型`);
                } else {
                  setLlmFetchMsg(d.message || '无可用模型');
                }
              } catch(e) { setLlmFetchMsg(String(e)); }
              setLlmFetching(false);
            }} disabled={llmFetching || !form.llm_ocr_endpoint}
              className="px-2 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-50 whitespace-nowrap">
              {llmFetching ? '...' : '拉取模型'}
            </button>
          </div>
          {llmModels.length > 0 && (
            <select value={form.llm_ocr_model || ''}
              onChange={(e) => updateForm({ llm_ocr_model: e.target.value })}
              className="w-full mt-1 rounded border border-blue-300 px-2 py-1 text-xs font-mono"
              size={Math.min(llmModels.length + 1, 8)}>
              <option value="" disabled>-- 选择模型 --</option>
              {llmModels.map((m: any) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          )}
          {llmFetchMsg && <p className={`text-xs mt-1 ${llmFetchMsg.includes('个模型') ? 'text-green-600' : 'text-red-500'}`}>{llmFetchMsg}</p>}
        </div>

        <div>
          <label className="text-xs text-gray-500 block mb-1">
            并发数: {form.llm_ocr_concurrency || 1}
          </label>
          <input type="range" min="1" max="5" step="1"
            value={form.llm_ocr_concurrency || 1}
            onChange={(e) => updateForm({ llm_ocr_concurrency: parseInt(e.target.value) })}
            className="w-full" />
          <div className="flex justify-between text-xs text-gray-400">
            <span>1 (默认)</span><span>5 (最快)</span>
          </div>
        </div>

        <details className="text-xs">
          <summary className="cursor-pointer text-blue-600 hover:text-blue-800">
            推荐模型 (已验证中文 PDF)
          </summary>
          <div className="mt-2 space-y-1">
            {LLM_OCR_RECOMMENDED.map(m => (
              <button key={m.model}
                onClick={() => updateForm({ llm_ocr_model: m.model })}
                title={m.note}
                className="block w-full text-left px-2 py-1 rounded hover:bg-blue-100 text-gray-700 text-xs">
                <span className="font-mono">{m.model}</span>
                <span className="text-gray-400 ml-2">{m.note}</span>
              </button>
            ))}
          </div>
        </details>
      </div>
      )}

      {/* ============ 书签 ============ */}
      <SectionHeader
        title="书签"
        summary={form.ai_vision_enabled ? (form.ai_vision_model || '已启用') : 'AI Vision 未启用'}
        color="gray"
        expanded={expanded.bookmarks}
        onToggle={() => toggleSection('bookmarks')}
      />
      {expanded.bookmarks && (
        <div className="space-y-3 py-3">
          <div className="flex items-center gap-2">
            <input type="checkbox" id="ai_vision_enabled"
              checked={form.ai_vision_enabled ?? true}
              onChange={(e) => updateForm({ ai_vision_enabled: e.target.checked })} className="rounded" />
            <label htmlFor="ai_vision_enabled" className="text-sm">启用 AI Vision 目录提取</label>
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">API 端点</label>
            <input type="text" value={form.ai_vision_endpoint || ''}
              onChange={(e) => updateForm({ ai_vision_endpoint: e.target.value })}
              placeholder={
                form.ai_vision_provider === 'gemini' ? 'https://generativelanguage.googleapis.com/v1beta' :
                form.ai_vision_provider === 'azure' ? 'https://{resource}.openai.azure.com' :
                form.ai_vision_provider === 'anthropic' || form.ai_vision_provider === 'minimax_anthropic' ? 'https://api.anthropic.com' :
                form.ai_vision_provider === 'minimax_openai' ? 'https://api.minimaxi.com/v1' :
                'http://127.0.0.1:12345/v1'
              }
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">模型名称</label>
            <div className="flex gap-1">
              <input type="text" value={form.ai_vision_model || ''}
                onChange={(e) => updateForm({ ai_vision_model: e.target.value })}
                placeholder="sabafallah/deepseek-ocr"
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
              <button
                type="button"
                onClick={async () => {
                  setFetchingModels(true)
                  setFetchModelsMsg('')
                  try {
                    const res = await fetch('/api/v1/fetch-models', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({
                        endpoint: form.ai_vision_endpoint,
                        api_key: form.ai_vision_api_key,
                        provider: form.ai_vision_provider,
                      }),
                    })
                    const data = await res.json()
                    if (data.ok && data.models.length > 0) {
                      setAiModels(data.models)
                      setFetchModelsMsg(`${data.models.length} 个模型`)
                    } else {
                      setFetchModelsMsg(data.message || '无可用模型')
                    }
                  } catch (e) {
                    setFetchModelsMsg(String(e))
                  }
                  setFetchingModels(false)
                }}
                disabled={fetchingModels || !form.ai_vision_endpoint}
                className="px-2 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-50 whitespace-nowrap"
                title="从提供商拉取可用模型列表"
              >
                {fetchingModels ? '...' : '获取模型'}
              </button>
            </div>
            {aiModels.length > 0 && (
              <select
                value={form.ai_vision_model || ''}
                onChange={(e) => updateForm({ ai_vision_model: e.target.value })}
                className="w-full mt-1 rounded border border-blue-300 px-2 py-1 text-xs font-mono"
                size={Math.min(aiModels.length + 1, 8)}
              >
                <option value="" disabled>-- 选择模型 --</option>
                {aiModels.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            )}
            {fetchModelsMsg && (
              <p className={`text-xs mt-1 ${fetchModelsMsg.includes('个模型') ? 'text-green-600' : 'text-red-500'}`}>
                {fetchModelsMsg}
              </p>
            )}
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">API Key</label>
            <input type="password" value={form.ai_vision_api_key || ''}
              onChange={(e) => updateForm({ ai_vision_api_key: e.target.value })}
              placeholder="sk-...  (支持 {env:VAR_NAME})"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">API 格式</label>
            <select value={form.ai_vision_provider || 'openai_compatible'}
              onChange={(e) => {
                const newProvider = e.target.value
                const defaultEndpoint = AI_VISION_ENDPOINTS[newProvider] || ''
                updateForm({
                  ai_vision_provider: newProvider,
                  ai_vision_endpoint: defaultEndpoint,
                })
              }}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs">
              <option value="openai_compatible">OpenAI / DeepSeek / 智谱 / Qwen / Ollama / lmstudio</option>
              <option value="openai_responses">OpenAI Responses (新版 /v1/responses)</option>
              <option value="azure">Azure OpenAI</option>
              <option value="anthropic">Anthropic Claude</option>
              <option value="gemini">Google Gemini</option>
              <option value="minimax_openai">MiniMax (OpenAI 兼容 · 国内/国际通用)</option>
              <option value="minimax_anthropic">MiniMax (Anthropic 兼容 · Token Plan)</option>
              <option value="custom">自定义 (Custom)</option>
            </select>
          </div>
          {form.ai_vision_provider === 'custom' && (
            <div className="flex items-center gap-2">
              <input type="checkbox" id="ai_vision_messages_api"
                checked={form.ai_vision_messages_api ?? false}
                onChange={(e) => updateForm({ ai_vision_messages_api: e.target.checked })} className="rounded" />
              <label htmlFor="ai_vision_messages_api" className="text-xs text-gray-500">
                使用 Anthropic Messages API 格式 (默认 OpenAI Chat Completions)
              </label>
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs text-gray-500 block mb-1">DPI</label>
              <input type="number" value={form.ai_vision_dpi ?? 150}
                onChange={(e) => updateForm({ ai_vision_dpi: parseInt(e.target.value) || 150 })}
                min={72} max={300} className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs" />
            </div>
          </div>
          <button
            type="button"
            onClick={async () => {
              setAiVisionTest('testing');
              try {
                const res = await fetch('/api/v1/check-ai-vision', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    endpoint: form.ai_vision_endpoint,
                    model: form.ai_vision_model,
                    api_key: form.ai_vision_api_key,
                    provider: form.ai_vision_provider,
                    messages_api: form.ai_vision_messages_api,
                  }),
                });
                const data = await res.json();
                setAiVisionTest(data.ok ? 'ok' : 'fail');
                setAiVisionMsg(data.message || data.error || '');
              } catch (e) {
                setAiVisionTest('fail');
                setAiVisionMsg(String(e));
              }
            }}
            disabled={aiVisionTest === 'testing'}
            className="px-3 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-50"
          >
            {aiVisionTest === 'testing' ? '测试中...' : '测试连接'}
          </button>
          {aiVisionMsg && (
            <p className={`text-xs ${aiVisionTest === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
              {aiVisionMsg}
            </p>
          )}
          <p className="text-xs text-gray-400">
            阶段1 从 OCR 文字层提取目录（免费），阶段2 用 AI Vision 从目录页图片提取。
            支持 OpenAI 兼容 / Gemini / MiniMax 格式。
          </p>
        </div>
      )}

      {/* ============ 保存按钮 ============ */}
      <div className="flex items-center gap-3 pt-2">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="px-5 py-2 text-sm rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 font-medium"
        >
          {saving ? '保存中...' : '保存设置'}
        </button>
        <button
          type="button"
          onClick={handleCheckUpdate}
          disabled={updateChecking}
          className="px-5 py-2 text-sm rounded border border-blue-300 bg-white text-blue-600 hover:bg-blue-50 disabled:opacity-50 font-medium"
        >
          {updateChecking ? '检测中...' : '检查更新'}
        </button>
        {saveMsg && (
          <span className={`text-xs ${saveMsg.includes('成功') ? 'text-green-600' : 'text-red-500'}`}>
            {saveMsg}
          </span>
        )}
        {updateResult && (
          <span className={`text-xs ${updateResult.includes('失败') ? 'text-red-500' : updateResult.includes('新版本') ? 'text-blue-600' : 'text-green-600'}`}>
            {updateResult}
          </span>
        )}
      </div>
    </div>
  )
}
