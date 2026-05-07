import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-gray-50">
          <div className="bg-white rounded-lg border border-gray-200 p-8 max-w-md text-center">
            <h2 className="text-lg font-semibold text-gray-800 mb-2">页面加载异常</h2>
            <p className="text-sm text-gray-500 mb-4">
              {this.state.error?.message || "未知错误"}
            </p>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null })
                window.location.reload()
              }}
              className="px-4 py-2 text-sm rounded bg-blue-600 text-white hover:bg-blue-700"
            >
              重新加载
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}
