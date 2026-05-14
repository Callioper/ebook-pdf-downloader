# Startup Detection Timeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 30-second timeout to the startup "正在检测系统状态..." screen so the app enters the main interface even if backend checks hang.

**Architecture:** The startup screen is rendered by `Layout.tsx` when `appReady` is `false`. The `init()` function runs 4 parallel tasks (theme fetch, system status, update check, Stacks auto-login) and only sets `appReady = true` after `Promise.allSettled` resolves all of them. We add a 30-second timeout that races against `Promise.allSettled` — whichever settles first triggers `setAppReady(true)`. Background tasks continue running; they just don't block the UI.

**Tech Stack:** React 18, TypeScript, Tailwind CSS

---

### Task 1: Add 30-second timeout to startup `init()`

**Files:**
- Modify: `frontend/src/components/Layout.tsx:120-187`

- [ ] **Step 1: Write the failing test** (manual — no frontend test framework)

Since this project has no frontend test framework (no Jest/Vitest), verify the current behavior by confirming that the startup blocks on `Promise.allSettled` with no timeout. Read lines 120-187 and verify there is no timeout mechanism.

- [ ] **Step 2: Add timeout to `init()`**

Replace the existing `init()` function in `frontend/src/components/Layout.tsx` (lines 120-187):

```typescript
  useEffect(() => {
    const init = async () => {
      const tasks = [
        // 1. Theme
        fetch('/api/v1/config')
          .then(r => r.json())
          .then(cfg => {
            const theme = cfg.theme || 'auto'
            localStorage.setItem('theme', theme)
            const cleanup = applyTheme(theme)
            return cleanup
          })
          .catch(() => {}),

        // 2. System status
        fetch('/api/v1/system-status')
          .then(r => r.json())
          .then(data => { setSysStatus(data); sysCheckedRef.current = true })
          .catch(() => setSysStatus(null))
          .finally(() => setSysChecking(false)),

        // 3. Update check
        fetch(`${API_BASE}/check-update`)
          .then(r => r.json())
          .then((data: UpdateInfo) => {
            cachedUpdate = data
            cachedVersion = data.current || '...'
            setVersion(cachedVersion)
            if (data.has_update) {
              const lastSeen = localStorage.getItem('last_update_seen')
              if (lastSeen !== data.latest) {
                setUpdateInfo(data)
                setDismissed(false)
              }
              setCheckResult(`新版本 v${data.latest} 可用`)
            } else {
              setUpdateInfo(null)
              setCheckResult(`已是最新 v${cachedVersion}`)
            }
          })
          .catch(() => { setCheckResult('检查失败') }),

        // 4. Stacks auto-login
        fetch('/api/v1/config')
          .then(r => r.json())
          .then(cfg => {
            const url = cfg.stacks_base_url || 'http://localhost:7788'
            const uname = cfg.stacks_username || ''
            const passwd = cfg.stacks_password || ''
            if (!uname || !passwd) return
            return fetch('/api/v1/check-stacks', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ url, username: uname, password: passwd }),
            })
          })
          .then(r => r?.json())
          .then(d => {
            if (d?.ok) console.log('[auto-login] Stacks login OK')
          })
          .catch(() => {}),
      ]

      const timeout = new Promise<void>(resolve => {
        setTimeout(() => resolve(), 30000)
      })

      await Promise.race([Promise.allSettled(tasks), timeout])
      setAppReady(true)
    }
    init()
  }, [])
```

The only change: add a `timeout` promise that resolves after 30 seconds, and use `Promise.race([Promise.allSettled(tasks), timeout])` instead of bare `Promise.allSettled(tasks)`. When the timeout fires first, `setAppReady(true)` still runs, allowing the UI to render. Background tasks continue in the background.

- [ ] **Step 3: Verify TypeScript compiles**

Run:
```bash
cd frontend
npx tsc --noEmit
```
Expected: No type errors.

- [ ] **Step 4: Verify build succeeds**

Run:
```bash
cd frontend
npm run build
```
Expected: `tsc` and `vite build` succeed without errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout.tsx
git commit -m "feat: add 30s timeout to startup detection screen"
```
