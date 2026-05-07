import { BrowserRouter, Routes, Route } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'
import SearchPage from './pages/SearchPage'
import ResultsPage from './pages/ResultsPage'
import TaskListPage from './pages/TaskListPage'
import TaskDetailPage from './pages/TaskDetailPage'
import ConfigSettings from './components/ConfigSettings'

function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<SearchPage />} />
            <Route path="results" element={<ResultsPage />} />
            <Route path="tasks" element={<TaskListPage />} />
            <Route path="tasks/:taskId" element={<TaskDetailPage />} />
            <Route path="config" element={<ConfigSettings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ErrorBoundary>
  )
}

export default App
