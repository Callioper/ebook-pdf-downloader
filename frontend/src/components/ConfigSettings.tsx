import { useState, useEffect, useRef, useCallback, type ReactNode } from 'react'
import { useOutletContext } from 'react-router-dom'
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
  ai_vision_zhipu_key: string
  ai_vision_doubao_key: string
  ai_vision_provider: string
  ai_vision_endpoint_id: string  // Doubao Endpoint ID (ep-...)
  ai_vision_max_pages: number
  llm_ocr_endpoint: string
  llm_ocr_model: string
  llm_ocr_concurrency: number
  llm_ocr_detect_batch: number
  mineru_token: string
  mineru_model: string
  paddleocr_online_token: string
  paddleocr_online_mode: string
  paddleocr_online_endpoint: string
  ocr_confirm_enabled: boolean
  bookmark_confirm_enabled: boolean
  pdf_compress: boolean
  pdf_compress_half: boolean
  filename_template: string
  theme: string
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
  theme: 'auto',
  zfile_base_url: '',
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
  ai_vision_zhipu_key: '',
  ai_vision_doubao_key: '',
  ai_vision_endpoint_id: '',
  ai_vision_provider: 'openai_compatible',
  ai_vision_max_pages: 5,
  llm_ocr_endpoint: 'http://127.0.0.1:1234/v1',
  llm_ocr_model: '',
  llm_ocr_concurrency: 1,
  llm_ocr_detect_batch: 20,
  mineru_token: '',
  mineru_model: 'vlm',
  paddleocr_online_token: '',
  paddleocr_online_mode: 'spatial',
  paddleocr_online_endpoint: '',
  ocr_confirm_enabled: false,
  bookmark_confirm_enabled: false,
  pdf_compress: false,
  pdf_compress_half: true,
  filename_template: '{title}',
}

const OCR_ENGINES = [
  { key: 'tesseract', name: 'Tesseract OCR', desc: '内置引擎，需 chi_sim 语言包' },
  { key: 'paddleocr', name: 'PaddleOCR', desc: '百度引擎，需 Python 3.11 虚拟环境' },
  { key: 'llm_ocr', name: 'LLM OCR', desc: '大模型视觉识别，无需本地引擎' },
  { key: 'mineru', name: 'MinerU', desc: '线上 API 精准解析，需 Token' },
  { key: 'paddleocr_online', name: 'PaddleOCR-VL-1.5', desc: '线上 API，需 Token' },
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

const AI_VISION_PROVIDERS = [
  { key: 'ollama',   label: 'Ollama',           endpoint: 'http://localhost:11434/v1',           desc: '本地 Ollama 服务' },
  { key: 'lmstudio', label: 'LM Studio',        endpoint: 'http://127.0.0.1:1234/v1',           desc: '本地 LM Studio 服务' },
  { key: 'doubao',   label: 'Doubao (豆包)',     endpoint: 'https://ark.cn-beijing.volces.com/api/v3', desc: '火山引擎 ARK 平台' },
  { key: 'zhipu',    label: 'Zhipu (智谱)',     endpoint: 'https://open.bigmodel.cn/api/paas/v4', desc: '智谱 AI 开放平台 (glm-4.6v-flash 免费)' },
] as const

export default function ConfigSettings() {
  const { openTocModal } = useOutletContext<{ openTocModal: (pdfPath: string, taskId?: string) => void }>()
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [form, setForm] = useState<AppConfig>({ ...DEFAULT_CONFIG })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [aiModels, setAiModels] = useState<{ id: string; name: string }[]>([])
  const [fetchingModels, setFetchingModels] = useState(false)
  const [fetchModelsMsg, setFetchModelsMsg] = useState('')
  const [bookmarking, setBookmarking] = useState(false)
  const [bookmarkMsg, setBookmarkMsg] = useState('')
  const [visibleSecrets, setVisibleSecrets] = useState<Record<string, boolean>>({})

  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    database: false,
    download: true,
    sources: false,
    proxy: false,
    ocr: false,
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
  const [onlineEngineStatus, setOnlineEngineStatus] = useState<Record<string, 'ok' | 'fail' | ''>>({ mineru: '', paddleocr: '' })
  const [onlineTesting, setOnlineTesting] = useState<Record<string, boolean>>({ mineru: false, paddleocr: false })
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

  const fetchConfigStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/v1/config-status')
      const data = await res.json()
      if (!mountedRef.current) return
      const auto = data._auto || {}
      delete data._auto

      setConfig(data)
      const merged = { ...DEFAULT_CONFIG, ...data }
      setForm(merged)

      // Apply auto-detect results from consolidated response
      if (auto.database?.ok) {
        setDbStatus('green')
        if (auto.database.databases?.length > 0) setDbDetecting(false)
      }
      if (auto.ocr?.ok) {
        const langs = auto.ocr.languages || []
        setOcrMsg(langs.length ? `${langs.length} languages` : '已安装')
        setOcrChecking(false)
      }
    } catch (e) {
      if (mountedRef.current) setConfig(DEFAULT_CONFIG)
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [])

  useEffect(() => { fetchConfigStatus() }, [fetchConfigStatus])

  // Persist AI Vision settings to localStorage (avoid re-entering after clear)
  useEffect(() => {
    const keys: (keyof AppConfig)[] = ['ai_vision_model', 'ai_vision_endpoint_id', 'ai_vision_zhipu_key', 'ai_vision_doubao_key', 'ai_vision_provider', 'ai_vision_endpoint']
    const saved: Record<string, string> = {}
    keys.forEach(k => { const v = form[k]; if (v) saved[k] = String(v) })
    if (Object.keys(saved).length > 0) localStorage.setItem('ai_vision_cache', JSON.stringify(saved))
  }, [form.ai_vision_model, form.ai_vision_endpoint_id, form.ai_vision_zhipu_key, form.ai_vision_doubao_key, form.ai_vision_provider, form.ai_vision_endpoint])

  // Restore AI Vision from localStorage on mount
  useEffect(() => {
    if (!config) return
    try {
      const raw = localStorage.getItem('ai_vision_cache')
      if (!raw) return
      const saved = JSON.parse(raw)
      const updates: Partial<AppConfig> = {}
      if (saved.ai_vision_model) updates.ai_vision_model = saved.ai_vision_model
      if (saved.ai_vision_endpoint_id) updates.ai_vision_endpoint_id = saved.ai_vision_endpoint_id
      if (saved.ai_vision_zhipu_key) updates.ai_vision_zhipu_key = saved.ai_vision_zhipu_key
      if (saved.ai_vision_doubao_key) updates.ai_vision_doubao_key = saved.ai_vision_doubao_key
      if (saved.ai_vision_provider) updates.ai_vision_provider = saved.ai_vision_provider
      if (saved.ai_vision_endpoint) updates.ai_vision_endpoint = saved.ai_vision_endpoint
      if (Object.keys(updates).length > 0) setForm(prev => ({ ...prev, ...updates }))
    } catch {}
  }, [config])

  // Auto-detect AI Vision connectivity on startup
  const aiVisionAutoRef = useRef(false)
  useEffect(() => {
    if (!config || aiVisionAutoRef.current) return
    aiVisionAutoRef.current = true
    const p = config.ai_vision_provider || 'ollama'
    const ep = config.ai_vision_endpoint || ''
    const model = p === 'doubao' ? (config.ai_vision_endpoint_id || '') : (config.ai_vision_model || '')
    if (!ep || !model) return
    setAiVisionTest('testing')
    fetch('/api/v1/check-ai-vision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        endpoint: ep, model, provider: p,
        api_key: p === 'zhipu' ? (config.ai_vision_zhipu_key || '') : p === 'doubao' ? (config.ai_vision_doubao_key || '') : (config.ai_vision_api_key || ''),
        endpoint_id: config.ai_vision_endpoint_id,
      }),
    }).then(r => r.json()).then(d => {
      if (mountedRef.current) { setAiVisionTest(d.ok ? 'ok' : 'fail'); setAiVisionMsg(d.message || '') }
    }).catch(() => {
      if (mountedRef.current) { setAiVisionTest('fail'); setAiVisionMsg('连接失败') }
    })
  }, [config])

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
      } catch (e) { }
    }
    restoreZlib()
  }, [config, form.zlib_email, form.zlib_password, zlibChecked])

  // Auto-detect Tesseract + OCRmyPDF on mount
  useEffect(() => {
    if (!config) return
    handleDetectOcrEngine('tesseract')
    handleDetectOcrEngine('ocrmypdf')
  }, [config])

  // Auto-detect database on mount
  useEffect(() => {
    if (!config) return
    checkDbConnectivity()
  }, [config])

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
      } catch (e) { }
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
      } catch (e) { }
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




  // Update OCR header status when engine selection or engine states change
  useEffect(() => {
    const eng = form.ocr_engine || 'tesseract'
    const info = ocrEngines[eng]
    if (info) {
      setOcrStatus(info.installed ? 'green' : 'red')
      setOcrMsg(info.msg || (info.installed ? '已安装' : '未检测到'))
    }
  }, [form.ocr_engine, ocrEngines])

  // Auto-detect stacks on config load (health + login)
  const autoStacksRef = useRef(false)
  useEffect(() => {
    if (!config || autoStacksRef.current) return
    autoStacksRef.current = true
    const check = async () => {
      setStacksChecking(true)
      try {
        const cfg = config!
        const url = cfg.stacks_base_url || form.stacks_base_url || 'http://localhost:7788'
        const health = await fetch(url + '/api/health', { signal: AbortSignal.timeout(3000) })
        if (!mountedRef.current) return
        if (!health.ok) { setStacksStatus('red'); return }

        const uname = cfg.stacks_username || form.stacks_username
        const passwd = cfg.stacks_password || form.stacks_password
        if (uname && passwd) {
          try {
            const loginRes = await fetch('/api/v1/check-stacks', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ url, username: uname, password: passwd }),
              signal: AbortSignal.timeout(5000),
            })
            const ld = await loginRes.json()
            if (mountedRef.current) setStacksStatus(ld.ok ? 'green' : 'yellow')
          } catch { if (mountedRef.current) setStacksStatus('yellow') }
          return
        }

        const key = cfg.stacks_api_key || form.stacks_api_key || ''
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

  // Auto-detect online API connectivity on startup
  const autoOnlineRef = useRef(false)
  useEffect(() => {
    if (!config || autoOnlineRef.current) return
    autoOnlineRef.current = true
    const cfg = config
    const check = async () => {
      if (cfg.mineru_token) {
        setOnlineTesting(prev => ({ ...prev, mineru: true }))
        try {
          const r = await fetch('/api/v1/check-mineru', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: cfg.mineru_token }) })
          const d = await r.json()
          if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, mineru: d.ok ? 'ok' : 'fail' }))
        } catch { if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, mineru: 'fail' })) }
        if (mountedRef.current) setOnlineTesting(prev => ({ ...prev, mineru: false }))
      }
      if (cfg.paddleocr_online_token) {
        setOnlineTesting(prev => ({ ...prev, paddleocr: true }))
        try {
          const r = await fetch('/api/v1/check-paddleocr-online', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: cfg.paddleocr_online_token }) })
          const d = await r.json()
          if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, paddleocr: d.ok ? 'ok' : 'fail' }))
        } catch { if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, paddleocr: 'fail' })) }
        if (mountedRef.current) setOnlineTesting(prev => ({ ...prev, paddleocr: false }))
      }
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
    } catch (e) { }
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
        } catch (e) { }
}, 1500)
    } catch (e) {
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
      if (mountedRef.current) {
        setOcrEngines(prev => ({
          ...prev,
          [engine]: { installed: false, installing: false, msg: '检测失败' },
        }))
      }
    }
  }

  const handleTestMineru = async () => {
    setOnlineTesting(prev => ({ ...prev, mineru: true }))
    setOnlineEngineStatus(prev => ({ ...prev, mineru: '' }))
    try {
      const res = await fetch('/api/v1/check-mineru', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: form.mineru_token || '' }),
      })
      const data = await res.json()
      if (!mountedRef.current) return
      setOnlineEngineStatus(prev => ({ ...prev, mineru: data.ok ? 'ok' : 'fail' }))
    } catch {
      if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, mineru: 'fail' }))
    }
    if (mountedRef.current) setOnlineTesting(prev => ({ ...prev, mineru: false }))
  }

  const handleTestPaddleocrOnline = async () => {
    setOnlineTesting(prev => ({ ...prev, paddleocr: true }))
    setOnlineEngineStatus(prev => ({ ...prev, paddleocr: '' }))
    try {
      const res = await fetch('/api/v1/check-paddleocr-online', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: form.paddleocr_online_token || '' }),
      })
      const data = await res.json()
      if (!mountedRef.current) return
      setOnlineEngineStatus(prev => ({ ...prev, paddleocr: data.ok ? 'ok' : 'fail' }))
    } catch {
      if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, paddleocr: 'fail' }))
    }
    if (mountedRef.current) setOnlineTesting(prev => ({ ...prev, paddleocr: false }))
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
        </div>
      )}

      {/* ============ 下载 ============ */}
      <SectionHeader
        title="下载"
        summary={<><StatusDot status={form.download_dir ? 'green' : 'yellow'} /> {form.download_dir ? '已设置' : '请设置下载目录'}</>}
        color="blue"
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

          {/* 文件名模板 */}
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">文件名模板</label>
            <input type="text" value={form.filename_template || '{title}'}
              onChange={(e) => updateForm({ filename_template: e.target.value })}
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono dark:bg-gray-700 dark:text-gray-100 dark:border-gray-600" />
            <p className="text-[10px] text-gray-400 mt-1">
              可用字段: {'{title}'} {'{author}'} {'{publisher}'} {'{isbn}'} {'{ss_code}'} {'{source}'} {'{year}'} {'{book_id}'}
            </p>
            {form.filename_template && form.filename_template.includes('{') && (
              <div className="mt-2 p-2 bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded">
                <p className="text-[10px] text-gray-500 mb-1">预览:</p>
                <p className="text-xs font-mono text-gray-700 dark:text-gray-300 break-all">
                  {(form.filename_template || '')
                    .replace(/\{title\}/g, '至高的清贫')
                    .replace(/\{author\}/g, '作者名')
                    .replace(/\{publisher\}/g, '出版社')
                    .replace(/\{isbn\}/g, '9787XXXXXXXX')
                    .replace(/\{ss_code\}/g, 'SS12345678')
                    .replace(/\{source\}/g, 'zlibrary')
                    .replace(/\{year\}/g, '2024')
                    .replace(/\{book_id\}/g, '123456')
                  }.pdf
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ============ 来源 ============ */}
      <SectionHeader
        title="来源"
        summary={<><StatusDot status={zlibConnected ? 'green' : stacksStatus} /> {zlibConnected ? 'Z-Library 已连接' : stacksStatus === 'green' ? 'Stacks 已连接' : '请配置来源'}</>}
        color="green"
        expanded={expanded.sources}
        onToggle={() => toggleSection('sources')}
      />
      {expanded.sources && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 space-y-3">
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
            <span className="text-xs font-medium text-gray-600">Z-Library</span>
            <div className="grid grid-cols-2 gap-2 mt-1.5">
              <input
                type="text"
                value={form.zlib_email || ''}
                onChange={(e) => updateForm({ zlib_email: e.target.value })}
                placeholder="邮箱"
                spellCheck={false}
                className="rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
              <div className="relative">
                <input
                  type={visibleSecrets['zlib'] ? 'text' : 'password'}
                  value={form.zlib_password || ''}
                  onChange={(e) => updateForm({ zlib_password: e.target.value })}
                  placeholder="密码"
                  className="rounded border border-gray-300 px-2 py-1.5 pr-8 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500 w-full"
                />
                <button type="button"
                  onClick={() => setVisibleSecrets(prev => ({ ...prev, zlib: !prev['zlib'] }))}
                  className="absolute right-1 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1"
                  title={visibleSecrets['zlib'] ? '隐藏' : '显示'}
                >
                  {visibleSecrets['zlib'] ? '🙈' : '👁'}
                </button>
              </div>
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
              <span className="text-xs font-medium text-gray-600">Stacks（Anna's Archive）</span>
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
            <div className="relative">
              <input
                type={visibleSecrets['stacks_key'] ? 'text' : 'password'}
                value={String(form.stacks_api_key || '')}
                onChange={(e) => setForm((prev) => ({ ...prev, stacks_api_key: e.target.value }))}
                placeholder="Admin API Key（可选，填写账号密码后优先使用 session 登录）"
                className="w-full rounded border border-gray-300 px-2 py-1.5 pr-8 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500 mt-1.5"
              />
              <button type="button"
                onClick={() => setVisibleSecrets(prev => ({ ...prev, stacks_key: !prev['stacks_key'] }))}
                className="absolute right-1 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1"
                title={visibleSecrets['stacks_key'] ? '隐藏' : '显示'}
              >
                {visibleSecrets['stacks_key'] ? '🙈' : '👁'}
              </button>
            </div>
            {/* Account login (unified with ZLibrary style) */}
            <span className="block text-xs font-medium text-gray-600 mt-2">账户登录</span>
            <div className="grid grid-cols-2 gap-2 mt-1">
              <input
                type="text" value={form.stacks_username || ''}
                onChange={(e) => updateForm({ stacks_username: e.target.value })}
                placeholder="用户名" spellCheck={false}
                className="rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
              />
              <div className="relative">
                <input
                  type={visibleSecrets['stacks_pw'] ? 'text' : 'password'}
                  value={form.stacks_password || ''}
                  onChange={(e) => updateForm({ stacks_password: e.target.value })}
                  placeholder="密码"
                  className="rounded border border-gray-300 px-2 py-1.5 pr-8 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500 w-full"
                />
                <button type="button"
                  onClick={() => setVisibleSecrets(prev => ({ ...prev, stacks_pw: !prev['stacks_pw'] }))}
                  className="absolute right-1 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1"
                  title={visibleSecrets['stacks_pw'] ? '隐藏' : '显示'}
                >
                  {visibleSecrets['stacks_pw'] ? '🙈' : '👁'}
                </button>
              </div>
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
                      } catch (e) { }
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
    {form.ocr_engine === 'llm_ocr' ? (
      <>
        <StatusDot status={form.llm_ocr_endpoint ? 'green' : 'red'} />
        <span className="text-xs">LLM OCR {form.llm_ocr_endpoint ? '已配置' : '未配置'}</span>
      </>
    ) : form.ocr_engine === 'mineru' ? (
      <>
        <StatusDot status={onlineEngineStatus.mineru === 'ok' ? 'green' : onlineEngineStatus.mineru === 'fail' ? 'red' : null} />
        <span className="text-xs">MinerU 线上 API{onlineEngineStatus.mineru === 'ok' ? ' 已启用' : onlineEngineStatus.mineru === 'fail' ? ' 连接失败' : ''}</span>
      </>
    ) : form.ocr_engine === 'paddleocr_online' ? (
      <>
        <StatusDot status={onlineEngineStatus.paddleocr === 'ok' ? 'green' : onlineEngineStatus.paddleocr === 'fail' ? 'red' : null} />
        <span className="text-xs">PaddleOCR-VL-1.5 线上 API{onlineEngineStatus.paddleocr === 'ok' ? ' 已启用' : onlineEngineStatus.paddleocr === 'fail' ? ' 连接失败' : ''}</span>
      </>
    ) : (
      <>
        <StatusDot status={form.ocr_engine === 'paddleocr' ? 'green' : ocrEngines['tesseract']?.installed ? 'green' : 'red'} />
        <span className="text-xs">OCRmyPDF ({OCR_ENGINES.find(e => e.key === form.ocr_engine)?.name || form.ocr_engine}) {ocrStatus === 'green' ? '已安装' : (ocrStatus === null ? '' : '未安装')}</span>
      </>
    )}
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

          {/* 引擎切换区 */}
          <div className="border-t border-gray-200 pt-3">
            <span className="text-xs font-medium text-gray-600 mb-2 block">引擎切换</span>
            <div className="grid grid-cols-2 gap-2">
              {OCR_ENGINES.filter(eng => eng.key !== 'llm_ocr' && eng.key !== 'mineru' && eng.key !== 'paddleocr_online').map((eng) => {
                const info = ocrEngines[eng.key] || { installed: eng.key === 'llm_ocr', msg: '' }
                const isSelected = form.ocr_engine === eng.key
                return (
                  <div
                    key={eng.key}
                    className={`rounded border p-2.5 ${isSelected ? 'border-blue-400 bg-blue-50' : 'border-gray-200 bg-white'}`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-medium text-gray-700">{eng.name}</span>
                      <div className="flex items-center gap-1">
                        <StatusDot status={info?.installed ? 'green' : info?.msg ? 'red' : null} />
                      </div>
                    </div>
                    <p className="text-xs text-gray-400 mb-2">{eng.desc}</p>
                    {eng.key !== 'llm_ocr' && info?.msg && (
                      <p className={`text-xs mb-1.5 ${info.installed ? 'text-green-600' : 'text-red-500'}`}>
                        {info.msg}
                      </p>
                    )}
                    {eng.key !== 'llm_ocr' && eng.key === 'paddleocr' && !info?.installed && (
                      <p className="text-xs text-gray-400 mb-1.5">需要 Python 3.11 虚拟环境，点击安装自动搭建</p>
                    )}
                    {eng.key !== 'llm_ocr' && eng.key === 'paddleocr' && info?.installed && (info as any)?.venv && (
                      <p className="text-xs text-green-600 mb-1.5">运行环境: {(info as any).venv}</p>
                    )}
                    <div className="flex items-center gap-1.5">
                      {eng.key !== 'llm_ocr' && (
                        <>
                          <button
                            type="button"
                            onClick={() => handleDetectOcrEngine(eng.key)}
                            className="px-2 py-1 text-xs rounded border border-gray-300 bg-white hover:bg-gray-100 text-gray-500"
                          >
                            检测
                          </button>
                          <button
                            type="button"
                            onClick={() => handleInstallOcrEngine(eng.key)}
                            disabled={info?.installing}
                            className="px-2 py-1 text-xs rounded bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-50"
                          >
                            {info?.installing ? '安装中...' : '安装'}
                          </button>
                        </>
                      )}
                      {eng.key === form.ocr_engine ? null : (
                        <button
                          type="button"
                          onClick={() => updateForm({ ocr_engine: eng.key })}
                          className="px-2 py-1 text-xs rounded text-blue-600 hover:bg-blue-50 ml-auto"
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

          {/* Tesseract 语言包状态 */}
          {form.ocr_engine !== 'llm_ocr' && (
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

                    }
                  }}
                  className="px-2 py-1 text-xs rounded bg-orange-500 text-white hover:bg-orange-600"
                >
                  安装语言包
                </button>
              )}
            </div>
          </div>
          )}

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
          {form.ocr_engine !== 'llm_ocr' && (
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
          )}

          {/* ---------- LLM OCR 启用/停用 ---------- */}
          <div className="border-t border-gray-200 pt-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-gray-700">
                {form.ocr_engine === 'llm_ocr' ? (
                  <span className="text-blue-600">LLM OCR 已启用</span>
                ) : (
                  <span className="text-gray-500">LLM OCR</span>
                )}
              </span>
              <button
                type="button"
                onClick={() => updateForm({ ocr_engine: form.ocr_engine === 'llm_ocr' ? 'tesseract' : 'llm_ocr' })}
                className={`px-3 py-1 text-xs rounded ${
                  form.ocr_engine === 'llm_ocr'
                    ? 'bg-gray-200 text-gray-600 hover:bg-gray-300'
                    : 'bg-blue-500 text-white hover:bg-blue-600'
                }`}
              >
                {form.ocr_engine === 'llm_ocr' ? '停用并回到 OCRmyPDF' : '启用 LLM OCR'}
              </button>
            </div>
          </div>

          {form.ocr_engine === 'llm_ocr' && (
          <div className="space-y-3 pt-2">
            <p className="text-xs text-gray-500">
               使用视觉大模型逐框识别文字层。需要运行 lmstudio / ollama 加载对应模型。
              推荐模型已验证中文 PDF 可用。
            </p>

            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">接口地址</label>
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
                  className="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 whitespace-nowrap">
                  {llmTesting ? '测试中...' : '检测'}
                </button>
              </div>
              {llmTestMsg && <p className={`text-xs mt-1 ${llmTestMsg.includes('成功')||llmTestMsg.includes('OK') ? 'text-green-600' : 'text-red-500'}`}>{llmTestMsg}</p>}
            </div>

            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">模型名称</label>
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
              <label className="text-xs font-medium text-gray-600 block mb-1">
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

            <div className="mt-2">
              <label className="text-xs font-medium text-gray-600 block mb-1">
                版面检测批次: {form.llm_ocr_detect_batch || 20} 页/批
              </label>
              <input type="range" min="5" max="50" step="5"
                value={form.llm_ocr_detect_batch || 20}
                onChange={(e) => updateForm({ llm_ocr_detect_batch: parseInt(e.target.value) })}
                className="w-full" />
              <div className="flex justify-between text-xs text-gray-400">
                <span>5 页 (低内存)</span><span>50 页 (更快)</span>
              </div>
              <p className="text-xs text-gray-400 mt-0.5">Surya 版面检测每批处理页数。内存不足时降低。</p>
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
          {/* ---------- MinerU 线上 API ---------- */}
          <div className="border-t border-gray-200 pt-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-gray-700">
                {form.ocr_engine === 'mineru' ? (
                  <span className="text-blue-600">MinerU 线上 API 已启用</span>
                ) : (
                  <span className="text-gray-500">MinerU 线上 API</span>
                )}
              </span>
              <button
                type="button"
                onClick={() => updateForm({ ocr_engine: form.ocr_engine === 'mineru' ? 'tesseract' : 'mineru' })}
                className={`px-3 py-1 text-xs rounded ${
                  form.ocr_engine === 'mineru'
                    ? 'bg-gray-200 text-gray-600 hover:bg-gray-300'
                    : 'bg-blue-500 text-white hover:bg-blue-600'
                }`}
              >
                {form.ocr_engine === 'mineru' ? '停用 MinerU' : '启用 MinerU'}
              </button>
            </div>
          </div>
          {form.ocr_engine === 'mineru' && (
          <div className="space-y-3 pt-2">
               <p className="text-xs text-gray-500">
               使用 MinerU v4 精准解析 API 进行文档 OCR。PDF 将上传至 MinerU 服务器处理。
               仅限中国大陆网络访问，单文件 ≤200MB / ≤200页。
               <span className="text-orange-500 ml-1">实验功能，识别可能会有重复</span>
             </p>
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">API Token</label>
              <div className="relative">
                <input type={visibleSecrets['mineru'] ? 'text' : 'password'}
                  value={form.mineru_token || ''}
                  onChange={(e) => updateForm({ mineru_token: e.target.value })}
                  placeholder="输入 MinerU API Token（Bearer 认证）"
                  className="w-full rounded border border-gray-300 px-2 py-1.5 pr-8 text-xs font-mono" />
                <button type="button"
                  onClick={() => setVisibleSecrets(prev => ({ ...prev, mineru: !prev['mineru'] }))}
                  className="absolute right-1 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1"
                  title={visibleSecrets['mineru'] ? '隐藏' : '显示'}
                >
                  {visibleSecrets['mineru'] ? '🙈' : '👁'}
                </button>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleTestMineru}
                disabled={onlineTesting.mineru || !form.mineru_token}
                className="px-3 py-1 text-xs rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed">
                {onlineTesting.mineru ? '测试中...' : '检测'}
              </button>
              {onlineEngineStatus.mineru === 'ok' && (
                <span className="text-xs text-green-600">连接正常</span>
              )}
              {onlineEngineStatus.mineru === 'fail' && (
                <span className="text-xs text-red-500">连接失败</span>
              )}
            </div>
            <p className="text-xs text-gray-400">
              需要先申请 Token：<a href="https://mineru.net/apiManage/docs" target="_blank" className="text-blue-500 hover:underline">MinerU API 文档</a>
            </p>
          </div>
          )}
          {/* ---------- PaddleOCR-VL-1.5 线上 API ---------- */}
          <div className="border-t border-gray-200 pt-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-gray-700">
                {form.ocr_engine === 'paddleocr_online' ? (
                  <span className="text-blue-600">PaddleOCR-VL-1.5 线上 API 已启用</span>
                ) : (
                  <span className="text-gray-500">PaddleOCR-VL-1.5 线上 API</span>
                )}
              </span>
              <button
                type="button"
                onClick={() => updateForm({ ocr_engine: form.ocr_engine === 'paddleocr_online' ? 'tesseract' : 'paddleocr_online' })}
                className={`px-3 py-1 text-xs rounded ${
                  form.ocr_engine === 'paddleocr_online'
                    ? 'bg-gray-200 text-gray-600 hover:bg-gray-300'
                    : 'bg-blue-500 text-white hover:bg-blue-600'
                }`}
              >
                {form.ocr_engine === 'paddleocr_online' ? '停用 PaddleOCR-VL-1.5' : '启用 PaddleOCR-VL-1.5'}
              </button>
            </div>
          </div>
          {form.ocr_engine === 'paddleocr_online' && (
          <div className="space-y-3 pt-2">
               <p className="text-xs text-gray-500">
               使用百度 PaddleOCR-VL-1.5 视觉大模型进行文档版面解析。
               支持中英文文档，无需本地 GPU。
               <span className="text-orange-500 ml-1">实验功能，识别可能会有重复</span>
            </p>
            <div>
               <label className="text-xs font-medium text-gray-600 block mb-1.5">识别模式 <span className="text-[11px] text-blue-500 ml-1">推荐逐框识别，次选混合识别</span></label>
              <div className="flex rounded border border-gray-300 overflow-hidden text-xs">
                {[
                  { key: 'spatial', label: '空间分配（快）' },
                  { key: 'perbox', label: '逐框识别（慢）' },
                  { key: 'hybrid', label: '混合识别' },
                ].map(({ key, label }) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => updateForm({ paddleocr_online_mode: key })}
                    className={`flex-1 py-1.5 text-center transition-colors ${
                      (form.paddleocr_online_mode || 'spatial') === key
                        ? 'bg-blue-500 text-white'
                        : 'bg-white text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-gray-400 mt-1">
                {(form.paddleocr_online_mode || 'spatial') === 'spatial' && '段落文字精准，行识别不精确'}
                {(form.paddleocr_online_mode || 'spatial') === 'perbox' && '行识别精准，有乱码风险'}
                {(form.paddleocr_online_mode || 'spatial') === 'hybrid' && '逐框为主、空间填补，可能产生识别重复'}
              </p>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">Access Token</label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <input type={visibleSecrets['paddle'] ? 'text' : 'password'}
                    value={form.paddleocr_online_token || ''}
                    onChange={(e) => updateForm({ paddleocr_online_token: e.target.value })}
                    placeholder="输入 PaddleOCR access token"
                    className="w-full rounded border border-gray-300 px-2 py-1.5 pr-8 text-xs font-mono" />
                  <button type="button"
                    onClick={() => setVisibleSecrets(prev => ({ ...prev, paddle: !prev['paddle'] }))}
                    className="absolute right-1 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1"
                    title={visibleSecrets['paddle'] ? '隐藏' : '显示'}
                  >
                    {visibleSecrets['paddle'] ? '🙈' : '👁'}
                  </button>
                </div>
                <button
                  type="button"
                  onClick={handleTestPaddleocrOnline}
                  disabled={onlineTesting.paddleocr || !form.paddleocr_online_token}
                  className="px-3 py-1 text-xs rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap">
                  {onlineTesting.paddleocr ? '测试中...' : '检测'}
                </button>
              </div>
              {onlineEngineStatus.paddleocr === 'ok' && (
                <p className="text-xs text-green-600 mt-1">连接正常</p>
              )}
              {onlineEngineStatus.paddleocr === 'fail' && (
                <p className="text-xs text-red-500 mt-1">连接失败</p>
              )}
            </div>
            <p className="text-xs text-gray-400">
              从 <a href="https://aistudio.baidu.com/paddleocr/task" target="_blank" className="text-blue-500 hover:underline">PaddleOCR 控制台</a> 获取 Access Token。
              <a href="https://ai.baidu.com/ai-doc/AISTUDIO/Cmkz2m0ma" target="_blank" className="text-blue-500 hover:underline ml-2">API 文档</a>
            </p>
          </div>
          )}

          {/* PDF 压缩（OCR 后执行） */}
          <div className="border-t border-gray-200 dark:border-gray-700 pt-3 mt-3">
            <label className="text-xs font-medium text-gray-600 block mb-1">PDF 黑白二值化压缩</label>
            <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer dark:text-gray-300">
              <input type="checkbox" checked={form.pdf_compress || false}
                onChange={(e) => updateForm({ pdf_compress: e.target.checked })}
                className="rounded" />
              启用（OCR 后自动执行）
            </label>
            {form.pdf_compress && (
              <div className="ml-5 mt-1 space-y-0.5">
                <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 cursor-pointer">
                  <input type="radio" name="compress_res" checked={!form.pdf_compress_half}
                    onChange={() => updateForm({ pdf_compress_half: false })} />
                  全分辨率（~300 DPI）
                </label>
                <label className="flex items-center gap-2 text-xs text-gray-500 dark:text-gray-400 cursor-pointer">
                  <input type="radio" name="compress_res" checked={!!form.pdf_compress_half}
                    onChange={() => updateForm({ pdf_compress_half: true })} />
                  半分辨率（~150 DPI，文件更小）
                </label>
              </div>
            )}
          </div>

          <div className="flex items-center gap-2 pt-3">
            <input type="checkbox" id="ocr_confirm_enabled"
              checked={form.ocr_confirm_enabled ?? false}
              onChange={(e) => updateForm({ ocr_confirm_enabled: e.target.checked })}
              className="rounded" />
            <label htmlFor="ocr_confirm_enabled" className="text-xs font-medium text-gray-600 block mb-1">
              管道执行到 OCR 步骤时弹出确认对话框
            </label>
          </div>
        </div>
      )}

      {/* ============ 书签 ============ */}
      <SectionHeader
        title="书签"
        summary={form.ai_vision_enabled ? (form.ai_vision_provider === 'doubao' ? (form.ai_vision_endpoint_id || 'Doubao') : (form.ai_vision_model || '已启用')) : '智能目录未启用'}
        color="gray"
        expanded={expanded.bookmarks}
        onToggle={() => toggleSection('bookmarks')}
      />
      {expanded.bookmarks && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <input type="checkbox" id="ai_vision_enabled"
              checked={form.ai_vision_enabled ?? true}
              onChange={(e) => updateForm({ ai_vision_enabled: e.target.checked })} className="rounded" />
            <label htmlFor="ai_vision_enabled" className="text-xs">启用智能目录提取</label>
          </div>

          {/* API 提供商 */}
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">API 提供商</label>
            <div className="flex rounded border border-gray-300 overflow-hidden text-xs">
              {AI_VISION_PROVIDERS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    const p = AI_VISION_PROVIDERS.find(p2 => p2.key === key)!
                    updateForm({
                      ai_vision_provider: key,
                      ai_vision_endpoint: p.endpoint,
                      ai_vision_model: key === 'zhipu' ? 'glm-4.6v-flash' : form.ai_vision_model,
                    })
                  }}
                  className={`flex-1 py-1.5 text-center transition-colors ${
                    (form.ai_vision_provider || 'ollama') === key
                      ? 'bg-blue-500 text-white'
                      : 'bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {(() => {
              const p = AI_VISION_PROVIDERS.find(p2 => p2.key === (form.ai_vision_provider || 'ollama'))
              return p ? <p className="text-[11px] text-gray-400 mt-1">{p.desc}</p> : null
            })()}
          </div>

          {/* API 端点 */}
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">API 端点</label>
            <input type="text" value={form.ai_vision_endpoint || ''}
              onChange={(e) => updateForm({ ai_vision_endpoint: e.target.value })}
              placeholder="https://..."
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
          </div>

          {/* Doubao Endpoint ID */}
          {form.ai_vision_provider === 'doubao' && (
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">Endpoint ID</label>
              <input type="text" value={form.ai_vision_endpoint_id ?? ''}
                onChange={(e) => updateForm({ ai_vision_endpoint_id: e.target.value })}
                placeholder="ep-2025xxxx-xxxxx"
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
              <details className="mt-2">
                <summary className="text-[11px] text-blue-500 cursor-pointer">Doubao 配置教程</summary>
                <div className="mt-1 text-[11px] text-gray-500 space-y-1">
                  <p>Endpoint ID 是火山引擎 ARK 平台的推理接入点 ID，格式为 <code className="text-gray-600 bg-gray-100 px-1 rounded">ep-...</code>。</p>
                  <p><b>获取步骤：</b></p>
                  <ol className="list-decimal list-inside space-y-0.5">
                    <li>访问 <a href="https://console.volcengine.com/ark" target="_blank" className="text-blue-500">火山引擎 ARK 控制台</a></li>
                    <li>开通服务：在「模型推理」页面开通 ARK 服务</li>
                    <li>创建接入点：点击「创建接入点」，选择 Doubao 模型</li>
                    <li>复制生成的 Endpoint ID（<code className="text-gray-600 bg-gray-100 px-1 rounded">ep-2025xxxx-xxxxx</code>）</li>
                  </ol>
                  <p><b>建议模型：</b>Doubao-1.5-vision-pro-32k / Doubao-1.5-vision-lite / Doubao-1.5-vision-pro</p>
                  <p><b>API Key：</b>在 ARK 控制台「API Key 管理」创建，填写到下方 API Key 字段。</p>
                </div>
              </details>
            </div>
          )}

          {/* Zhipu guide */}
          {form.ai_vision_provider === 'zhipu' && (
            <details className="mt-1">
              <summary className="text-[11px] text-blue-500 cursor-pointer">Zhipu 配置说明</summary>
              <div className="mt-1 text-[11px] text-gray-500 space-y-1">
                <p>使用 <code className="text-gray-600 bg-gray-100 px-1 rounded">glm-4.6v-flash</code>，最新免费的视觉理解模型。</p>
                <p>访问 <a href="https://open.bigmodel.cn" target="_blank" className="text-blue-500">智谱 AI 开放平台</a>，创建 API Key 后填写到下方 API Key 字段即可使用。</p>
              </div>
            </details>
          )}

          {/* 模型名称 */}
          {form.ai_vision_provider === 'doubao' ? (
            <p className="text-[11px] text-gray-400">模型由 Endpoint ID 指定（{form.ai_vision_endpoint_id || '未填写'}）</p>
          ) : form.ai_vision_provider === 'zhipu' ? (
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">模型名称</label>
              <select value={form.ai_vision_model || 'glm-4.6v-flash'}
                onChange={(e) => updateForm({ ai_vision_model: e.target.value })}
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono dark:bg-gray-700 dark:text-gray-100 dark:border-gray-600">
                <option value="glm-4.6v-flash">glm-4.6v-flash</option>
                <option value="glm-4.1v-thinking-flash">glm-4.1v-thinking-flash</option>
                <option value="glm-4v-flash">glm-4v-flash</option>
              </select>
            </div>
          ) : (
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">模型名称</label>
            <div className="flex gap-1">
              <input type="text" value={form.ai_vision_model || ''}
                onChange={(e) => updateForm({ ai_vision_model: e.target.value })}
                placeholder={
                  form.ai_vision_provider === 'zhipu' ? 'glm-4.6v-flash' :
                  'minicpm-v'
                }
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
                        api_key: (form.ai_vision_provider === 'ollama' || form.ai_vision_provider === 'lmstudio') ? '' : form.ai_vision_api_key,
                        provider: form.ai_vision_provider,
                        endpoint_id: form.ai_vision_endpoint_id,
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
              >
                {fetchingModels ? '...' : '获取模型'}
              </button>
            </div>
            {aiModels.length > 0 && (
              <select value={form.ai_vision_model || ''}
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
          )}

          {/* API Key — conditional per provider */}
          {form.ai_vision_provider === 'zhipu' && (
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">API Key</label>
              <div className="relative">
                <input type={visibleSecrets['aivision_zhipu'] ? 'text' : 'password'}
                  value={form.ai_vision_zhipu_key || ''}
                  onChange={(e) => updateForm({ ai_vision_zhipu_key: e.target.value })}
                  placeholder="智谱 API Key"
                  className="w-full rounded border border-gray-300 px-2 py-1.5 pr-8 text-xs font-mono" />
                <button type="button"
                  onClick={() => setVisibleSecrets(prev => ({ ...prev, aivision_zhipu: !prev['aivision_zhipu'] }))}
                  className="absolute right-1 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1">
                  {visibleSecrets['aivision_zhipu'] ? '🙈' : '👁'}
                </button>
              </div>
            </div>
          )}
          {form.ai_vision_provider === 'doubao' && (
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">API Key</label>
              <div className="relative">
                <input type={visibleSecrets['aivision_doubao'] ? 'text' : 'password'}
                  value={form.ai_vision_doubao_key || ''}
                  onChange={(e) => updateForm({ ai_vision_doubao_key: e.target.value })}
                  placeholder="ARK API Key"
                  className="w-full rounded border border-gray-300 px-2 py-1.5 pr-8 text-xs font-mono" />
                <button type="button"
                  onClick={() => setVisibleSecrets(prev => ({ ...prev, aivision_doubao: !prev['aivision_doubao'] }))}
                  className="absolute right-1 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1">
                  {visibleSecrets['aivision_doubao'] ? '🙈' : '👁'}
                </button>
              </div>
            </div>
          )}
          {form.ai_vision_provider === 'openai_compatible' && (
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">API Key</label>
              <div className="relative">
                <input type={visibleSecrets['aivision'] ? 'text' : 'password'}
                  value={form.ai_vision_api_key || ''}
                  onChange={(e) => updateForm({ ai_vision_api_key: e.target.value })}
                  placeholder="sk-...  (支持 {env:VAR_NAME})"
                  className="w-full rounded border border-gray-300 px-2 py-1.5 pr-8 text-xs font-mono" />
                <button type="button"
                  onClick={() => setVisibleSecrets(prev => ({ ...prev, aivision: !prev['aivision'] }))}
                  className="absolute right-1 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-1">
                  {visibleSecrets['aivision'] ? '🙈' : '👁'}
                </button>
              </div>
            </div>
          )}

          {/* 检测按钮 */}
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
                    api_key: form.ai_vision_provider === 'zhipu' ? form.ai_vision_zhipu_key : form.ai_vision_provider === 'doubao' ? form.ai_vision_doubao_key : (form.ai_vision_provider === 'ollama' || form.ai_vision_provider === 'lmstudio') ? '' : form.ai_vision_api_key,
                    provider: form.ai_vision_provider,
                    endpoint_id: form.ai_vision_endpoint_id,
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
            {aiVisionTest === 'testing' ? '测试中...' : '检测'}
          </button>
          {aiVisionMsg && (
            <p className={`text-xs ${aiVisionTest === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
              {aiVisionMsg}
            </p>
          )}

          {/* 确认对话框 */}
          <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
            <input type="checkbox" id="bookmark_confirm_enabled"
              checked={form.bookmark_confirm_enabled ?? false}
              onChange={(e) => updateForm({ bookmark_confirm_enabled: e.target.checked })}
              className="rounded" />
            <label htmlFor="bookmark_confirm_enabled" className="text-xs font-medium text-gray-600">
              管道执行到书签步骤时弹出确认对话框
            </label>
          </div>
        </div>
      )}

      {/* ======== 主题 ======== */}
      <div className="border-t border-gray-200 pt-3">
        <label className="text-xs font-medium text-gray-600 block mb-1.5">主题</label>
        <div className="flex rounded border border-gray-300 overflow-hidden text-xs">
          {[
            { key: 'auto', label: '自动' },
            { key: 'light', label: '白昼' },
            { key: 'dark', label: '黑夜' },
          ].map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => updateForm({ theme: key })}
              className={`flex-1 py-1.5 text-center transition-colors ${
                (form.theme || 'auto') === key
                  ? 'bg-blue-500 text-white'
                  : 'bg-white text-gray-600 hover:bg-gray-50'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

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
          className="px-5 py-2 text-sm rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 font-medium"
        >
          {updateChecking ? '检测中...' : '检查更新'}
        </button>
        <button
          type="button"
          onClick={async () => {
            setBookmarking(true)
            setBookmarkMsg('')
            try {
              const res = await fetch('/api/v1/select-file', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filters: [{ name: 'PDF', extensions: ['pdf'] }] }),
              })
              const data = await res.json()
              if (!data.path) { setBookmarkMsg('未选择文件'); return }

              setBookmarkMsg('已选择文件，请在弹出的目录识别窗口中操作')
              openTocModal(data.path)
            } catch (e) {
              setBookmarkMsg(String(e))
            }
            setBookmarking(false)
          }}
          disabled={bookmarking}
          className="px-5 py-2 text-sm rounded bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 font-medium"
        >
          {bookmarking ? '处理中...' : '智能书签'}
        </button>
        {saveMsg && (
          <span className={`text-xs ${saveMsg.includes('成功') ? 'text-green-600' : 'text-red-500'}`}>
            {saveMsg}
          </span>
        )}
        {updateResult && (
          <span className={`text-xs px-2 py-1 rounded ${updateResult.includes('失败') ? 'text-red-600 bg-red-50' : updateResult.includes('新版本') ? 'text-blue-600 bg-blue-50 font-semibold' : 'text-green-600 bg-green-50'}`}>
            {updateResult}
          </span>
        )}
        {bookmarkMsg && (
          <span className={`text-xs ${bookmarkMsg.includes('失败') || bookmarkMsg.includes('未选择') ? 'text-red-500' : 'text-green-600'}`}>
            {bookmarkMsg}
          </span>
        )}
      </div>
    </div>
  )
}
