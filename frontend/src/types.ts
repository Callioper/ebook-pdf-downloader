export interface BookCandidate {
  book_id?: string
  title: string
  author?: string
  isbn?: string
  publisher?: string
  year?: string
  language?: string
  format?: string
  size?: string
  md5?: string
  source: string
  [key: string]: unknown
}

export interface BookItem {
  book_id: string
  title: string
  author: string
  author_ss: string
  isbn: string
  isbn_ss: string
  publisher: string
  publisher_ss: string
  ss_code: string
  ss_code_ss: string
  language?: string
  format?: string
  size?: string
  source?: string
  [key: string]: unknown
}

export interface TaskItem {
  task_id: string
  book_id: string
  title: string
  isbn: string
  ss_code: string
  source: string
  bookmark?: string | null
  authors: string[]
  publisher: string
  status: TaskStatus
  current_step: string
  progress: number
  step_detail?: string
  step_eta?: string
  logs: string[]
  error: string
  report: TaskReport
  created_at: number
  updated_at: number
}

export interface TaskReport {
  book_id?: string
  title?: string
  source?: string
  ss_code?: string
  isbn?: string
  authors?: string[]
  publisher?: string
  pdf_path?: string
  page_count?: number
  bookmark?: string
  bookmark_applied?: boolean
  ocr_done?: boolean
  tmp_dir?: string
  output_file?: string
  completed_at?: string
  download_note?: string
  description?: string
  rating?: number
  tags?: string[]
  douban_toc?: string
  nlc_toc?: string
  [key: string]: unknown
}

export type TaskStatus = 'pending' | 'running' | 'paused' | 'completed' | 'failed' | 'cancelled'

export interface SearchParams {
  field?: string
  query?: string
  fuzzy?: boolean
  fields?: string[]
  queries?: string[]
  logics?: string[]
  fuzzies?: string[]
  page?: number
  page_size?: number
  source?: string
}

export interface SearchResult {
  total: number
  page: number
  page_size: number
  results: BookItem[]
  external_books: BookCandidate[]
}

export interface AppConfig {
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
  llm_ocr_endpoint: string
  llm_ocr_model: string
  llm_ocr_api_key: string
  llm_ocr_timeout: number
  [key: string]: unknown
}

export interface WSMessage {
  type: string
  task_id?: string
  task?: TaskItem
  status?: string
  current_step?: string
  progress?: number
  step?: string
  error?: string
  count?: number
  [key: string]: unknown
}
