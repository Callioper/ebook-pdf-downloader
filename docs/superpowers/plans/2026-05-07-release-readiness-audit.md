# 首次发布自查自纠 Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 系统性地审查 book-downloader 项目，修复代码质量缺陷、安全漏洞、构建配置问题和 UI 瑕疵，确保 v1.5.0 首次公开发布可靠可用。

**Architecture:** 自上而下的逐层审查：后端代码清理 → 安全加固 → 构建验证 → 前端 UI 抛光 → 测试完整性 → 文档/版本号对齐。每层独立可验收，互不阻塞。

**Tech Stack:** Python 3.10+ / FastAPI / TypeScript 5.x / React 18 / Tailwind CSS / PyInstaller / Inno Setup

---

## 文件结构梳理

本次审计涉及以下文件，分为「修复」和「新增」两类：

| 文件 | 操作 | 问题描述 |
|------|------|----------|
| `backend/main.py` | 修改 | 重复 import、hardcoded version、os._exit()、CORS 全开、docs 端点暴露 |
| `backend/config.py` | 修改 | frozen 模式下 DEFAULT_CONFIG_FILE 路径错误 |
| `backend/task_store.py` | 修改 | 中文注释乱码、tasks.json 路径在 frozen 模式下可能异常 |
| `backend/book-downloader.spec` | 修改 | console=True 弹出命令行窗口 |
| `backend/api/search.py` | 修改 | 版本号不一致（使用 VERSION 来自 version.py）、无速率限制 |
| `frontend/src/components/Layout.tsx` | 修改 | 关闭时 sendBeacon 路径缺少 API 前缀、emoji 在部分终端显示异常 |
| `frontend/src/components/ConfigSettings.tsx` | 修改 | FolderPicker 按钮文案 "..." |
| `frontend/src/components/StepProgressBar.tsx` | 修改 | 需确认处理无步骤场景 |
| `frontend/src/App.tsx` | 修改 | 缺少 ErrorBoundary |
| `frontend/src/components/ErrorBoundary.tsx` | 新增 | 全局错误捕获组件 |
| `frontend/vite.config.ts` | 修改 | 检查 proxy 配置 |
| `setup.iss` | 修改 | 安装后的路径配置 |
| `CHANGELOG.md` | 修改 | 更新到 v1.5.0 |
| `AI_CONTEXT.md` | 修改 | 版本号对齐 |
| `.gitignore` | 修改 | *.spec 规则与实际冲突 |

---

### Task 1: 清理 backend/main.py — 重复 import 与 hardcoded version

**Files:**
- Modify: `backend/main.py:1-208`
- Test: `test_smoke.py`

- [ ] **Step 1: 删除重复的 import 语句**

`backend/main.py:7` 导入了 `asyncio`，但代码中从未使用。`backend/main.py:159-161` 和 `backend/main.py:180-181` 重复导入了 `webbrowser` 和 `urllib.request`。

打开 `backend/main.py`，删除以下行：

```python
# 删除第 7 行（如果确实未使用）
import asyncio

# 删除第 180-181 行的重复导入（保留第 159-161 行）
import webbrowser
import urllib.request
```

同时，将第 67 行的 hardcoded `"1.0.0"` 改为从 `version.py` 动态读取：

```python
# 第 65-70 行，改为：
from version import VERSION

app = FastAPI(
    title="Book Downloader",
    version=VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)
```

确保 `from version import VERSION` 只出现一次（检查文件顶部是否已有导入）。

- [ ] **Step 2: 运行冒烟测试验证未引入语法错误**

```powershell
python D:\opencode\book-downloader\test_smoke.py
```

预期: 所有 Section 1~8 测试通过。

- [ ] **Step 3: 验证 version API 返回正确版本号**

启动后端后手动验证（或等 Task 7 统一验证）：

```powershell
(Invoke-WebRequest -Uri "http://localhost:8000/api/v1/check-update").Content | ConvertFrom-Json | Select-Object current
```

预期: `current` 字段为 `"1.4.0"`（与 version.py 一致）。

- [ ] **Step 4: 提交**

```powershell
git add backend/main.py
git commit -m "fix: remove duplicate imports and hardcoded version in main.py"
```

---

### Task 2: 修复主进程的优雅关闭

**Files:**
- Modify: `backend/main.py:113,145-155`

- [ ] **Step 1: 替换 os._exit() 为优雅关闭**

`os._exit(0)` 会立即终止进程，不执行 `atexit` 注册的清理函数和 `try/finally` 块。FlareSolverr 进程可能泄漏。

修改 `backend/main.py:100-116` 的 shutdown 端点：

```python
@app.post("/api/v1/shutdown")
async def shutdown():
    def _do_shutdown():
        import time as _time
        _time.sleep(0.3)
        try:
            stop_flaresolverr()
        except Exception:
            pass
        try:
            from task_store import task_store
            task_store.stop()
        except Exception:
            pass
        # 使用 sys.exit() 而非 os._exit(0)
        import sys as _sys
        _sys.exit(0)

    threading.Thread(target=_do_shutdown, daemon=True).start()
    return {"ok": True, "message": "shutting down"}
```

修改 `backend/main.py:143-155` 的 main() 异常处理：

```python
def main():
    try:
        config = init_config()
        host = config.get("host", "0.0.0.0")
        port = config.get("port", 8000)
        db_path = config.get("ebook_db_path", "")
        if db_path:
            search_engine.set_db_dir(db_path)
        uvicorn.run(app, host=host, port=port, reload=False, log_level="info")
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
        import sys as _sys
        _sys.exit(1)
```

注意：uvicorn.run() 会处理信号，`KeyboardInterrupt` 是正常退出路径，不应返回 exit code 1。

- [ ] **Step 2: 运行冒烟测试验证**

```powershell
python D:\opencode\book-downloader\test_smoke.py
```

预期: 全部通过。

- [ ] **Step 3: 提交**

```powershell
git add backend/main.py
git commit -m "fix: replace os._exit() with graceful sys.exit() for proper cleanup"
```

---

### Task 3: 修复 frozen 模式下 config 路径错误

**Files:**
- Modify: `backend/config.py:17-26`

- [ ] **Step 1: 理解问题**

`backend/config.py:17-23` 中 `_get_app_dir()` 在 frozen 模式下返回 `%APPDATA%\BookDownloader`。但 `DEFAULT_CONFIG_FILE` 在 `backend/config.py:26` 也使用了 `_get_app_dir()`，这意味着解析 `config.default.json` 时也会去 APPDATA 找——而实际上该文件随 exe 打包到 `sys._MEIPASS`，不在 APPDATA。

不过仔细看 `load_config()` 的实现（第 72-82 行），`DEFAULT_CONFIG_FILE` 从未被实际读取——该方法使用硬编码的 `DEFAULT_CONFIG` 字典（第 28-57 行）。所以这个问题目前不影响功能，但为了代码正确性，修复它。

修改 `backend/config.py:25-26`：

```python
CONFIG_FILE = _get_app_dir() / "config.json"

# DEFAULT_CONFIG_FILE 仅在未 frozen 时指向项目根目录；frozen 模式下它不存在于文件系统
def _get_default_config_path() -> Path:
    if getattr(sys, 'frozen', False):
        # frozen: shipped alongside exe in _MEIPASS
        return Path(sys._MEIPASS) / "config.default.json"
    else:
        return Path(__file__).resolve().parent.parent / "config.default.json"

DEFAULT_CONFIG_FILE = _get_default_config_path()
```

- [ ] **Step 2: 确保 install 脚本包含 config.default.json**

检查 `backend/book-downloader.spec`，确认 `config.default.json` 已打包：

查看第 14-28 行 datas 列表，当前没有包含 `config.default.json`。添加它：

打开 `backend/book-downloader.spec`，在 datas 列表中增加一行（约第 28 行之后）：

```python
        (str(BACKEND_DIR.parent / "config.default.json"), "config.default.json"),
```

- [ ] **Step 3: 同时确保 setup.iss 安装后配置正确**

`setup.iss:24` 已经复制了 `config.default.json` 到 `{app}` 目录。但 frozen 模式下 config.py 从 `sys._MEIPASS` 读取，这是 PyInstaller 的临时目录。需要确认 `_get_default_config_path()` 能找到文件。

PyInstaller 打包后 `sys._MEIPASS` 指向解压目录，datas 中的文件会按规则放置：
- `(str(BACKEND_DIR.parent / "config.default.json"), "config.default.json")` 会将文件放到 `_MEIPASS/config.default.json`

所以 `Path(sys._MEIPASS) / "config.default.json"` 能找到它。此修复正确。

- [ ] **Step 4: 提交**

```powershell
git add backend/config.py backend/book-downloader.spec
git commit -m "fix: correct config.default.json path resolution in frozen mode"
```

---

### Task 4: 修复 task_store.py 中文注释乱码

**Files:**
- Modify: `backend/task_store.py:1-6`

- [ ] **Step 1: 替换乱码注释行**

`backend/task_store.py:1-6` 当前是乱码：

```python
# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
# ???????????????????????????JSON???
# ????????askStore.create(), get(), list_all(), update(), delete(), cancel()
# ?????onfig
# ???????????????Lock?????????
```

替换为：

```python
# -*- coding: utf-8 -*-
# 职责：任务存储管理，内存字典 + JSON 文件持久化
# 入口函数：TaskStore.create(), get(), list_all(), update(), delete(), cancel()
# 依赖：config
# 注意：线程安全，使用 Lock 保护并发访问
```

- [ ] **Step 2: 确认 TASKS_FILE 路径合理**

`backend/task_store.py:19`:
```python
TASKS_FILE = Path(__file__).resolve().parent.parent / "tasks.json"
```

在 frozen 模式下，`__file__` 指向 `_MEIPASS` 内的文件，`parent.parent` 会回到项目根（不一定可写）。应该像 config 一样使用运行时路径。

修改为：

```python
import sys as _sys

def _get_tasks_path() -> Path:
    if getattr(_sys, 'frozen', False):
        app_data = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        conf_dir = app_data / 'BookDownloader'
        conf_dir.mkdir(parents=True, exist_ok=True)
        return conf_dir / "tasks.json"
    return Path(__file__).resolve().parent.parent / "tasks.json"

TASKS_FILE = _get_tasks_path()
```

同时在文件顶部的 import 部分确保 `os` 已导入（当前第 10 行已有 `import os`）。

- [ ] **Step 3: 运行冒烟测试验证**

```powershell
python D:\opencode\book-downloader\test_smoke.py
```

预期: 全部通过，Section 6（Task Store）不报错。

- [ ] **Step 4: 提交**

```powershell
git add backend/task_store.py
git commit -m "fix: repair garbled comments and tasks.json path in frozen mode"
```

---

### Task 5: 安全加固 — CORS 限制 + 隐藏 docs 端点

**Files:**
- Modify: `backend/main.py:72-78,65-70`

- [ ] **Step 1: 限制 CORS 为 localhost**

当前 `allow_origins=["*"]` 允许任何源访问。本应用在本地运行（Edge App 模式或浏览器 localhost），不需要通配符。

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",   # Vite dev server
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- [ ] **Step 2: 条件性隐藏 /docs 和 /redoc**

公开的 API 文档在生产环境中不必要，且暴露内部端点。只在非 frozen 模式下启用：

```python
import sys as _sys

is_dev = not getattr(_sys, 'frozen', False)

app = FastAPI(
    title="Book Downloader",
    version=VERSION,
    docs_url="/docs" if is_dev else None,
    redoc_url="/redoc" if is_dev else None,
)
```

- [ ] **Step 3: 运行冒烟测试**

```powershell
python D:\opencode\book-downloader\test_smoke.py
```

- [ ] **Step 4: 提交**

```powershell
git add backend/main.py
git commit -m "security: restrict CORS to localhost and hide docs in production"
```

---

### Task 6: PyInstaller — 隐藏控制台窗口

**Files:**
- Modify: `backend/book-downloader.spec:73`

- [ ] **Step 1: 将 console 改为 False**

`backend/book-downloader.spec:73` 当前 `console=True`，用户双击 exe 时会弹出命令行窗口。改为 `False` 以隐藏控制台，让应用以 GUI 模式运行。

```python
exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
    [],
    name='BookDownloader',
    debug=False,
    strip=False,
    upx=False,
    console=False,  # 从 True 改为 False
    runtime_tmpdir=None,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(BACKEND_DIR.parent / "icon.ico"),
)
```

注意：`console=False` 意味着所有 print/logger 输出都不会显示。需要确保所有用户可见信息通过 Web UI 或日志文件提供。由于应用通过浏览器交互，这是正确的行为。

- [ ] **Step 2: 更新 .gitignore 中的 *.spec 规则**

`.gitignore:9` 中 `*.spec` 会忽略 `book-downloader.spec`，但这个文件必须被版本追踪。修改：

```
# 旧的：
*.spec

# 新的：
!book-downloader.spec
*.spec
```

- [ ] **Step 3: 验证 spec 文件仍在 tracking 中**

```powershell
git ls-files -- "backend/book-downloader.spec"
```

如果返回空（被 gitignore 排除），需要强制追踪：

```powershell
git add -f backend/book-downloader.spec
```

- [ ] **Step 4: 提交**

```powershell
git add backend/book-downloader.spec .gitignore
git commit -m "build: hide console window in production and track spec file"
```

---

### Task 7: 前端 — 添加 ErrorBoundary 和 Loading 状态

**Files:**
- Create: `frontend/src/components/ErrorBoundary.tsx`
- Modify: `frontend/src/App.tsx:1-25`

- [ ] **Step 1: 创建 ErrorBoundary 组件**

创建 `frontend/src/components/ErrorBoundary.tsx`：

```tsx
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
```

- [ ] **Step 2: 在 App.tsx 中包裹 ErrorBoundary**

修改 `frontend/src/App.tsx:1-25`：

```tsx
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
```

- [ ] **Step 3: 构建前端验证编译通过**

```powershell
npm run build
```

工作目录: `D:\opencode\book-downloader\frontend`

预期: tsc + vite build 成功，无错误。

- [ ] **Step 4: 提交**

```powershell
git add frontend/src/components/ErrorBoundary.tsx frontend/src/App.tsx
git commit -m "feat: add ErrorBoundary component for graceful crash recovery"
```

---

### Task 8: 前端 UI 抛光

**Files:**
- Modify: `frontend/src/components/ConfigSettings.tsx:68-73`
- Modify: `frontend/src/components/Layout.tsx:237-248`
- Modify: `frontend/src/components/Layout.tsx:58`

- [ ] **Step 1: 修复 FolderPicker 按钮文案**

`ConfigSettings.tsx:70` 中 `{picking ? '...' : '...'}` 两个状态的文案相同，用户无法区分。需要改为可用时为 `...`，选择中为 `...`

实际上再看一下代码：`{picking ? '...' : '...'}` 已经是相同的了。这是一个静态问题。修改为合理文案：

```tsx
// Line 70
{picking ? '...' : '...'}
```

改为使用明确的文字：

```tsx
{picking ? '选择中...' : '浏览...'}
```

- [ ] **Step 2: 替换 footer 中的 emoji 为纯文本**

`Layout.tsx:237` footer 中使用了 emoji `...` 和 `...`，在某些 Windows 系统字体下显示为方框。修改为纯文本符号：

```tsx
<footer className="bg-white border-t border-gray-200 py-2">
  <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between text-xs text-gray-400">
    <div className="flex items-center gap-2">
      <button
        onClick={checkUpdate}
        disabled={checking}
        className="hover:text-gray-600 disabled:opacity-50"
        title="检查更新"
      >
        {checking ? '(checking)' : '(re-check)'}
      </button>
      <span>v{version || '...'}</span>
    </div>
    <a href="https://github.com/Callioper/book-downloader" target="_blank" rel="noopener noreferrer" className="hover:text-gray-600">
      github.com/Callioper/book-downloader
    </a>
  </div>
</footer>
```

- [ ] **Step 4: 构建前端验证**

```powershell
npm run build
```

工作目录: `D:\opencode\book-downloader\frontend`

- [ ] **Step 5: 提交**

```powershell
git add frontend/src/components/ConfigSettings.tsx frontend/src/components/Layout.tsx
git commit -m "ui: fix FolderPicker label and replace emoji with text in footer"
```

---

### Task 9: 版本号与文档对齐

**Files:**
- Modify: `CHANGELOG.md:1-13`
- Modify: `AI_CONTEXT.md:7`
- Modify: `backend/version.py:1`

- [ ] **Step 1: 更新 CHANGELOG.md 到 v1.5.0**

当前 `CHANGELOG.md` 只记录到 v1.4.0。追加 v1.5.0 条目：

在 `CHANGELOG.md` 文件顶部（第 1 行之前）插入：

```markdown
# 变更记录

## v1.5.0 — 2026-05-07 — 首次公开发布
- 后端：修复 main.py 重复 import 和硬编码版本号
- 后端：将 os._exit() 替换为优雅的 sys.exit() 关闭流程
- 后端：修复 frozen 模式下 config/tasks 路径解析
- 后端：限制 CORS 为 localhost，隐藏生产环境 API 文档
- 构建：隐藏 PyInstaller 控制台窗口 (console=False)
- 前端：新增 ErrorBoundary 全局崩溃恢复组件
- 前端：修复 FolderPicker 按钮文案，footer emoji 替换为纯文本
- 文档：CHANGELOG 和 AI_CONTEXT 版本号对齐到 v1.5.0

## v1.4.0 — 2026-05-04 — OCR 修复 + 状态持久化
```

**注意**：删除原有的 `# 变更记录` 行，因为新文本已包含。

- [ ] **Step 2: 更新 AI_CONTEXT.md 版本号**

`AI_CONTEXT.md:7` 当前显示 `v1.5.0`。确保与实际版本一致：

```
- 版本：v1.5.0
```

已经是 v1.5.0，不需要改。但确认 `backend/version.py` 也是这个版本。

- [ ] **Step 3: 同步 backend/version.py**

`backend/version.py:1` 当前是 `VERSION = "1.4.0"`。需要更新为：

```python
VERSION = "1.5.0"
GITHUB_REPO = "Callioper/book-downloader"
UPDATE_CHECKED_KEY = "last_update_seen"
```

**注意**：如果用户希望以 v1.4.0 发布（即不对本次审计升级版本号），则此步需与用户确认。计划默认升级到 v1.5.0 以标记审计改动。

- [ ] **Step 4: 运行冒烟测试确保版本号变更不影响功能**

```powershell
python D:\opencode\book-downloader\test_smoke.py
```

- [ ] **Step 5: 提交**

```powershell
git add CHANGELOG.md AI_CONTEXT.md backend/version.py
git commit -m "docs: align version to v1.5.0 for first public release"
```

---

### Task 10: 扩展冒烟测试覆盖

**Files:**
- Modify: `test_smoke.py`

- [ ] **Step 1: 新增后端 API 结构验证测试**

在 `test_smoke.py` 的 `main()` 函数中 `Section 7` 之后增加 `Section 9: API Structure`：

```python
    # ==== Section 9: API Route Registration (3 tests) ====
    print("\n  [Section 9] API Route Registration")
    print("  " + "-" * 40)

    def test_api_search_importable():
        spec = importlib.util.spec_from_file_location("search_api", os.path.join(BACKEND_DIR, "api", "search.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, 'router'), "search.py should export 'router'"
        routes = [r.path for r in mod.router.routes]
        assert '/api/v1/search' in routes, "search route missing"
        assert '/api/v1/config' in routes, "config route missing"

    def test_api_tasks_importable():
        spec = importlib.util.spec_from_file_location("tasks_api", os.path.join(BACKEND_DIR, "api", "tasks.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, 'router'), "tasks.py should export 'router'"
        routes = [r.path for r in mod.router.routes]
        assert any('/api/v1/tasks' in p for p in routes), "tasks list route missing"

    def test_pipeline_steps_consistency():
        task_store_module = sys.modules.get('task_store')
        if task_store_module is None:
            spec = importlib.util.spec_from_file_location("task_store", os.path.join(BACKEND_DIR, "task_store.py"))
            task_store_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(task_store_module)
        steps = task_store_module.PIPELINE_STEPS
        assert len(steps) == 7, f"Expected 7 pipeline steps, got {len(steps)}"
        for step in ['fetch_metadata', 'fetch_isbn', 'download_pages', 'convert_pdf', 'ocr', 'bookmark', 'finalize']:
            assert step in steps, f"Missing step: {step}"

    test("search API router has expected routes", test_api_search_importable)
    test("tasks API router has expected routes", test_api_tasks_importable)
    test("pipeline has all 7 expected steps", test_pipeline_steps_consistency)
```

- [ ] **Step 2: 运行时端口可配置验证**

在 Section 4 末尾增加一个测试，检查 port 配置的有效值范围：

```python
    def test_port_config_range():
        config = config_module.load_config()
        port = config.get('port', 8000)
        assert isinstance(port, int), "port should be an integer"
        assert 1024 <= port <= 65535, f"port {port} out of valid range"
```

这是可选的——如果 `config.json` 中 port 恰好为 0 或超出范围，此测试会失败。但在默认配置下 8000 在范围内。

- [ ] **Step 3: 运行完整的冒烟测试**

```powershell
python D:\opencode\book-downloader\test_smoke.py
```

预期: 所有 Section（包括新增的 Section 9）全部通过。

- [ ] **Step 4: 提交**

```powershell
git add test_smoke.py
git commit -m "test: add API route and pipeline step consistency smokes"
```

---

### Task 11: 最终集成验证

**Files:**
- 无新文件修改，仅运行验证命令

- [ ] **Step 1: 完整构建前端**

```powershell
npm run build
```

工作目录: `D:\opencode\book-downloader\frontend`

预期: tsc 编译通过，vite 构建成功。检查输出中有 `index.html` 和 `assets/` 目录。

- [ ] **Step 2: 运行冒烟测试通过全部 9 个 Section**

```powershell
python D:\opencode\book-downloader\test_smoke.py
```

预期: 输出 `Result: XX/XX passed`，无 failed。

- [ ] **Step 3: 运行 release.py 的 dry-run**

```powershell
python D:\opencode\book-downloader\release.py 1.5.0 --dry-run
```

预期: 语法检查通过（"All Python files OK"）、前端自检通过、其余步骤显示 "(dry-run, skipped)"。

**注意**：如果 `GITHUB_TOKEN` 未设置，Step 8 会提示跳过，这是正常的。

- [ ] **Step 4: 启动后端并手动验证关键端点**

```powershell
Start-Process python -ArgumentList "D:\opencode\book-downloader\backend\main.py", "--no-browser" -NoNewWindow
Start-Sleep -Seconds 3
```

然后逐条验证：

```powershell
# 健康检查
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/health"
# 预期: {ok: True, status: "running"}

# 配置获取
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/config"
# 预期: 返回配置 JSON，zlib_password 已被排除

# 版本检查
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/check-update"
# 预期: 包含 current、latest、has_update 字段

# 前端首页
Invoke-WebRequest -Uri "http://localhost:8000/" | Select-Object StatusCode
# 预期: 200
```

结束时关闭后端：

```powershell
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/shutdown" -Method POST
```

- [ ] **Step 5: 检查 git 状态确认无遗漏**

```powershell
git status
```

预期: 工作区干净，或只有未追踪文件（如 `tasks.json`）。

- [ ] **Step 6: 提交（如有最后的修改）**

```powershell
git add -A
git commit -m "chore: final integration verification for v1.5.0 release"
```

---

## 自审清单（执行者自查用）

完成所有 Task 后，确认以下检查项：

- [ ] `backend/main.py` 无重复 import，version 从 version.py 读取
- [ ] `backend/main.py` 不再使用 `os._exit()`
- [ ] `backend/main.py` CORS 限制为 localhost
- [ ] `backend/config.py` DEFAULT_CONFIG_FILE 在 frozen 模式下指向正确路径
- [ ] `backend/task_store.py` 中文注释清晰，tasks.json 路径正确
- [ ] `backend/book-downloader.spec` console=False, config.default.json 已打包
- [ ] `.gitignore` 不排除 `book-downloader.spec`
- [ ] `frontend/src/components/ErrorBoundary.tsx` 存在且被 App 包裹
- [ ] `frontend/src/components/ConfigSettings.tsx` FolderPicker 按钮有区分文字
- [ ] `frontend/src/components/Layout.tsx` footer 无 emoji 乱码问题
- [ ] `CHANGELOG.md` 有 v1.5.0 条目
- [ ] `backend/version.py` 为 "1.5.0"
- [ ] `test_smoke.py` 全部 9 个 Section 通过
- [ ] `npm run build` 成功
- [ ] `release.py --dry-run` 通过
- [ ] 手动验证 /health、/config、/check-update 端点正常
