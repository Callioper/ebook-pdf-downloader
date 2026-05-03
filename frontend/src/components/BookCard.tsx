import type { BookItem, BookCandidate } from '../types'

interface BookCardProps {
  book: BookItem | BookCandidate
  selected?: boolean
  onClick?: () => void
  onDownload?: () => void
}

function isExternal(book: BookItem | BookCandidate): book is BookCandidate {
  const s = book.source || ''
  return s.startsWith('annas_archive') || s.startsWith('zlibrary')
}

function sourceLabel(source: string) {
  if (source.startsWith('annas_archive')) return 'Anna\'s Archive'
  if (source.startsWith('zlibrary')) return 'Z-Library'
  return source || '本地数据库'
}

export default function BookCard({ book, selected, onClick, onDownload }: BookCardProps) {
  if (isExternal(book)) {
    return (
      <div
        onClick={onClick}
        className={`p-4 rounded-lg border cursor-pointer transition-all ${
          selected
            ? 'border-blue-400 bg-blue-50 shadow-sm'
            : 'border-gray-200 bg-white hover:border-blue-200 hover:shadow-sm'
        }`}
      >
        <div className="flex justify-between items-start">
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-medium text-gray-900 truncate" title={book.title}>
              {book.title || '(无标题)'}
            </h3>
            <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
              {book.author && <span>作者: {book.author}</span>}
              {book.publisher && <span>出版社: {book.publisher}</span>}
              {book.year && <span>出版: {book.year}</span>}
            </div>
            <div className="mt-2 flex flex-wrap gap-1 text-xs">
              {book.format && (
                <span className="px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">{book.format}</span>
              )}
              {book.size && (
                <span className="px-1.5 py-0.5 rounded bg-green-100 text-green-700">{book.size}</span>
              )}
              {book.language && (
                <span className="px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">{book.language}</span>
              )}
              {book.isbn && (
                <span className="px-1.5 py-0.5 rounded bg-yellow-100 text-yellow-700">ISBN: {book.isbn}</span>
              )}
            </div>
          </div>
          {onDownload && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDownload()
              }}
              className="ml-3 shrink-0 px-3 py-1.5 bg-blue-600 text-white text-xs rounded-md hover:bg-blue-700 transition-colors"
            >
              开始任务
            </button>
          )}
        </div>
      </div>
    )
  }

  return (
    <div
      onClick={onClick}
      className={`p-4 rounded-lg border cursor-pointer transition-all ${
        selected
          ? 'border-blue-400 bg-blue-50 shadow-sm'
          : 'border-gray-200 bg-white hover:border-blue-200 hover:shadow-sm'
      }`}
    >
      <div className="flex justify-between items-start">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-medium text-gray-900 truncate" title={book.title}>
            {book.title || '(无标题)'}
          </h3>
          <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
            {book.author && <span>作者: {book.author}</span>}
            {book.publisher && <span>出版社: {book.publisher}</span>}
            {book.isbn && <span>ISBN: {book.isbn}</span>}
            {book.ss_code && <span>SS: {book.ss_code}</span>}
          </div>
        </div>
        {onDownload && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              onDownload()
            }}
            className="ml-3 shrink-0 px-3 py-1.5 bg-blue-600 text-white text-xs rounded-md hover:bg-blue-700 transition-colors"
          >
            下载
          </button>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-1 text-xs text-gray-400">
        <span>ID: {book.book_id}</span>
      </div>
    </div>
  )
}
