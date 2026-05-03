import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../stores/useStore'
import { SEARCH_FIELDS } from '../constants'

interface SearchRow {
  id: number
  field: string
  query: string
  fuzzy: boolean
  logic: string
}

export default function AdvancedSearchForm() {
  const navigate = useNavigate()
  const fetchSearchResults = useStore((s) => s.fetchSearchResults)
  const setError = useStore((s) => s.setError)
  const [loading, setLoading] = useState(false)
  const [rows, setRows] = useState<SearchRow[]>([
    { id: 1, field: 'title', query: '', fuzzy: true, logic: 'AND' },
  ])
  const [pageSize, setPageSize] = useState(20)

  const addRow = () => {
    setRows((prev) => [
      ...prev,
      { id: Date.now(), field: 'author', query: '', fuzzy: true, logic: 'AND' },
    ])
  }

  const removeRow = (id: number) => {
    if (rows.length <= 1) return
    setRows((prev) => prev.filter((r) => r.id !== id))
  }

  const updateRow = (id: number, updates: Partial<SearchRow>) => {
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...updates } : r)))
  }

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    const validRows = rows.filter((r) => r.query.trim())
    if (validRows.length === 0) {
      setError('请输入至少一个搜索条件')
      return
    }

    setLoading(true)
    await fetchSearchResults({
      fields: validRows.map((r) => r.field),
      queries: validRows.map((r) => r.query),
      logics: validRows.map((r) => r.logic),
      fuzzies: validRows.map((r) => String(r.fuzzy)),
      page: 1,
      page_size: pageSize,
    })
    setLoading(false)
    navigate('/results')
  }

  return (
    <form onSubmit={handleSearch} className="space-y-3">
      {rows.map((row, idx) => (
        <div key={row.id} className="flex items-center gap-2">
          {idx > 0 && (
            <select
              value={row.logic}
              onChange={(e) => updateRow(row.id, { logic: e.target.value })}
              className="border border-gray-300 rounded px-2 py-2 text-xs bg-white"
            >
              <option value="AND">AND</option>
              <option value="OR">OR</option>
              <option value="NOT">NOT</option>
            </select>
          )}
          <select
            value={row.field}
            onChange={(e) => updateRow(row.id, { field: e.target.value })}
            className="border border-gray-300 rounded-lg px-3 py-2.5 text-sm bg-white focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none"
          >
            {SEARCH_FIELDS.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </select>
          <input
            type="text"
            value={row.query}
            onChange={(e) => updateRow(row.id, { query: e.target.value })}
            placeholder="输入关键词..."
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none"
          />
          <label className="flex items-center gap-1 text-xs text-gray-500">
            <input
              type="checkbox"
              checked={row.fuzzy}
              onChange={(e) => updateRow(row.id, { fuzzy: e.target.checked })}
              className="rounded"
            />
            模糊
          </label>
          {rows.length > 1 && (
            <button
              type="button"
              onClick={() => removeRow(row.id)}
              className="text-red-400 hover:text-red-600 text-lg"
              title="删除"
            >
              ×
            </button>
          )}
        </div>
      ))}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={addRow}
          className="text-xs text-blue-600 hover:text-blue-800"
        >
          + 添加条件
        </button>
        <select
          value={pageSize}
          onChange={(e) => setPageSize(parseInt(e.target.value))}
          className="border border-gray-300 rounded px-2 py-1 text-xs"
        >
          <option value={20}>20条/页</option>
          <option value={50}>50条/页</option>
          <option value={100}>100条/页</option>
        </select>
        <button
          type="submit"
          disabled={loading}
          className="px-6 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {loading ? '搜索中...' : '高级搜索'}
        </button>
      </div>
    </form>
  )
}
