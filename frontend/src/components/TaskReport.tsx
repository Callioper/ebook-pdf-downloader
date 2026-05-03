import type { TaskReport } from '../types'

interface TaskReportProps {
  report: TaskReport
}

export default function TaskReport({ report }: TaskReportProps) {
  if (!report || Object.keys(report).length === 0) {
    return (
      <div className="text-xs text-gray-400 p-4 text-center">
        暂无报告数据
      </div>
    )
  }

  const fields = [
    { key: 'title', label: '书名' },
    { key: 'book_id', label: 'Book ID' },
    { key: 'isbn', label: 'ISBN' },
    { key: 'ss_code', label: 'SS码' },
    { key: 'source', label: '来源' },
    { key: 'page_count', label: '页数' },
    { key: 'ocr_done', label: 'OCR', render: (v: boolean) => v ? '已完成' : '未执行' },
    { key: 'bookmark_applied', label: '目录', render: (v: boolean) => v ? '已应用' : '未应用' },
    { key: 'pdf_path', label: 'PDF路径' },
    { key: 'completed_at', label: '完成时间' },
    { key: 'download_note', label: '备注' },
  ]

  return (
    <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
      <div className="px-4 py-2 bg-gray-50 border-b border-gray-100">
        <h4 className="text-xs font-semibold text-gray-600">任务报告</h4>
      </div>
      <div className="p-4">
        <table className="w-full text-sm">
          <tbody>
            {fields
              .filter((f) => report[f.key] !== undefined && report[f.key] !== '')
              .map((f) => (
                <tr key={f.key} className="border-b border-gray-50 last:border-0">
                  <td className="py-1.5 pr-3 text-xs text-gray-500 w-24">{f.label}</td>
                  <td className="py-1.5 text-xs text-gray-800 break-all">
                    {f.render ? f.render(report[f.key] as any) : String(report[f.key])}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
