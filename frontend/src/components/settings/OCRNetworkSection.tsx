import React, { useState, useEffect, useRef, useCallback } from 'react'
import { SectionProps } from './types'
import { LLM_OCR_RECOMMENDED } from '../../constants'

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

> ⚠️ 添加后需**重启终端或IDE**使 PATH 生效，或使用完整路径验证：
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

function OCRNetworkSection({ form, updateForm, mountedRef }: SectionProps) {
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
  const [aiModels, setAiModels] = useState<{ id: string; name: string }[]>([])
  const [fetchingModels, setFetchingModels] = useState(false)
  const [fetchModelsMsg, setFetchModelsMsg] = useState('')
  const [aiVisionTest, setAiVisionTest] = useState<'testing' | 'ok' | 'fail' | null>(null)
  const [aiVisionMsg, setAiVisionMsg] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')
  const [updateChecking, setUpdateChecking] = useState(false)
  const [updateResult, setUpdateResult] = useState('')

  // --- OCR logic ---
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
  }, [form.ocr_engine, mountedRef])

  const handleDetectOcrEngine = useCallback(async (engine: string) => {
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
        } as any,
      }))
    } catch (e) {
      if (mountedRef.current) {
        setOcrEngines(prev => ({
          ...prev,
          [engine]: { installed: false, installing: false, msg: '检测失败' },
        }))
      }
    }
  }, [mountedRef])

  const handleInstallOcrEngine = useCallback(async (engine: string) => {
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
  }, [mountedRef])

  const handleTestMineru = useCallback(async () => {
    setOnlineTesting(prev => ({ ...prev, mineru: true }))
    setOnlineEngineStatus(prev => ({ ...prev, mineru: '' }))
    try {
      const res = await fetch('/api/v1/check-mineru', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: (form as any).mineru_token || '' }),
      })
      const data = await res.json()
      if (!mountedRef.current) return
      setOnlineEngineStatus(prev => ({ ...prev, mineru: data.ok ? 'ok' : 'fail' }))
    } catch {
      if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, mineru: 'fail' }))
    }
    if (mountedRef.current) setOnlineTesting(prev => ({ ...prev, mineru: false }))
  }, [form, mountedRef])

  const handleTestPaddleocrOnline = useCallback(async () => {
    setOnlineTesting(prev => ({ ...prev, paddleocr: true }))
    setOnlineEngineStatus(prev => ({ ...prev, paddleocr: '' }))
    try {
      const res = await fetch('/api/v1/check-paddleocr-online', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: (form as any).paddleocr_online_token || '' }),
      })
      const data = await res.json()
      if (!mountedRef.current) return
      setOnlineEngineStatus(prev => ({ ...prev, paddleocr: data.ok ? 'ok' : 'fail' }))
    } catch {
      if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, paddleocr: 'fail' }))
    }
    if (mountedRef.current) setOnlineTesting(prev => ({ ...prev, paddleocr: false }))
  }, [form, mountedRef])

  // Auto-detect OCR engine statuses
  const autoOcrRef = useRef(false)
  useEffect(() => {
    if (autoOcrRef.current) return
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
            } as any,
          }))
        })
        .catch(() => {})
    })
    const defaultEngine = form.ocr_engine || 'tesseract'
    fetch(`/api/v1/check-ocr?engine=${encodeURIComponent(defaultEngine)}`)
      .then((r) => r.json())
      .then((data) => {
        if (!mountedRef.current) return
        setOcrStatus(data.ok ? 'green' : 'red')
        setOcrMsg(data.version || data.message || (data.ok ? '已安装' : '未检测到'))
      })
      .catch(() => {})
  }, [form.ocr_engine, mountedRef])

  // Update OCR header status when engine selection changes
  useEffect(() => {
    const eng = form.ocr_engine || 'tesseract'
    const info = ocrEngines[eng]
    if (info) {
      setOcrStatus(info.installed ? 'green' : 'red')
      setOcrMsg(info.msg || (info.installed ? '已安装' : '未检测到'))
    }
  }, [form.ocr_engine, ocrEngines])

  // Auto-detect online API connectivity
  const autoOnlineRef = useRef(false)
  useEffect(() => {
    if (autoOnlineRef.current) return
    autoOnlineRef.current = true
    const check = async () => {
      if ((form as any).mineru_token) {
        setOnlineTesting(prev => ({ ...prev, mineru: true }))
        try {
          const r = await fetch('/api/v1/check-mineru', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: (form as any).mineru_token }) })
          const d = await r.json()
          if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, mineru: d.ok ? 'ok' : 'fail' }))
        } catch { if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, mineru: 'fail' })) }
        if (mountedRef.current) setOnlineTesting(prev => ({ ...prev, mineru: false }))
      }
      if ((form as any).paddleocr_online_token) {
        setOnlineTesting(prev => ({ ...prev, paddleocr: true }))
        try {
          const r = await fetch('/api/v1/check-paddleocr-online', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token: (form as any).paddleocr_online_token }) })
          const d = await r.json()
          if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, paddleocr: d.ok ? 'ok' : 'fail' }))
        } catch { if (mountedRef.current) setOnlineEngineStatus(prev => ({ ...prev, paddleocr: 'fail' })) }
        if (mountedRef.current) setOnlineTesting(prev => ({ ...prev, paddleocr: false }))
      }
    }
    check()
  }, [mountedRef])

  // --- Save / Update ---
  const handleSave = useCallback(async () => {
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
      setSaveMsg('保存成功')
      setTimeout(() => setSaveMsg(''), 2000)
    } catch (e: any) {
      setSaveMsg('保存失败: ' + (e.message || '未知错误'))
    }
    setSaving(false)
  }, [form, mountedRef])

  const handleCheckUpdate = useCallback(async () => {
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
  }, [mountedRef])

  return (
    <div className="space-y-3">
      {/* OCRmyPDF 独立状态区 */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">OCRmyPDF 状态</label>
        <div className="flex items-center gap-2">
          <StatusDot status={(ocrEngines['ocrmypdf'] as any)?.installed ? 'green' : (ocrEngines['ocrmypdf'] as any)?.msg ? 'red' : null} />
          <span className="text-xs text-gray-500">
            {(ocrEngines['ocrmypdf'] as any)?.msg || '点击检测'}
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
            disabled={(ocrEngines['ocrmypdf'] as any)?.installing}
            className="px-2 py-1 text-xs rounded bg-orange-500 text-white hover:bg-orange-600 disabled:opacity-50"
          >
            {(ocrEngines['ocrmypdf'] as any)?.installing ? '安装中...' : '一键安装'}
          </button>
        </div>
      </div>

      {/* 引擎切换区 */}
      <div className="border-t border-gray-200 pt-3">
        <span className="text-xs font-medium text-gray-600 mb-2 block">引擎切换</span>
        <div className="grid grid-cols-2 gap-2">
          {OCR_ENGINES.filter(eng => eng.key !== 'llm_ocr' && eng.key !== 'mineru' && eng.key !== 'paddleocr_online').map((eng) => {
            const info = (ocrEngines[eng.key] as any) || { installed: eng.key === 'llm_ocr', msg: '' }
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
            value={(form as any).ocr_oversample || 200}
            onChange={(e) => updateForm({ ocr_oversample: parseInt(e.target.value) } as any)}
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
          <span className="text-xs text-gray-400">越低越快，150-400，推荐 200</span>
        </div>
      </div>

      {/* OCR 安装指引 */}
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

      {/* LLM OCR */}
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
              <input value={(form as any).llm_ocr_endpoint || 'http://127.0.0.1:1234/v1'}
                onChange={(e) => updateForm({ llm_ocr_endpoint: e.target.value } as any)}
                placeholder="http://127.0.0.1:1234/v1"
                className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
              <button onClick={async () => {
                setLlmTesting(true); setLlmTestMsg('');
                try {
                  const r = await fetch('/api/v1/check-llm-ocr', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ endpoint: (form as any).llm_ocr_endpoint, model: (form as any).llm_ocr_model })
                  });
                  const d = await r.json();
                  setLlmTestMsg(d.message || (d.ok ? 'OK' : 'Failed'));
                } catch (e) { setLlmTestMsg(String(e)); }
                setLlmTesting(false);
              }} disabled={llmTesting}
                className="px-3 py-1.5 text-xs rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 whitespace-nowrap">
                {llmTesting ? '测试中...' : '检测'}
              </button>
            </div>
            {llmTestMsg && <p className={`text-xs mt-1 ${llmTestMsg.includes('成功') || llmTestMsg.includes('OK') ? 'text-green-600' : 'text-red-500'}`}>{llmTestMsg}</p>}
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">模型名称</label>
            <div className="flex gap-2">
              <input value={(form as any).llm_ocr_model || ''}
                onChange={(e) => updateForm({ llm_ocr_model: e.target.value } as any)}
                placeholder="qwen3-vl-4b-instruct"
                className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
              <button onClick={async () => {
                setLlmFetching(true); setLlmFetchMsg('');
                try {
                  const r = await fetch('/api/v1/fetch-llm-models', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ endpoint: (form as any).llm_ocr_endpoint })
                  });
                  const d = await r.json();
                  if (d.ok && d.models.length > 0) {
                    setLlmModels(d.models);
                    setLlmFetchMsg(`${d.models.length} 个模型`);
                  } else {
                    setLlmFetchMsg(d.message || '无可用模型');
                  }
                } catch (e) { setLlmFetchMsg(String(e)); }
                setLlmFetching(false);
              }} disabled={llmFetching || !(form as any).llm_ocr_endpoint}
                className="px-2 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-50 whitespace-nowrap">
                {llmFetching ? '...' : '拉取模型'}
              </button>
            </div>
            {llmModels.length > 0 && (
              <select value={(form as any).llm_ocr_model || ''}
                onChange={(e) => updateForm({ llm_ocr_model: e.target.value } as any)}
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
              并发数: {(form as any).llm_ocr_concurrency || 1}
            </label>
            <input type="range" min="1" max="5" step="1"
              value={(form as any).llm_ocr_concurrency || 1}
              onChange={(e) => updateForm({ llm_ocr_concurrency: parseInt(e.target.value) } as any)}
              className="w-full" />
            <div className="flex justify-between text-xs text-gray-400">
              <span>1 (默认)</span><span>5 (最快)</span>
            </div>
          </div>
          <div className="mt-2">
            <label className="text-xs font-medium text-gray-600 block mb-1">
              版面检测批次: {(form as any).llm_ocr_detect_batch || 20} 页/批
            </label>
            <input type="range" min="5" max="50" step="5"
              value={(form as any).llm_ocr_detect_batch || 20}
              onChange={(e) => updateForm({ llm_ocr_detect_batch: parseInt(e.target.value) } as any)}
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
                  onClick={() => updateForm({ llm_ocr_model: m.model } as any)}
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

      {/* MinerU */}
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
            <input value={(form as any).mineru_token || ''}
              onChange={(e) => updateForm({ mineru_token: e.target.value } as any)}
              placeholder="输入 MinerU API Token（Bearer 认证）"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleTestMineru}
              disabled={onlineTesting.mineru || !(form as any).mineru_token}
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

      {/* PaddleOCR-VL-1.5 */}
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
                  onClick={() => updateForm({ paddleocr_online_mode: key } as any)}
                  className={`flex-1 py-1.5 text-center transition-colors ${
                    ((form as any).paddleocr_online_mode || 'spatial') === key
                      ? 'bg-blue-500 text-white'
                      : 'bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-gray-400 mt-1">
              {((form as any).paddleocr_online_mode || 'spatial') === 'spatial' && '段落文字精准，行识别不精确'}
              {((form as any).paddleocr_online_mode || 'spatial') === 'perbox' && '行识别精准，有乱码风险'}
              {((form as any).paddleocr_online_mode || 'spatial') === 'hybrid' && '逐框为主、空间填补，可能产生识别重复'}
            </p>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">Access Token</label>
            <div className="flex gap-2">
              <input value={(form as any).paddleocr_online_token || ''}
                onChange={(e) => updateForm({ paddleocr_online_token: e.target.value } as any)}
                placeholder="输入 PaddleOCR access token"
                className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
              <button
                type="button"
                onClick={handleTestPaddleocrOnline}
                disabled={onlineTesting.paddleocr || !(form as any).paddleocr_online_token}
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

      <div className="flex items-center gap-2 pt-3">
        <input type="checkbox" id="ocr_confirm_enabled"
          checked={(form as any).ocr_confirm_enabled ?? false}
          onChange={(e) => updateForm({ ocr_confirm_enabled: e.target.checked } as any)}
          className="rounded" />
        <label htmlFor="ocr_confirm_enabled" className="text-xs font-medium text-gray-600">
          管道执行到 OCR 步骤时弹出确认对话框
        </label>
      </div>

      {/* ============ AI Vision / 书签 ============ */}
      <div className="border-t border-gray-200 pt-3">
        <span className="text-xs font-medium text-gray-600 mb-2 block">AI Vision 目录提取</span>
        <div className="flex items-center gap-2">
          <input type="checkbox" id="ai_vision_enabled"
            checked={(form as any).ai_vision_enabled ?? true}
            onChange={(e) => updateForm({ ai_vision_enabled: e.target.checked } as any)} className="rounded" />
          <label htmlFor="ai_vision_enabled" className="text-xs">启用 AI Vision 目录提取</label>
        </div>
        <div className="mt-2">
          <label className="text-xs font-medium text-gray-600 block mb-1">API 端点</label>
          <input type="text" value={(form as any).ai_vision_endpoint || ''}
            onChange={(e) => updateForm({ ai_vision_endpoint: e.target.value } as any)}
            placeholder={
              (form as any).ai_vision_provider === 'gemini' ? 'https://generativelanguage.googleapis.com/v1beta' :
              (form as any).ai_vision_provider === 'azure' ? 'https://{resource}.openai.azure.com' :
              (form as any).ai_vision_provider === 'anthropic' || (form as any).ai_vision_provider === 'minimax_anthropic' ? 'https://api.anthropic.com' :
              (form as any).ai_vision_provider === 'minimax_openai' ? 'https://api.minimaxi.com/v1' :
              'http://127.0.0.1:12345/v1'
            }
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
        </div>
        <div className="mt-2">
          <label className="text-xs font-medium text-gray-600 block mb-1">模型名称</label>
          <div className="flex gap-1">
            <input type="text" value={(form as any).ai_vision_model || ''}
              onChange={(e) => updateForm({ ai_vision_model: e.target.value } as any)}
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
                      endpoint: (form as any).ai_vision_endpoint,
                      api_key: (form as any).ai_vision_api_key,
                      provider: (form as any).ai_vision_provider,
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
              disabled={fetchingModels || !(form as any).ai_vision_endpoint}
              className="px-2 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-50 whitespace-nowrap"
              title="从提供商拉取可用模型列表"
            >
              {fetchingModels ? '...' : '获取模型'}
            </button>
          </div>
          {aiModels.length > 0 && (
            <select
              value={(form as any).ai_vision_model || ''}
              onChange={(e) => updateForm({ ai_vision_model: e.target.value } as any)}
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
        <div className="mt-2">
          <label className="text-xs font-medium text-gray-600 block mb-1">API Key</label>
          <input type="password" value={(form as any).ai_vision_api_key || ''}
            onChange={(e) => updateForm({ ai_vision_api_key: e.target.value } as any)}
            placeholder="sk-...  (支持 {env:VAR_NAME})"
            className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
        </div>
        <div className="mt-2">
          <label className="text-xs font-medium text-gray-600 block mb-1">API 格式</label>
          <select value={(form as any).ai_vision_provider || 'openai_compatible'}
            onChange={(e) => {
              const newProvider = e.target.value
              const defaultEndpoint = AI_VISION_ENDPOINTS[newProvider] || ''
              updateForm({
                ai_vision_provider: newProvider,
                ai_vision_endpoint: defaultEndpoint,
              } as any)
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
        {(form as any).ai_vision_provider === 'custom' && (
          <div className="flex items-center gap-2 mt-2">
            <input type="checkbox" id="ai_vision_messages_api"
              checked={(form as any).ai_vision_messages_api ?? false}
              onChange={(e) => updateForm({ ai_vision_messages_api: e.target.checked } as any)} className="rounded" />
            <label htmlFor="ai_vision_messages_api" className="text-xs font-medium text-gray-600">
              使用 Anthropic Messages API 格式 (默认 OpenAI Chat Completions)
            </label>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3 mt-2">
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">DPI</label>
            <input type="number" value={(form as any).ai_vision_dpi ?? 150}
              onChange={(e) => updateForm({ ai_vision_dpi: parseInt(e.target.value) || 150 } as any)}
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
                  endpoint: (form as any).ai_vision_endpoint,
                  model: (form as any).ai_vision_model,
                  api_key: (form as any).ai_vision_api_key,
                  provider: (form as any).ai_vision_provider,
                  messages_api: (form as any).ai_vision_messages_api,
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
          className="px-3 py-1.5 mt-2 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-50"
        >
          {aiVisionTest === 'testing' ? '测试中...' : '检测'}
        </button>
        {aiVisionMsg && (
          <p className={`text-xs mt-1 ${aiVisionTest === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
            {aiVisionMsg}
          </p>
        )}
        <p className="text-xs text-gray-400 mt-1">
          阶段1 从 OCR 文字层提取目录（免费），阶段2 用 AI Vision 从目录页图片提取。
          支持 OpenAI 兼容 / Gemini / MiniMax 格式。
        </p>
        <div className="flex items-center gap-2 mt-2">
          <input type="checkbox" id="bookmark_confirm_enabled"
            checked={(form as any).bookmark_confirm_enabled ?? false}
            onChange={(e) => updateForm({ bookmark_confirm_enabled: e.target.checked } as any)}
            className="rounded" />
          <label htmlFor="bookmark_confirm_enabled" className="text-xs font-medium text-gray-600">
            管道执行到书签步骤时弹出确认对话框
          </label>
        </div>
      </div>

      {/* ============ 主题 ============ */}
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
                ((form as any).theme || 'auto') === key
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
      </div>
    </div>
  )
}

export default React.memo(OCRNetworkSection)
