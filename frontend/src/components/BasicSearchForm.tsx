import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useStore } from '../stores/useStore'
import { SEARCH_FIELDS } from '../constants'

export default function BasicSearchForm() {
  const navigate = useNavigate()
  const fetchSearchResults = useStore((s) => s.fetchSearchResults)
  const setError = useStore((s) => s.setError)
  const [field, setField] = useState('title')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) {
      setError('请输入搜索关键词')
      return
    }
    setLoading(true)
    await fetchSearchResults({ field, query, page: 1, page_size: 20 })
    setLoading(false)
    navigate('/results')
  }

  return (
    <form onSubmit={handleSearch} className="flex items-center gap-2">
      <select
        value={field}
        onChange={(e) => setField(e.target.value)}
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
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="输入关键词搜索..."
        className="flex-1 border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:ring-2 focus:ring-blue-200 focus:border-blue-400 outline-none"
      />
      <button
        type="submit"
        disabled={loading}
        className="px-6 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
      >
        {loading ? '搜索中...' : '搜索'}
      </button>
    </form>
  )
}
