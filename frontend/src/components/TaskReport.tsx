import type { TaskReport } from '../types'

interface TaskReportProps {
  report: TaskReport
  finishedDir?: string
  createdAt?: number
}

export default function TaskReport({ report, finishedDir, createdAt }: TaskReportProps) {
  if (!report || Object.keys(report).length === 0) {
    return (
      <div className="text-xs text-gray-400 p-4 text-center">
        暂无报告数据
      </div>
    )
  }

  const formatTime = (ts: number) => {
    const d = new Date(ts * 1000)
    return d.toLocaleString('zh-CN', { hour12: false })
  }

  const fields = [
    { key: 'book_id', label: 'Book ID' },
    { key: 'title', label: '书名' },
    { key: 'authors', label: '作者', render: (v: unknown) => Array.isArray(v) ? (v as string[]).join(', ') : String(v) },
    { key: 'publisher', label: '出版社' },
    { key: 'source', label: '来源' },
    { key: 'isbn', label: 'ISBN' },
    { key: 'ss_code', label: 'SS码' },
    { key: 'page_count', label: '页数' },
    { key: 'download_source', label: '下载渠道' },
    { key: 'ocr_done', label: 'OCR', render: (v: unknown) => v ? '已完成' : '未执行' },
  ]

  const visibleFields = fields.filter(
    (f) => report[f.key] !== undefined && report[f.key] !== '' && report[f.key] !== null
  )

  const hasBookmark = !!report.bookmark
  const pdfPath = report.pdf_path || ''
  const outputFile = report.output_file || ''

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="px-4 py-2 bg-gray-50 border-b border-gray-100">
        <h4 className="text-xs font-semibold text-gray-600">任务报告</h4>
      </div>
      <div className="p-4">
        <div style={{ display: 'grid', gridTemplateColumns: hasBookmark ? '1fr 1fr' : '1fr', gap: 16 }}>
          <div>
            <table className="w-full text-sm">
              <tbody>
                {createdAt && (
                  <tr className="border-b border-gray-50">
                    <td className="py-1.5 pr-3 text-xs text-gray-500 w-20 align-top">创建时间</td>
                    <td className="py-1.5 text-xs text-gray-800">{formatTime(createdAt)}</td>
                  </tr>
                )}
                {visibleFields.map((f) => (
                  <tr key={f.key} className="border-b border-gray-50 last:border-0">
                    <td className="py-1.5 pr-3 text-xs text-gray-500 w-20 align-top">{f.label}</td>
                    <td className="py-1.5 text-xs text-gray-800 break-all">
                      {f.render ? f.render(report[f.key] as any) : String(report[f.key])}
                    </td>
                  </tr>
                ))}
                {pdfPath && (
                  <tr className="border-b border-gray-50">
                    <td className="py-1.5 pr-3 text-xs text-gray-500 w-20 align-top">PDF路径</td>
                    <td className="py-1.5 text-xs text-gray-800 break-all font-mono">{pdfPath}</td>
                  </tr>
                )}
                {outputFile && (
                  <tr className="border-b border-gray-50">
                    <td className="py-1.5 pr-3 text-xs text-gray-500 w-20 align-top">OCR路径</td>
                    <td className="py-1.5 text-xs text-gray-800 break-all font-mono">{outputFile}</td>
                  </tr>
                )}
                {report.completed_at && (
                  <tr className="border-b border-gray-50 last:border-0">
                    <td className="py-1.5 pr-3 text-xs text-gray-500 w-20 align-top">完成时间</td>
                    <td className="py-1.5 text-xs text-gray-800">{report.completed_at}</td>
                  </tr>
                )}
                {report.download_note && (
                  <tr className="border-b border-gray-50 last:border-0">
                    <td className="py-1.5 pr-3 text-xs text-gray-500 w-20 align-top">备注</td>
                    <td className="py-1.5 text-xs text-gray-800">{report.download_note}</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {hasBookmark && (
            <div style={{ borderLeft: '1px solid #e5e7eb', paddingLeft: 16 }}>
              <div className="text-xs font-semibold text-gray-600 mb-2">目录书签</div>
              <div
                className="text-xs text-gray-700 whitespace-pre-wrap"
                style={{
                  maxHeight: 360,
                  overflowY: 'auto',
                  lineHeight: 1.7,
                  fontFamily: 'inherit',
                }}
              >
                {report.bookmark}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
