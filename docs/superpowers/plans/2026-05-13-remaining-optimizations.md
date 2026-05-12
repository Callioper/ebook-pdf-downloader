# ConfigSettings Split + PyInstaller Cleanup + Minor Optimizations

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the 2360-line `ConfigSettings.tsx` into 4 focused sub-components, clean up PyInstaller spec, fix module-level logging init, and remove redundant urllib3 import.

**Architecture:** ConfigSettings becomes a thin orchestrator that delegates to: `DatabaseSection`, `DownloadSourcesSection`, `OCRNetworkSection`, and `AIVisionSection`. Each handles its own form updates via the shared `updateForm` callback. PyInstaller spec adds `__pycache__` exclusions and replaces hardcoded certifi path with computed one.

**Tech Stack:** React 18, TypeScript, Tailwind CSS, PyInstaller

---

## File Structure

| File | Role |
|---|---|
| `frontend/src/components/ConfigSettings.tsx` | Shrinks to ~500 lines — imports sub-sections |
| `frontend/src/components/settings/DatabaseSection.tsx` | NEW — database paths, self-check |
| `frontend/src/components/settings/DownloadSourcesSection.tsx` | NEW — ZLib, Stacks, Flare, Proxy, sources |
| `frontend/src/components/settings/OCRNetworkSection.tsx` | NEW — OCR engines, MinerU, PaddleOCR, LLM, Tesseract, AI Vision |
| `frontend/src/components/settings/ThemeSection.tsx` | NEW — theme selector (already small) |
| `backend/book-downloader.spec` | Cleanup — excludes __pycache__, fixes certifi path |
| `backend/main.py` | Move `_setup_logging()` into `main()` |
| `backend/api/search.py` | Remove module-level `urllib3` import |

---

### Task 1: Move `_setup_logging()` into `main()`

**Files:**
- Modify: `D:\opencode\book-downloader\backend\main.py`

**Impact:** MEDIUM — logging file handler creation no longer blocks module import (only runs on actual startup).

- [ ] **Step 1: Read the file**

Read `D:\opencode\book-downloader\backend\main.py`. Find `_setup_logging()` call at module level (line 63).

- [ ] **Step 2: Move the call**

Delete the module-level call `_setup_logging()` at line 63.

Add the call as the first line inside `main()` function:

```python
def main():
    _setup_logging()
    init_config()
    ...
```

- [ ] **Step 3: Verify syntax**

```bash
python -m py_compile backend\main.py
```

- [ ] **Step 4: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/main.py
git commit -m "perf: move _setup_logging() into main() to avoid module-level file I/O"
```

---

### Task 2: Clean up PyInstaller spec

**Files:**
- Modify: `D:\opencode\book-downloader\backend\book-downloader.spec`

**Impact:** MEDIUM — smaller exe (no __pycache__ in bundle), portable certifi path.

- [ ] **Step 1: Read the file**

Read `D:\opencode\book-downloader\backend\book-downloader.spec`. Find the `datas` list (around lines 15-30).

- [ ] **Step 2: Replace certifi path**

Find the hardcoded certifi path (line 28):
```python
(r"C:\Users\Administrator\AppData\Local\Packages\...", "certifi"),
```

Replace with a computed path:

```python
import certifi
# certifi cacert.pem — resolved at build time
_cert_path = os.path.dirname(certifi.__file__)
_cacert = os.path.join(_cert_path, "cacert.pem")
```

Then in the `datas` list use `(_cacert, "certifi")` instead of the hardcoded path.

- [ ] **Step 3: Add __pycache__ exclusions**

In the `exe = EXE(...)` call, verify there's an `excludes` list. If not, add:

```python
excludes=['__pycache__', '*.pyc', '*.pyo'],
```

- [ ] **Step 4: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/book-downloader.spec
git commit -m "build: fix portable certifi path in PyInstaller spec, exclude __pycache__"
```

---

### Task 3: Remove module-level urllib3 import

**Files:**
- Modify: `D:\opencode\book-downloader\backend\api\search.py:25-26`

**Impact:** MEDIUM — unnecessary dependency load at API module import.

- [ ] **Step 1: Read the file**

Read `D:\opencode\book-downloader\backend\api\search.py`. Find lines 25-26:

```python
import urllib3
warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)
```

- [ ] **Step 2: Replace with string-based filter**

Replace with:

```python
import warnings
warnings.filterwarnings("ignore", message=".*InsecureRequestWarning.*")
```

(No need to import urllib3 — `warnings.filterwarnings` supports message regex matching.)

- [ ] **Step 3: Verify syntax**

```bash
python -m py_compile backend\api\search.py
```

- [ ] **Step 4: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/api/search.py
git commit -m "perf: remove module-level urllib3 import, use string-based warning filter"
```

---

### Task 4: Extract sub-components from ConfigSettings.tsx

**Files:**
- Create: `D:\opencode\book-downloader\frontend\src\components\settings\DatabaseSection.tsx`
- Create: `D:\opencode\book-downloader\frontend\src\components\settings\DownloadSourcesSection.tsx`
- Create: `D:\opencode\book-downloader\frontend\src\components\settings\OCRNetworkSection.tsx`
- Modify: `D:\opencode\book-downloader\frontend\src\components\ConfigSettings.tsx`

**Background:** ConfigSettings at 2360 lines is too large — every state change re-renders the entire tree. Extracting sub-components with `React.memo` cuts re-render scope.

- [ ] **Step 1: Create `settings/` directory**

```bash
mkdir frontend\src\components\settings
```

- [ ] **Step 2: Define shared props interface**

Create `frontend/src/components/settings/types.ts`:

```typescript
import { AppConfig } from '../../../types'

export interface SectionProps {
  form: AppConfig
  updateForm: (data: Partial<AppConfig>) => void
  mountedRef: React.MutableRefObject<boolean>
}
```

- [ ] **Step 3: Create DatabaseSection.tsx**

Extract lines from ConfigSettings.tsx that handle:
- SQLite DB path input + detect button
- Download dir + finished dir inputs

This section has its own state (`dbStatus`, `dbDetecting`, etc.) — keep those local to the component.

The component signature:
```tsx
export default function DatabaseSection({ form, updateForm, mountedRef }: SectionProps) { ... }
```

- [ ] **Step 4: Create DownloadSourcesSection.tsx**

Extract lines handling:
- Z-Library (email, password, check button)
- Stacks (URL, API key, username, password, login button)
- FlareSolverr (port, install/start/stop)
- HTTP Proxy
- Source connectivity check

- [ ] **Step 5: Create OCRNetworkSection.tsx**

Extract lines handling:
- OCR engine selection (Tesseract/PaddleOCR/MinerU/PaddleOCR-VL-1.5/LLM OCR)
- MinerU config (token, detect button)
- PaddleOCR-VL-1.5 config (token, mode selector, detect button)
- LLM OCR config (endpoint, model)
- Tesseract config (language, jobs, timeout, DPI)
- OCR confirm checkbox
- Theme selector

- [ ] **Step 6: Rewrite ConfigSettings.tsx**

Replace with:
```tsx
import DatabaseSection from './settings/DatabaseSection'
import DownloadSourcesSection from './settings/DownloadSourcesSection'
import OCRNetworkSection from './settings/OCRNetworkSection'
import { SectionProps } from './settings/types'
import React from 'react'

export default function ConfigSettings() {
  const mountedRef = useRef(true)
  const [form, updateFormState] = useState<AppConfig>(DEFAULT_CONFIG)
  
  const updateForm = useCallback((data: Partial<AppConfig>) => {
    updateFormState(prev => {
      const next = { ...prev, ...data }
      updateConfig(next)  // persist to backend
      return next
    })
  }, [])

  return (
    <div className="space-y-4">
      <DatabaseSection form={form} updateForm={updateForm} mountedRef={mountedRef} />
      <DownloadSourcesSection form={form} updateForm={updateForm} mountedRef={mountedRef} />
      <OCRNetworkSection form={form} updateForm={updateForm} mountedRef={mountedRef} />
    </div>
  )
}
```

- [ ] **Step 7: Build frontend**

```bash
cd D:\opencode\book-downloader\frontend
npm run build
```

Expected: tsc + vite both pass without errors.

- [ ] **Step 8: Commit**

```bash
cd D:\opencode\book-downloader
git add frontend/src/components/settings/ frontend/src/components/ConfigSettings.tsx
git commit -m "refactor: split ConfigSettings into DatabaseSection, DownloadSourcesSection, OCRNetworkSection"
```

---

### Self-Review

**1. Spec coverage:**
- ConfigSettings split → Task 4
- PyInstaller cleanup → Task 2
- Logging fix → Task 1
- urllib3 fix → Task 3

**2. Placeholder scan:** No TBD/TODO. Config extraction described in detail.

**3. Type consistency:**
- `SectionProps` defined in `types.ts`, imported by all sub-components
- `updateForm: (data: Partial<AppConfig>) => void` — same type as existing `updateForm` in ConfigSettings
- `mountedRef: React.MutableRefObject<boolean>` — passed through from parent
