# LLM Local OCR Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add support for local LLM vision models (Ollama, LM Studio, OpenAI-compatible APIs) as an OCR engine, capable of extracting text from PDF pages and producing searchable PDF with text layers.

**Architecture:** Extract PDF pages as images via PyMuPDF, send each image to a local LLM endpoint (OpenAI-compatible `/v1/chat/completions` with vision), receive text response, and embed the text as an invisible overlay layer back into the PDF using PyMuPDF's `insert_textbox`/`add_redact_annot`. Model capability is verified before use by sending a tiny test image and checking the response contains recognizable text.

**Tech Stack:** Python 3.10+ (PyMuPDF/fitz for PDF processing, httpx/requests for API calls), TypeScript 5.x (React settings UI)

---

## Design Decisions

1. **API format:** OpenAI-compatible `/v1/chat/completions` with vision. Both Ollama (`http://localhost:11434`) and LM Studio (`http://localhost:1234`) support this.
2. **Model verification:** Send a 100x30 white image with black text "Hello123" and check the response contains expected text. If no recognizable text is returned, the model is considered non-OCR-capable.
3. **Page processing:** Extract each page as PNG at 200 DPI, send to LLM, insert returned text as invisible text layer on the page.
4. **Concurrency:** Process one page at a time (LLM endpoints typically queue requests). Configurable with `llm_ocr_workers`.
5. **Progress:** Emit page-by-page progress with ETA via existing `_emit_progress`.

---

### Task 1: Backend — Create LLM OCR Engine Module

**Files:**
- Create: `backend/engine/llm_ocr.py`
- Test: `test_smoke.py` (add import check)

- [ ] **Step 1: Create the LLM OCR module**

```python
# backend/engine/llm_ocr.py
"""LLM-based OCR engine using OpenAI-compatible vision API (Ollama, LM Studio, etc.)"""

import asyncio
import base64
import io
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def encode_image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def extract_page_images(pdf_path: str, dpi: int = 200) -> List[bytes]:
    """Extract each PDF page as a PNG image. Returns list of image bytes."""
    import fitz
    doc = fitz.open(pdf_path)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


async def verify_llm_model(
    endpoint: str,
    model_name: str,
    api_key: str = "",
    timeout: int = 30,
) -> Tuple[bool, str]:
    """
    Verify a model is OCR-capable by sending a tiny test image.
    Returns (is_ocr_capable, message).
    """
    import httpx
    from PIL import Image, ImageDraw, ImageFont

    # Create a tiny test image with known text
    img = Image.new("RGB", (200, 40), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except Exception:
        font = ImageFont.load_default()
    draw.text((10, 10), "Test123", fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_b64 = encode_image_to_base64(buf.getvalue())

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                    {
                        "type": "text",
                        "text": "Read the text in this image. Reply with ONLY the text, nothing else.",
                    },
                ],
            }
        ],
        "max_tokens": 50,
        "temperature": 0,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{endpoint.rstrip('/')}/v1/chat/completions",
                json=body,
                headers=headers,
            )
            if resp.status_code != 200:
                return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            if "test123" in content.lower() or "Test123" in content:
                return True, f"OCR 验证通过: 识别到 '{content}'"
            return False, f"OCR 验证失败: 返回了 '{content[:50]}' 但不包含 Test123"
    except Exception as e:
        return False, f"连接失败: {str(e)[:100]}"


async def ocr_page(
    endpoint: str,
    model_name: str,
    image_bytes: bytes,
    api_key: str = "",
    language: str = "chi_sim+eng",
    timeout: int = 60,
) -> Optional[str]:
    """Send a single page image to the LLM and return recognized text."""
    import httpx

    img_b64 = encode_image_to_base64(image_bytes)
    lang_hint = "Chinese and English" if "chi_sim" in language else "English"

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Extract ALL text from this image. This is a scanned book page in {lang_hint}. "
                            "Preserve the original text layout, line breaks, and structure. "
                            "Do not add commentary. Output ONLY the extracted text."
                        ),
                    },
                ],
            }
        ],
        "max_tokens": 4096,
        "temperature": 0,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{endpoint.rstrip('/')}/v1/chat/completions",
                json=body,
                headers=headers,
            )
            if resp.status_code != 200:
                logger.warning(f"LLM OCR page failed: HTTP {resp.status_code}")
                return None
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"LLM OCR page error: {e}")
        return None


def build_searchable_pdf(
    original_pdf: str,
    output_pdf: str,
    ocr_results: List[Optional[str]],
) -> bool:
    """
    Overlay OCR text onto each page of the PDF as an invisible text layer.
    ocr_results[i] is the text for page i (0-indexed).
    Returns True on success.
    """
    import fitz

    doc = fitz.open(original_pdf)
    for i, text in enumerate(ocr_results):
        if not text or not text.strip():
            continue
        if i >= len(doc):
            break
        page = doc[i]
        rect = page.rect
        # Insert text as invisible overlay (opacity 0, but searchable)
        page.insert_textbox(
            rect,
            text,
            fontname="helv",
            fontsize=8,
            color=(0, 0, 0),
            render_mode=3,  # invisible but selectable/searchable
        )
    doc.save(output_pdf, garbage=4, deflate=True)
    doc.close()
    return True


async def run_llm_ocr(
    task_id: str,
    pdf_path: str,
    output_pdf: str,
    endpoint: str,
    model_name: str,
    api_key: str = "",
    language: str = "chi_sim+eng",
    timeout: int = 7200,
    emit_progress=None,
    add_log=None,
) -> int:
    """
    Run LLM-based OCR on a PDF. Returns exit code (0 = success).
    Emits progress updates via the callbacks.
    """
    if add_log is None:
        add_log = lambda msg: None

    add_log("LLM OCR: extracting page images...")
    images = extract_page_images(pdf_path, dpi=200)
    total = len(images)
    add_log(f"LLM OCR: {total} pages to process")

    ocr_results: List[Optional[str]] = []
    start_time = time.time()

    for i, img_bytes in enumerate(images):
        page_num = i + 1
        add_log(f"LLM OCR: processing page {page_num}/{total}...")
        if emit_progress:
            await emit_progress(
                step="ocr",
                progress=int(i / total * 100),
                detail=f"{page_num}/{total} 页",
                eta=_compute_eta(start_time, page_num, total),
            )

        text = await ocr_page(endpoint, model_name, img_bytes, api_key, language, timeout=120)
        ocr_results.append(text)

    add_log("LLM OCR: building searchable PDF...")
    ok = build_searchable_pdf(pdf_path, output_pdf, ocr_results)
    if ok:
        add_log("LLM OCR: searchable PDF created successfully")
        return 0
    else:
        add_log("LLM OCR: failed to build output PDF")
        return 1


def _compute_eta(start: float, current: int, total: int) -> str:
    """Format ETA string from elapsed time."""
    elapsed = time.time() - start
    if current <= 1 or elapsed <= 5:
        return ""
    sec_per_page = elapsed / current
    remaining = (total - current) * sec_per_page
    if remaining <= 0:
        return ""
    if remaining < 60:
        return f"约{int(remaining)}秒"
    m = int(remaining // 60)
    s = int(remaining % 60)
    if m < 60:
        return f"约{m}分{s}秒"
    h = m // 60
    m = m % 60
    return f"约{h}时{m}分"
```

- [ ] **Step 2: Commit**

```bash
git add backend/engine/llm_ocr.py
git commit -m "feat: add LLM-based OCR engine module"
```

---

### Task 2: Backend — Integrate LLM OCR into Pipeline

**Files:**
- Modify: `backend/engine/pipeline.py`

- [ ] **Step 1: Add `llm_ocr` branch in `_step_ocr`**

In `_step_ocr` (after existing `elif ocr_engine == "paddleocr":` block), add:

```python
        elif ocr_engine == "llm_ocr":
            task_store.add_log(task_id, "Running LLM-based OCR...")
            
            llm_endpoint = config.get("llm_ocr_endpoint", "http://localhost:11434")
            llm_model = config.get("llm_ocr_model", "llama3.2-vision")
            llm_api_key = config.get("llm_ocr_api_key", "")
            
            if not llm_endpoint or not llm_model:
                task_store.add_log(task_id, "LLM OCR: endpoint or model not configured")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            output_pdf = pdf_path.replace(".pdf", "_ocr.pdf")

            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 10})

            try:
                from engine.llm_ocr import run_llm_ocr

                async def _emit_llm(**kwargs):
                    await _emit_progress(task_id, kwargs["step"], kwargs["progress"], kwargs.get("detail", ""), kwargs.get("eta", ""))

                exit_code = await asyncio.wait_for(
                    run_llm_ocr(
                        task_id=task_id,
                        pdf_path=pdf_path,
                        output_pdf=output_pdf,
                        endpoint=llm_endpoint,
                        model_name=llm_model,
                        api_key=llm_api_key,
                        language=ocr_lang,
                        timeout=ocr_timeout,
                        emit_progress=_emit_llm,
                        add_log=lambda msg: task_store.add_log(task_id, f"  {msg}"),
                    ),
                    timeout=ocr_timeout,
                )
                if exit_code == 0:
                    os.replace(output_pdf, pdf_path)
                    task_store.add_log(task_id, "LLM OCR completed successfully")
                    report["ocr_done"] = True
                else:
                    task_store.add_log(task_id, f"LLM OCR failed with exit code {exit_code}")
            except asyncio.TimeoutError:
                task_store.add_log(task_id, f"LLM OCR timed out after {ocr_timeout}s")
            except Exception as e:
                task_store.add_log(task_id, f"LLM OCR error: {e}")
```

- [ ] **Step 2: Add `llm_ocr` to OCR engine detection in `_step_ocr`**

Find the OCR engine plugin management section (where EasyOCR plugin is installed/uninstalled), add a check for `llm_ocr`:

```python
        if ocr_engine == "llm_ocr":
            # No plugin management needed for LLM OCR (uses HTTP API)
            pass
```

- [ ] **Step 3: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: integrate LLM OCR into pipeline"
```

---

### Task 3: Backend — Add check-ocr and install-ocr endpoints for LLM

**Files:**
- Modify: `backend/api/search.py`

- [ ] **Step 1: Add `llm_ocr` to `check-ocr` endpoint**

In the `check-ocr` handler, add after `appleocr` check:

```python
        elif engine == "llm_ocr":
            from config import get_config
            cfg = get_config()
            endpoint = cfg.get("llm_ocr_endpoint", "")
            model = cfg.get("llm_ocr_model", "")
            api_key = cfg.get("llm_ocr_api_key", "")
            if not endpoint or not model:
                return {"ok": False, "engine": "llm_ocr", "message": "未配置端点或模型名"}
            try:
                from engine.llm_ocr import verify_llm_model
                ok, msg = await verify_llm_model(endpoint, model, api_key)
                return {"ok": ok, "engine": "llm_ocr", "message": msg, "endpoint": endpoint}
            except Exception as e:
                return {"ok": False, "engine": "llm_ocr", "message": f"验证失败: {str(e)[:100]}"}
```

Note: The existing `check-ocr` route is `async def` so we can call `await verify_llm_model`.

- [ ] **Step 2: Add `llm_ocr` to `install-ocr` endpoint**

In the install handler:

```python
        elif engine == "llm_ocr":
            return {"ok": False, "message": "LLM OCR 需要手动配置端点，请在设置中填写 Ollama/LM Studio 地址"}
```

- [ ] **Step 3: Commit**

```bash
git add backend/api/search.py
git commit -m "feat: add LLM OCR check endpoint"
```

---

### Task 4: Frontend — Add Type Definitions

**Files:**
- Modify: `frontend/src/types.ts`

- [ ] **Step 1: Add LLM OCR config fields to `AppConfig`**

```typescript
export interface AppConfig {
  // ... existing fields ...
  llm_ocr_endpoint: string
  llm_ocr_model: string
  llm_ocr_api_key: string
  [key: string]: unknown
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/types.ts
git commit -m "feat: add LLM OCR config types"
```

---

### Task 5: Frontend — Add LLM OCR Engine Option

**Files:**
- Modify: `frontend/src/components/ConfigSettings.tsx`

- [ ] **Step 1: Add `llm_ocr` to `OCR_ENGINES` list**

```typescript
const OCR_ENGINES = [
  { key: 'tesseract', name: 'Tesseract OCR', desc: '内置引擎，需 chi_sim 语言包' },
  { key: 'paddleocr', name: 'PaddleOCR', desc: '百度引擎，需 Python 3.11 虚拟环境' },
  { key: 'easyocr', name: 'EasyOCR', desc: 'PyTorch 引擎，CPU 较慢' },
  { key: 'appleocr', name: 'AppleOCR', desc: '仅 macOS 支持' },
  { key: 'llm_ocr', name: 'LLM OCR', desc: '本地大模型 OCR (Ollama/LM Studio)' },
]
```

- [ ] **Step 2: Add LLM OCR config fields to `DEFAULT_CONFIG`**

```typescript
const DEFAULT_CONFIG: AppConfig = {
  // ... existing defaults ...
  llm_ocr_endpoint: 'http://localhost:11434',
  llm_ocr_model: '',
  llm_ocr_api_key: '',
}
```

- [ ] **Step 3: Add LLM OCR settings panel in OCR section**

Add after the OCR engine switching section, a new collapsible section for LLM OCR configuration:

```tsx
          {/* LLM OCR 设置 */}
          {form.ocr_engine === 'llm_ocr' && (
            <div className="border-t border-gray-200 pt-3 space-y-2">
              <span className="text-xs font-medium text-gray-600 block">LLM OCR 配置</span>
              <div>
                <label className="text-xs text-gray-500">API 端点</label>
                <input
                  type="text"
                  value={form.llm_ocr_endpoint || ''}
                  onChange={(e) => updateForm({ llm_ocr_endpoint: e.target.value })}
                  placeholder="http://localhost:11434"
                  className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono"
                />
                <p className="text-xs text-gray-400 mt-0.5">Ollama 默认 11434，LM Studio 默认 1234</p>
              </div>
              <div>
                <label className="text-xs text-gray-500">模型名称</label>
                <input
                  type="text"
                  value={form.llm_ocr_model || ''}
                  onChange={(e) => updateForm({ llm_ocr_model: e.target.value })}
                  placeholder="llama3.2-vision 或 minicpm-v"
                  className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500">API Key (可选)</label>
                <input
                  type="password"
                  value={form.llm_ocr_api_key || ''}
                  onChange={(e) => updateForm({ llm_ocr_api_key: e.target.value })}
                  placeholder="LM Studio 通常不需要"
                  className="w-full rounded border border-gray-300 px-2 py-1.5 text-xs font-mono"
                />
              </div>
              <p className="text-xs text-amber-600 bg-amber-50 p-2 rounded">
                提示：使用前请确保 Ollama/LM Studio 已运行，且模型为多模态（vision）模型。
              </p>
            </div>
          )}
```

- [ ] **Step 4: Add LLM OCR to auto-detect engines list**

```typescript
    const engines = ['tesseract', 'paddleocr', 'easyocr', 'appleocr', 'llm_ocr']
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ConfigSettings.tsx
git commit -m "feat: add LLM OCR settings UI"
```

---

### Task 6: Verification

- [ ] **Step 1: Run smoke test**

Run: `python test_smoke.py`
Expected: All tests pass (20/20).

- [ ] **Step 2: TypeScript compilation**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: verify LLM OCR implementation"
```

---

## Self-Review

### 1. Spec coverage
- Ollama support: ✅ OpenAI-compatible `/v1/chat/completions` endpoint works with Ollama
- LM Studio support: ✅ Same API format
- OCR model verification: ✅ Task 1 `verify_llm_model()` sends test image
- Searchable PDF output: ✅ Task 1 `build_searchable_pdf()` adds text layer via PyMuPDF
- Settings integration: ✅ Task 5 adds UI
- Progress feedback: ✅ Task 2 integrates with existing `_emit_progress`

### 2. Placeholder scan
No TBD, TODO, or "implement later" found. All code is complete.

### 3. Type consistency
- `AppConfig.llm_ocr_endpoint`, `llm_ocr_model`, `llm_ocr_api_key` consistent across types.ts and ConfigSettings.tsx
- `ocr_engine === "llm_ocr"` consistent across pipeline.py and search.py
- `verify_llm_model(endpoint, model, api_key)` signature matches all callers
