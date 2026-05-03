import { STATUS_LABELS, STATUS_COLORS } from '../constants'

export function statusBadge(status: string) {
  const label = STATUS_LABELS[status] || status
  const colorClass = STATUS_COLORS[status] || 'bg-gray-100 text-gray-600'

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colorClass}`}>
      {label}
    </span>
  )
}
