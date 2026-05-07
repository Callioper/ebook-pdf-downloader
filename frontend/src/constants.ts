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
