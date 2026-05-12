# AI Vision Settings Restructure — 4 Providers + Doubao/Zhipu Setup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify AI Vision settings to 4 providers (Ollama/LM Studio/Doubao/Zhipu), auto-fill endpoints, support model fetching + connectivity test, add Doubao Endpoint ID and Zhipu setup guides.

**Architecture:** Replace `AI_VISION_ENDPOINTS` with 4 providers. Ollama/LM Studio use local endpoints (auto-filled). Doubao requires Endpoint ID via ARK platform. Zhipu uses `glm-4.6v-flash` with API key. Remove DPI selector (hardcode 300). Reorder fields: Provider → Endpoint → Model → API Key → Test.

**Tech Stack:** React/TypeScript, Tailwind CSS, backend `fetch-models` and `check-ai-vision` endpoints (already exist)

---

## File Structure

| File | Role |
|---|---|
| `frontend/src/components/ConfigSettings.tsx:339-348` | Replace `AI_VISION_ENDPOINTS` with 4-provider constant |
| `frontend/src/components/ConfigSettings.tsx:2120-2305` | Rewrite bookmarks section — reorder, add Doubao/Zhipu fields |
| `frontend/src/types.ts` | Add `ai_vision_endpoint_id?: string` to AppConfig |
| `backend/config.py:87-89` | Change `ai_vision_dpi` default to 300 |

---

### Task 1: Backend — DPI default to 300

**Files:**
- Modify: `D:\opencode\book-downloader\backend\config.py:88`

- [ ] **Step 1: Change DPI default**

Read `D:\opencode\book-downloader\backend\config.py`. Find `"ai_vision_dpi": 150` (line 88). Change to `300`.

- [ ] **Step 2: Commit**

```bash
git add backend/config.py
git commit -m "chore: default ai_vision_dpi to 300"
```

---

### Task 2: Frontend — types.ts + provider constants

**Files:**
- Modify: `D:\opencode\book-downloader\frontend\src\types.ts`
- Modify: `D:\opencode\book-downloader\frontend\src\components\ConfigSettings.tsx:339-348`

- [ ] **Step 1: Add endpoint_id to AppConfig**

In `types.ts`, add after `ai_vision_api_key`:

```typescript
  ai_vision_endpoint_id?: string  // Doubao Endpoint ID (ep-...)
```

- [ ] **Step 2: Replace AI_VISION_ENDPOINTS**

Replace lines 339-348 in `ConfigSettings.tsx`:

```typescript
const AI_VISION_PROVIDERS = [
  { key: 'ollama',       label: 'Ollama',              endpoint: 'http://localhost:11434/v1',     desc: '本地 Ollama 服务' },
  { key: 'lmstudio',     label: 'LM Studio',           endpoint: 'http://127.0.0.1:1234/v1',     desc: '本地 LM Studio 服务' },
  { key: 'doubao',       label: 'Doubao (豆包)',        endpoint: 'https://ark.cn-beijing.volces.com/api/v3', desc: '火山引擎 ARK 平台' },
  { key: 'zhipu',        label: 'Zhipu (智谱)',        endpoint: 'https://open.bigmodel.cn/api/paas/v4', desc: '智谱 AI 开放平台' },
] as const
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/types.ts frontend/src/components/ConfigSettings.tsx
git commit -m "feat: 4-provider AI Vision (Ollama/LM Studio/Doubao/Zhipu) with auto-endpoint"
```

---

### Task 3: Rewrite bookmarks section UI

**Files:**
- Modify: `D:\opencode\book-downloader\frontend\src\components\ConfigSettings.tsx:2120-2305`

Replace the entire bookmarks section (lines 2120-2305) with the new layout.

- [ ] **Step 1: Read current section**

Read lines 2120-2305 to understand the full current layout.

- [ ] **Step 2: Replace the section**

Replace from `{/* ============ 书签 ============ */}` (line 2120) through the bookmark confirm checkbox end (line 2305) with:

```tsx
      {/* ============ 书签 ============ */}
      <SectionHeader
        title="书签"
        summary={form.ai_vision_enabled ? (form.ai_vision_model || '已启用') : 'AI Vision 未启用'}
        color="gray"
        expanded={expanded.bookmarks}
        onToggle={() => toggleSection('bookmarks')}
      />
      {expanded.bookmarks && (
        <div className="bg-gray-50 rounded-lg border border-gray-200 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <input type="checkbox" id="ai_vision_enabled"
              checked={form.ai_vision_enabled ?? true}
              onChange={(e) => updateForm({ ai_vision_enabled: e.target.checked })} className="rounded" />
            <label htmlFor="ai_vision_enabled" className="text-xs">启用 AI Vision 目录提取</label>
          </div>

          {/* 1. API 提供商 */}
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1.5">API 提供商</label>
            <div className="flex rounded border border-gray-300 overflow-hidden text-xs">
              {AI_VISION_PROVIDERS.map(({ key, label }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => {
                    const p = AI_VISION_PROVIDERS.find(p => p.key === key)!
                    updateForm({
                      ai_vision_provider: key,
                      ai_vision_endpoint: p.endpoint,
                      ai_vision_model: key === 'zhipu' ? 'glm-4.6v-flash' : form.ai_vision_model,
                    })
                  }}
                  className={`flex-1 py-1.5 text-center transition-colors ${
                    (form.ai_vision_provider || 'ollama') === key
                      ? 'bg-blue-500 text-white'
                      : 'bg-white text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {(() => {
              const p = AI_VISION_PROVIDERS.find(p => p.key === (form.ai_vision_provider || 'ollama'))
              return p ? <p className="text-[11px] text-gray-400 mt-1">{p.desc}</p> : null
            })()}
          </div>

          {/* 2. API 端点 */}
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">API 端点</label>
            <input type="text" value={form.ai_vision_endpoint || ''}
              onChange={(e) => updateForm({ ai_vision_endpoint: e.target.value })}
              placeholder="https://..."
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
          </div>

          {/* 3. Doubao Endpoint ID (conditional) */}
          {form.ai_vision_provider === 'doubao' && (
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">Endpoint ID</label>
              <input type="text" value={form.ai_vision_endpoint_id || ''}
                onChange={(e) => updateForm({ ai_vision_endpoint_id: e.target.value })}
                placeholder="ep-2025xxxx-xxxxx"
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
              <details className="mt-2">
                <summary className="text-[11px] text-blue-500 cursor-pointer">Doubao 配置教程</summary>
                <div className="mt-1 text-[11px] text-gray-500 space-y-1">
                  <p>Endpoint ID 是火山引擎 ARK 平台的推理接入点 ID，格式为 <code className="text-gray-600 bg-gray-100 px-1 rounded">ep-...</code>。</p>
                  <p><b>获取步骤：</b></p>
                  <ol className="list-decimal list-inside space-y-0.5">
                    <li>访问 <a href="https://console.volcengine.com/ark" target="_blank" className="text-blue-500">火山引擎 ARK 控制台</a></li>
                    <li>开通服务：在「模型推理」页面开通 ARK 服务</li>
                    <li>创建接入点：点击「创建接入点」，选择 Doubao 模型</li>
                    <li>复制生成的 Endpoint ID（<code className="text-gray-600 bg-gray-100 px-1 rounded">ep-2025xxxx-xxxxx</code>）</li>
                  </ol>
                  <p><b>建议模型：</b>Doubao-1.5-vision-pro-32k / Doubao-1.5-vision-lite / Doubao-1.5-vision-pro</p>
                  <p><b>API Key：</b>在 ARK 控制台「API Key 管理」创建，填写到下方 API Key 字段。</p>
                </div>
              </details>
            </div>
          )}

          {/* 4. Zhipu guide */}
          {form.ai_vision_provider === 'zhipu' && (
            <details className="mt-1">
              <summary className="text-[11px] text-blue-500 cursor-pointer">Zhipu 配置说明</summary>
              <div className="mt-1 text-[11px] text-gray-500 space-y-1">
                <p>使用 <code className="text-gray-600 bg-gray-100 px-1 rounded">glm-4.6v-flash</code>，最新免费的视觉理解模型。</p>
                <p>访问 <a href="https://open.bigmodel.cn" target="_blank" className="text-blue-500">智谱 AI 开放平台</a>，创建 API Key 后填写到下方 API Key 字段即可使用。</p>
              </div>
            </details>
          )}

          {/* 5. 模型名称 */}
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">模型名称</label>
            <div className="flex gap-1">
              <input type="text" value={form.ai_vision_model || ''}
                onChange={(e) => updateForm({ ai_vision_model: e.target.value })}
                placeholder={
                  form.ai_vision_provider === 'zhipu' ? 'glm-4.6v-flash' :
                  form.ai_vision_provider === 'doubao' ? 'doubao-vision-pro-32k' :
                  'minicpm-v'
                }
                className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
              <button
                type="button"
                onClick={async () => {
                  setFetchingModels(true)
                  setFetchModelsMsg('')
                  try {
                    const res = await fetch('/api/v1/fetch-models', {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({
                        endpoint: form.ai_vision_endpoint,
                        api_key: form.ai_vision_api_key,
                        provider: form.ai_vision_provider,
                        endpoint_id: form.ai_vision_endpoint_id,
                      }),
                    })
                    const data = await res.json()
                    if (data.ok && data.models.length > 0) {
                      setAiModels(data.models)
                      setFetchModelsMsg(`${data.models.length} 个模型`)
                    } else {
                      setFetchModelsMsg(data.message || '无可用模型')
                    }
                  } catch (e) {
                    setFetchModelsMsg(String(e))
                  }
                  setFetchingModels(false)
                }}
                disabled={fetchingModels || !form.ai_vision_endpoint}
                className="px-2 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-50 whitespace-nowrap"
              >
                {fetchingModels ? '...' : '获取模型'}
              </button>
            </div>
            {aiModels.length > 0 && (
              <select value={form.ai_vision_model || ''}
                onChange={(e) => updateForm({ ai_vision_model: e.target.value })}
                className="w-full mt-1 rounded border border-blue-300 px-2 py-1 text-xs font-mono"
                size={Math.min(aiModels.length + 1, 8)}
              >
                <option value="" disabled>-- 选择模型 --</option>
                {aiModels.map(m => (
                  <option key={m.id} value={m.id}>{m.name}</option>
                ))}
              </select>
            )}
            {fetchModelsMsg && (
              <p className={`text-xs mt-1 ${fetchModelsMsg.includes('个模型') ? 'text-green-600' : 'text-red-500'}`}>
                {fetchModelsMsg}
              </p>
            )}
          </div>

          {/* 6. API Key */}
          <div>
            <label className="text-xs font-medium text-gray-600 block mb-1">API Key</label>
            <input type="password" value={form.ai_vision_api_key || ''}
              onChange={(e) => updateForm({ ai_vision_api_key: e.target.value })}
              placeholder="sk-...  (支持 {env:VAR_NAME})"
              className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono" />
          </div>

          {/* 7. Test button */}
          <button
            type="button"
            onClick={async () => {
              setAiVisionTest('testing');
              try {
                const res = await fetch('/api/v1/check-ai-vision', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    endpoint: form.ai_vision_endpoint,
                    model: form.ai_vision_model,
                    api_key: form.ai_vision_api_key,
                    provider: form.ai_vision_provider,
                    messages_api: form.ai_vision_messages_api,
                    endpoint_id: form.ai_vision_endpoint_id,
                  }),
                });
                const data = await res.json();
                setAiVisionTest(data.ok ? 'ok' : 'fail');
                setAiVisionMsg(data.message || data.error || '');
              } catch (e) {
                setAiVisionTest('fail');
                setAiVisionMsg(String(e));
              }
            }}
            disabled={aiVisionTest === 'testing'}
            className="px-3 py-1.5 text-xs rounded border border-gray-300 bg-white hover:bg-gray-50 disabled:opacity-50"
          >
            {aiVisionTest === 'testing' ? '测试中...' : '检测'}
          </button>
          {aiVisionMsg && (
            <p className={`text-xs ${aiVisionTest === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
              {aiVisionMsg}
            </p>
          )}

          {/* 8. Confirm checkbox */}
          <div className="flex items-center gap-2 pt-2 border-t border-gray-200">
            <input type="checkbox" id="bookmark_confirm_enabled"
              checked={form.bookmark_confirm_enabled ?? false}
              onChange={(e) => updateForm({ bookmark_confirm_enabled: e.target.checked })}
              className="rounded" />
            <label htmlFor="bookmark_confirm_enabled" className="text-xs font-medium text-gray-600 block mb-1">
              管道执行到书签步骤时弹出确认对话框
            </label>
          </div>
        </div>
      )}
```

- [ ] **Step 3: Build frontend**

```bash
cd D:\opencode\book-downloader\frontend
npm run build
```

Expected: tsc + vite pass.

- [ ] **Step 4: Commit**

```bash
cd D:\opencode\book-downloader
git add frontend/src/components/ConfigSettings.tsx
git commit -m "feat: restructure AI Vision settings — 4 providers, Doubao Endpoint ID, Zhipu guide, remove DPI"
```

---

### Self-Review

**1. Spec coverage:**
- Reorder → Provider → Endpoint → (Doubao ID) → Model → Key → Test → Confirm
- 4 providers → `AI_VISION_PROVIDERS` constant with auto-endpoint
- Remove DPI → field removed, default 300 in Task 1
- Doubao Endpoint ID → conditional input + collapsible setup guide
- Zhipu guide → collapsible description with glm-4.6v-flash
- Model fetching → unchanged, adds `endpoint_id` to request body
- Connectivity test → unchanged, adds `endpoint_id` to request body

**2. Placeholder scan:** No TBD/TODO.

**3. Type consistency:**
- `ai_vision_endpoint_id?: string` — added to AppConfig
- `form.ai_vision_endpoint_id` — accessed in conditional render (optional chaining via `|| ''`)
- `AI_VISION_PROVIDERS` uses `as const` for type narrowing
- Provider keys: `'ollama' | 'lmstudio' | 'doubao' | 'zhipu'` — must match backend `check-ai-vision` and `fetch-models`
