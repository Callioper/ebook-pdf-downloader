import { useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { useStore } from '../stores/useStore'
import { API_BASE } from '../constants'
import type { BookItem, BookCandidate } from '../types'
import BookCard from '../components/BookCard'
import TaskListPanel from '../components/TaskListPanel'

export default function ResultsPage() {
  const navigate = useNavigate()
  const searchResults = useStore((s) => s.searchResults)
  const externalBooks = useStore((s) => s.externalBooks)
  const searchTotal = useStore((s) => s.searchTotal)
  const loading = useStore((s) => s.loading)
  const [selected, setSelected] = useState<BookItem | BookCandidate | null>(null)
  const [creating, setCreating] = useState(false)

  const { annaBooks, zlibBooks } = useMemo(() => ({
    annaBooks: externalBooks.filter((b) => b.source === 'annas_archive'),
    zlibBooks: externalBooks.filter((b) => b.source === 'zlibrary'),
  }), [externalBooks])

  const handleDownload = async (book: BookItem | BookCandidate) => {
    setCreating(true)
    try {
      const bookSource = book.source || (book as any).source_db || 'DX_6.0'
      const { data: task } = await axios.post(`${API_BASE}/tasks`, {
        book_id: book.book_id || book.md5 || '',
        title: book.title || '',
        isbn: book.isbn || (book as any).isbn_ss || '',
        ss_code: (book as any).ss_code || (book as any).ss_code_ss || '',
        source: bookSource,
        authors: book.author ? [book.author] : [],
        publisher: book.publisher || (book as any).publisher_ss || '',
      })
      // Immediately start the task after creation
      await axios.post(`${API_BASE}/tasks/${task.task_id}/start`)
      navigate(`/tasks/${task.task_id}`)
    } catch (e: any) {
      alert('创建任务失败: ' + e.message)
    } finally {
      setCreating(false)
    }
  }

  const handleBatchDownload = async () => {
    if (!selected) return
    await handleDownload(selected)
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-800">
            搜索结果 ({searchTotal} 条)
          </h2>
          <div className="flex items-center gap-2">
            {selected && (
              <button
                onClick={handleBatchDownload}
                disabled={creating}
                className="px-4 py-1.5 bg-green-600 text-white text-sm rounded-md hover:bg-green-700 disabled:opacity-50"
              >
                {creating ? '创建中...' : `下载: ${selected.title?.slice(0, 15)}...`}
              </button>
            )}
          </div>
        </div>

        {loading ? (
          <div className="text-center py-10 text-gray-400">搜索中...</div>
        ) : searchResults.length === 0 ? (
          <div className="text-center py-10 text-gray-400">暂无结果</div>
        ) : (
          <div className="space-y-2">
            {searchResults.map((book) => (
              <BookCard
                key={book.book_id}
                book={book}
                selected={selected?.book_id === book.book_id}
                onClick={() => setSelected(book)}
                onDownload={() => handleDownload(book)}
              />
            ))}
          </div>
        )}

        {annaBooks.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-gray-600 border-b pb-1">
              外部来源 - Anna's Archive
            </h3>
            {annaBooks.map((book, idx) => (
              <BookCard
                key={`aa-${book.md5 || idx}`}
                book={book}
                selected={selected?.md5 === book.md5}
                onClick={() => setSelected(book)}
                onDownload={() => handleDownload(book)}
              />
            ))}
          </div>
        )}

        {zlibBooks.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-gray-600 border-b pb-1">
              外部来源 - Z-Library
            </h3>
            {zlibBooks.map((book, idx) => (
              <BookCard
                key={`zlib-${book.book_id || idx}`}
                book={book}
                selected={selected?.book_id === book.book_id}
                onClick={() => setSelected(book)}
                onDownload={() => handleDownload(book)}
              />
            ))}
          </div>
        )}

        {searchTotal > 0 && (
          <div className="text-center text-xs text-gray-400">
            共 {searchTotal} 条记录
          </div>
        )}
      </div>

      <div className="space-y-4">
        <TaskListPanel compact />
      </div>
    </div>
  )
}
