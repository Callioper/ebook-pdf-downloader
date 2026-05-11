export const API_BASE = '/api/v1'

export const PIPELINE_STEPS = [
  { key: 'fetch_metadata', label: '获取元数据' },
  { key: 'fetch_isbn', label: '获取ISBN' },
  { key: 'download_pages', label: '下载页面' },
  { key: 'convert_pdf', label: '转换PDF' },
  { key: 'ocr', label: 'OCR识别' },
  { key: 'bookmark', label: '目录处理' },
  { key: 'finalize', label: '完成处理' },
] as const

export const STATUS_LABELS: Record<string, string> = {
  pending: '等待中',
  running: '运行中',
  paused: '已暂停',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
}

export const STATUS_COLORS: Record<string, string> = {
  pending: 'bg-gray-200 text-gray-700',
  running: 'bg-blue-100 text-blue-700',
  paused: 'bg-yellow-100 text-yellow-700',
  completed: 'bg-green-100 text-green-700',
  failed: 'bg-red-100 text-red-700',
  cancelled: 'bg-yellow-100 text-yellow-700',
}

export const SEARCH_FIELDS = [
  { key: 'title', label: '书名' },
  { key: 'author', label: '作者' },
  { key: 'isbn', label: 'ISBN' },
  { key: 'publisher', label: '出版社' },
  { key: 'ss_code', label: 'SS码' },
  { key: 'book_id', label: 'Book ID' },
] as const

export const DB_SOURCES = ['DX_6.0', 'DX_2.0-5.0'] as const

export interface OcrEngineInfo {
  key: string
  name: string
  desc?: string
  needs_install?: boolean
  has_install?: boolean
}

export const OCR_ENGINES: OcrEngineInfo[] = [
  { key: 'tesseract', name: 'Tesseract OCR', desc: '内置引擎，需 chi_sim 语言包' },
  { key: 'paddleocr', name: 'PaddleOCR', desc: '百度引擎，需 Python 3.11 虚拟环境' },
  { key: 'llm_ocr', name: 'LLM OCR (视觉大模型)', desc: '需运行 lmstudio / ollama 加载本地视觉大模型', needs_install: true, has_install: false },
  { key: 'mineru', name: 'MinerU 线上 API', desc: '上海 AI Lab 精准解析，需 Token' },
  { key: 'paddleocr_online', name: 'PaddleOCR-VL-1.5 线上 API', desc: '百度 PaddleOCR 视觉大模型，需 Token 和端点' },
]

export const LLM_OCR_RECOMMENDED = [
  { model: 'qwen3-vl-4b-instruct', name: 'Qwen3-VL 4B (推荐)', note: '平衡精度/速度' },
  { model: 'qwen/qwen3-vl-8b', name: 'Qwen3-VL 8B', note: '更高精度' },
  { model: 'jamepeng2023/paddleocr-vl-1.5', name: 'PaddleOCR-VL 1.5', note: '速度最快' },
  { model: 'glm-ocr', name: 'GLM-OCR', note: '智谱 OCR' },
  { model: 'mineru2.5-pro-2604-1.2b@q8_0', name: 'MinerU 2.5 Pro (Q8)', note: '量化版' },
  { model: 'noctrex/paddleocr-vl-1.5', name: 'PaddleOCR-VL 1.5 (noctrex)', note: '备选' },
] as const
