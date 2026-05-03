import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean; error: string }> {
  constructor(props: { children: React.ReactNode }) {
    super(props)
    this.state = { hasError: false, error: '' }
  }
  static getDerivedStateFromError(e: Error) {
    return { hasError: true, error: e.message }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 40, textAlign: 'center', fontFamily: 'sans-serif' }}>
          <h2 style={{ color: '#c00' }}>页面渲染出错</h2>
          <pre style={{ fontSize: 13, color: '#666', marginTop: 12 }}>{this.state.error}</pre>
          <button
            onClick={() => window.location.reload()}
            style={{ marginTop: 16, padding: '6px 20px', cursor: 'pointer' }}
          >
            刷新页面
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
)
