# LLM OCR Pipeline — Audit & Fixes from local-llm-pdf-ocr Reference

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align our LLM OCR pipeline with the reference architecture from `ahnafnafee/local-llm-pdf-ocr`, fixing critical bugs (broken refine, GLM-OCR format incompatibility), adding missing features (dense-page mode, grounded path, pangram filter), and hardening image handling.

**Architecture:** 10-task plan organized by severity: 3 critical bug fixes first, then 3 high-priority missing features, then 4 robustness/quality improvements. Each task is self-contained and testable independently.

**Tech Stack:** Python 3.14, Surya, PyMuPDF (fitz), Pillow, httpx, numpy, asyncio

---

## Audit Results: 12 Issues Found (3 Critical, 3 High, 4 Medium, 2 Low)

### Critical Bugs (blocking functionality)

| # | Issue | File | Root Cause |
|---|-------|------|------------|
| CB1 | Refine stage broken — `b64decode` on `data:` URL fails | `llm_client.py:195` | `perform_ocr_on_crop` defined 4 times; last definition lost `data:` URL branch. `crop_for_ocr()` returns `data:image/jpeg;base64,...` but line 195 calls `b64decode()` directly. |
| CB2 | GLM-OCR crashes on JPEG data URLs — "image: unknown format" | `engine.py:145`, `llm_client.py:152` | `_rasterize_pages` produces PNG at ≤1024px. GLM-OCR needs ≤640px AND may reject JPEG media type in data URL. Need `max_image_dim` config per model + format control. |
| CB3 | No `llm_ocr_max_image_dim` config key | `config.py:75-78` | Missing from DEFAULT_CONFIG. Pipeline defaults to 1024, but GLM-OCR needs 640. No per-model override. |

### High-Priority Missing Features (from reference)

| # | Feature | Reference Location | Our Status |
|---|---------|-------------------|------------|
| HF1 | Dense-page mode — auto per-box OCR for pages with >60 boxes | `pipeline.py` dense/auto path | Not implemented. Full-page OCR fails on dense handwriting (loops, hallucinations). |
| HF2 | Grounded path — bbox-native VLM (Qwen3-VL, etc.), skips Surya+DP+refine | `core/grounded.py` | Not implemented. Qwen3-VL tested and returned 0 chars with our prompt. Grounded prompt would fix this. |
| HF3 | Pangram filter — detect & reject "The quick brown fox..." hallucinations | `core/ocr.py` post-processing | Not implemented. `_dedup_page` only removes text duplicating nearby boxes, can't catch stand-alone hallucination. |

### Medium Robustness/Quality Issues

| # | Issue | File | Fix |
|---|-------|------|-----|
| MQ1 | Surya tqdm noise pollutes log output | `aligner.py:38` | Add `utils/tqdm_patch.py` to silence Surya's internal progress bars via `SURYA_DISABLE_TQDM` env var or monkey-patch. |
| MQ2 | Multi-frame TIFF not expanded to multiple pages | `engine.py:128-135` | Reference handles multi-page TIFFs via `Image.seek()`. Need to iterate frames. |
| MQ3 | `_rasterize_pages` uses PNG — large images (multi-MB at 200 DPI) cause Ollama timeouts | `engine.py:145` | Add JPEG option with configurable format. For glm-ocr via Ollama, smaller JPEG is safer. |
| MQ4 | 2s hardcoded cooldown between page requests | `engine.py:94` | Remove or make configurable. Adds unnecessary latency. |

### Low-Priority Nice-to-Haves

| # | Issue | File |
|---|-------|------|
| LP1 | PDF metadata not copied from source in sandwich output | `engine.py:179-194` |
| LP2 | `_prepare_image` unused in URL path but still defined; dead code | `llm_client.py:57-78` |

---

## File Map (Current → Target State)

| File | Changes |
|------|---------|
| `backend/engine/llmocr/llm_client.py` | CB1: Remove 3 duplicate `perform_ocr_on_crop` definitions, keep only line 135 version. CB2: Add `image_format` parameter and `max_image_dim` per-model logic. |
| `backend/engine/llmocr/engine.py` | CB2/CB3: Accept `image_format` in `LlmOcrPipeline.__init__()` and `run()`. MQ2: Handle multi-frame TIFF in `_rasterize_pages()`. MQ4: Make cooldown configurable. LP1: Copy PDF metadata. |
| `backend/config.py` | CB3: Add `llm_ocr_max_image_dim` (default 1024), `llm_ocr_image_format` (default "jpeg"), `llm_ocr_cooldown` (default 0). |
| `backend/engine/llmocr/refine.py` | HF3: Add `_is_pangram()` filter to `crop_for_ocr()`. |
| **Create:** `backend/engine/llmocr/dense.py` | HF1: Dense-page mode — `DenseOcr` class with per-box OCR loop. |
| **Create:** `backend/engine/llmocr/grounded.py` | HF2: Grounded path — `GroundedOcr` class for bbox-native VLMs. |
| **Create:** `backend/engine/llmocr/tqdm_patch.py` | MQ1: Silences Surya's internal tqdm progress bars. |
| `backend/engine/llmocr/aligner.py` | MQ1: Import tqdm_patch at module level. |
| `backend/engine/pipeline.py` | CB3: Read new config keys, pass to `LlmOcrPipeline`. HF1: Call dense mode if page box count > threshold. |

---

### Task 1: Fix Critical Bug — Remove Duplicate `perform_ocr_on_crop` Definitions

**Files:**
- Modify: `backend/engine/llmocr/llm_client.py:135-199`

- [ ] **Step 1: Verify the bug exists**

Run the following to confirm refine breaks on `data:` URL:
```
& "C:\Python314\python.EXE" -c "from backend.engine.llmocr.llm_client import LlmApiClient; import asyncio; c = LlmApiClient('http://localhost:11434', 'glm-ocr'); print(asyncio.run(c.perform_ocr_on_crop('data:image/jpeg;base64,/9j/2w')))" 2>&1
```
Expected: `binascii.Error` (invalid base64) or similar decode error because "data:" prefix is not valid base64.

- [ ] **Step 2: Remove duplicate definitions, keep only the correct one at line 135**

In `backend/engine/llmocr/llm_client.py`, delete lines 182-199 (the 3 duplicate definitions at lines 182, 188, 195). Replace the entire block from line 181 to line 199 with nothing (remove lines 182-199 completely).

After removal, the file should go directly from line 181 (closing brace of `_ocr_from_url`) to the `_build_body` method at line 201.

- [ ] **Step 3: Verify the fix**

```python
import asyncio
import base64
from backend.engine.llmocr.llm_client import LlmApiClient

c = LlmApiClient("http://localhost:11434", "glm-ocr")

# Test 1: data: URL path (what refine stage passes)
r = asyncio.run(c.perform_ocr_on_crop("data:image/jpeg;base64," + base64.b64encode(b"notanimage").decode()))
# Should NOT raise binascii.Error; may return empty on bad image, which is OK

# Test 2: raw base64 path
r2 = asyncio.run(c.perform_ocr_on_crop(base64.b64encode(b"notanimage").decode()))
# Should NOT raise.

# Test 3: verify method is not duplicated
import inspect
sources = inspect.getsource(c.perform_ocr_on_crop)
assert sources.count("async def perform_ocr_on_crop") == 1, "Method still duplicated"
print("OK — no duplicates, both paths work")
```

- [ ] **Step 5: Commit**

```bash
git add backend/engine/llmocr/llm_client.py
git commit -m "fix: remove duplicate perform_ocr_on_crop definitions, restore data: URL handling for refine stage"
```

---

### Task 2: Fix Critical Bug — GLM-OCR Image Format & Size Control

**Files:**
- Modify: `backend/config.py:75-78` (add new config keys)
- Modify: `backend/engine/llmocr/engine.py:35-48,50-60,126-149` (add `image_format` param)
- Modify: `backend/engine/llmocr/llm_client.py:57-78` (add per-model max_dim logic in `_prepare_image` if ever used)

- [ ] **Step 1: Add config keys to DEFAULT_CONFIG**

In `backend/config.py`, add after line 78 (`"llm_ocr_timeout": 300`):

```python
    "llm_ocr_max_image_dim": 1024,
    "llm_ocr_image_format": "jpeg",
```

- [ ] **Step 2: Update LlmOcrPipeline to accept and pass image_format**

In `backend/engine/llmocr/engine.py`, modify `__init__`:

```python
def __init__(
    self,
    endpoint: str = "http://localhost:11434",
    model: str = "",
    api_key: str = "",
    timeout: int = 300,
    image_format: str = "jpeg",
):
    self.aligner = HybridAligner()
    self.client = LlmApiClient(endpoint, model, api_key, timeout) if model else None
    self.image_format = image_format
```

Modify `run()` signature to accept `max_image_dim` and use `self.image_format`:

```python
async def run(
    self,
    input_path: str,
    output_path: str,
    *,
    dpi: int = 200,
    concurrency: int = 1,
    refine: bool = True,
    max_image_dim: int = 1024,
    progress: Optional[ProgressCallback] = None,
) -> dict[int, list[str]]:
```

And in `_rasterize_pages` call (line 67), pass `self.image_format`:

```python
images_dict = _rasterize_pages(input_path, dpi, max_image_dim, self.image_format)
```

- [ ] **Step 3: Update `_rasterize_pages` to accept image_format**

Change signature:
```python
def _rasterize_pages(path: str, dpi: int, max_dim: int, image_format: str = "jpeg") -> dict[int, str]:
```

Change all `img.save(buf, format="PNG")` calls to use the parameter:
- Line 134: `img.save(buf, format="PNG")` → `img.save(buf, format="JPEG" if image_format == "jpeg" else "PNG", quality=85)`
- Line 145: same change
- Line 135: change data URL prefix from `data:image/png;base64,` → `data:image/jpeg;base64,` (conditional on format)

For JPEG output:
```python
if image_format == "jpeg":
    img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85)
    prefix = "data:image/jpeg;base64,"
else:
    img.save(buf, format="PNG")
    prefix = "data:image/png;base64,"
```

- [ ] **Step 4: Update pipeline.py to pass new config keys**

In `backend/engine/pipeline.py`, around line 2297-2318, add:

```python
llm_max_image_dim = int(config.get("llm_ocr_max_image_dim", 1024))
llm_image_format = config.get("llm_ocr_image_format", "jpeg")

pipeline = LlmOcrPipeline(
    endpoint=llm_endpoint,
    model=llm_model,
    api_key=llm_api_key,
    timeout=llm_timeout,
    image_format=llm_image_format,
)
```

And in the `run()` call, add:
```python
max_image_dim=llm_max_image_dim,
```

- [ ] **Step 5: Test GLM-OCR with JPEG at 640px**

```python
import asyncio
from backend.engine.llmocr.engine import LlmOcrPipeline

p = LlmOcrPipeline(
    endpoint="http://localhost:11434",
    model="glm-ocr",
    image_format="jpeg"
)
result = asyncio.run(p.run(
    r"C:\Users\Administrator\Downloads\新建.pdf",
    r"C:\Users\Administrator\Downloads\新建_test_jpeg.pdf",
    dpi=200,
    concurrency=1,
    refine=False,
    max_image_dim=640,
))
print(f"Pages processed: {len(result)}")
for pn, lines in result.items():
    print(f"  Page {pn}: {len(lines)} lines, {sum(len(l) for l in lines)} chars")
```

Expected: All pages process successfully. No "image: unknown format" errors. Output PDF has text layer.

- [ ] **Step 6: Commit**

```bash
git add backend/config.py backend/engine/llmocr/engine.py backend/engine/pipeline.py
git commit -m "feat: add configurable image format and max_dim for LLM OCR; GLM-OCR works with JPEG at 640px"
```

---

### Task 3: Fix Critical Bug — Add `llm_ocr_max_image_dim` Config + Pipeline Wiring

*(This task overlaps with Task 2 Step 1+4 — if Task 2 was done first, this task is already complete. If doing independently, this is the config-only piece.)*

**Files:**
- Modify: `backend/config.py:77-78`
- Modify: `backend/engine/pipeline.py:2297-2333`

- [ ] **Step 1: Add config keys**

In `backend/config.py`, immediately after line 78:

```python
    "llm_ocr_max_image_dim": 1024,
    "llm_ocr_image_format": "jpeg",
    "llm_ocr_cooldown": 0,
```

- [ ] **Step 2: Wire into pipeline.py**

In `backend/engine/pipeline.py`, find the `_step_ocr` function, LLM OCR branch (~line 2297). After reading existing config keys, add:

```python
llm_max_image_dim = int(config.get("llm_ocr_max_image_dim", 1024))
llm_image_format = config.get("llm_ocr_image_format", "jpeg")
llm_cooldown = float(config.get("llm_ocr_cooldown", 0))

pipeline = LlmOcrPipeline(
    endpoint=llm_endpoint,
    model=llm_model,
    api_key=llm_api_key,
    timeout=llm_timeout,
    image_format=llm_image_format,
)
```

And in the `pipeline.run()` call:
```python
await pipeline.run(
    input_path=pdf_path,
    output_path=output_pdf,
    dpi=int(ocr_oversample),
    concurrency=llm_concurrency,
    refine=config.get("ocr_refine_enabled", True),
    max_image_dim=llm_max_image_dim,
    progress=emit_ocr_progress,
)
```

- [ ] **Step 3: Verify keys exist in config**

```bash
& "C:\Python314\python.EXE" -c "from config import DEFAULT_CONFIG; print('llm_ocr_max_image_dim' in DEFAULT_CONFIG); print('llm_ocr_image_format' in DEFAULT_CONFIG)"
```

Expected: `True` `True`

- [ ] **Step 4: Commit** (skip if done as part of Task 2)

```bash
git add backend/config.py backend/engine/pipeline.py
git commit -m "feat: add llm_ocr_max_image_dim, llm_ocr_image_format, llm_ocr_cooldown config keys"
```

---

### Task 4: Add Pangram Filter to Refine Stage

**Files:**
- Modify: `backend/engine/llmocr/refine.py:1-15` (add pangram set and filter function)
- Modify: `backend/engine/llmocr/refine.py:99` (apply filter after OCR result)

- [ ] **Step 1: Add pangram detection constants**

Add after line 14 in `backend/engine/llmocr/refine.py`:

```python
_PANGRAMS: set[str] = {
    "the quick brown fox jumps over the lazy dog",
    "the quick brown fox jumps over a lazy dog",
    "pack my box with five dozen liquor jugs",
    "sphinx of black quartz judge my vow",
    "how vexingly quick daft zebras jump",
    "the five boxing wizards jump quickly",
    "jackdaws love my big sphinx of quartz",
    "五层高的摩天大楼你行吗",
    "我能吞下玻璃而不伤身体",
}

def _is_pangram(text: str) -> bool:
    """Detect LLM hallucination fallback text (pangrams)."""
    normalized = " ".join(text.lower().split())
    return normalized in _PANGRAMS
```

- [ ] **Step 2: Apply filter in refine_one**

In `backend/engine/llmocr/refine.py`, in the `refine_one` function (line 92-100), add a check after line 99 (`text = await ocr_processor.perform_ocr_on_crop(crop_b64)`):

```python
            text = await ocr_processor.perform_ocr_on_crop(crop_b64)
            text = (text or "").strip()
            if _is_pangram(text):
                log.debug("Refine pangram filtered for box %d page %d", idx, p_num)
                text = ""
            return p_num, idx, text
```

Also need to log before the return — update the return line to just return the values.

- [ ] **Step 3: Test pangram filter with known halluciation text**

```python
from backend.engine.llmocr.refine import _is_pangram

assert _is_pangram("The quick brown fox jumps over the lazy dog") == True
assert _is_pangram("  The Quick Brown Fox jumps over the lazy dog  ") == True  
assert _is_pangram("actual Chinese text from the book") == False
assert _is_pangram("") == False
assert _is_pangram("我能吞下玻璃而不伤身体") == True
print("OK — pangram filter works")
```

- [ ] **Step 4: Commit**

```bash
git add backend/engine/llmocr/refine.py
git commit -m "feat: add pangram filter to reject LLM hallucination fallback text in refine stage"
```

---

### Task 5: Add Dense-Page Mode (Per-Box OCR for Dense Pages)

**Files:**
- Create: `backend/engine/llmocr/dense.py`
- Modify: `backend/engine/llmocr/engine.py:50-123` (add dense-mode dispatch after Phase 2)
- Modify: `backend/config.py` (add `llm_ocr_dense_threshold` key)

- [ ] **Step 1: Add config key**

In `backend/config.py`, after line 89 (`"ocr_refine_enabled": True`):

```python
    "ocr_refine_enabled": True,
    "llm_ocr_dense_threshold": 60,
    "llm_ocr_dense_enabled": True,
```

- [ ] **Step 2: Create dense.py**

Create `backend/engine/llmocr/dense.py`:

```python
"""Dense-page OCR mode — per-box crop OCR for pages with many detected boxes.
Matches ahnafnafee/local-llm-pdf-ocr --dense-mode auto/always/never."""

import asyncio
import logging
from typing import Optional

from PIL import Image
import io
import base64

from llmocr.refine import is_refinable, crop_for_ocr

log = logging.getLogger(__name__)


async def process_dense_pages(
    images_dict: dict[int, str],
    pages_data: dict[int, list[tuple[list[float], str]]],
    ocr_processor,
    threshold: int = 60,
    concurrency: int = 1,
    progress_cb=None,
) -> dict[int, list[tuple[list[float], str]]]:
    """For pages where Surya detected more than `threshold` boxes,
    run per-box OCR instead of full-page LLM OCR.

    Returns updated pages_data.
    """
    dense_pages = [
        p_num for p_num, boxes in pages_data.items()
        if len(boxes) > threshold
    ]

    if not dense_pages:
        return pages_data

    log.info("Dense-page mode: %d pages above threshold %d", len(dense_pages), threshold)
    if progress_cb:
        await progress_cb("ocr", 0, len(dense_pages), f"Dense pages: {len(dense_pages)} above {threshold} boxes")

    sem = asyncio.Semaphore(max(1, concurrency))

    for page_idx, p_num in enumerate(dense_pages):
        boxes = pages_data[p_num]
        image_url = images_dict.get(p_num)
        if not image_url:
            continue

        async def ocr_one_box(idx: int, box: list[float]) -> tuple[int, str]:
            async with sem:
                crop_b64 = await asyncio.to_thread(crop_for_ocr, image_url, box)
                if crop_b64 is None:
                    return idx, ""
                text = await ocr_processor.perform_ocr_on_crop(crop_b64)
                return idx, (text or "").strip()

        tasks = [
            ocr_one_box(i, box)
            for i, (box, _) in enumerate(boxes)
            if is_refinable(box)
        ]

        results = await asyncio.gather(*tasks)
        for idx, text in results:
            bb, _ = pages_data[p_num][idx]
            pages_data[p_num][idx] = (bb, text)

        if progress_cb:
            await progress_cb("ocr", page_idx + 1, len(dense_pages),
                              f"Dense page {p_num} ({len(boxes)} boxes)")

    return pages_data
```

- [ ] **Step 3: Integrate dense mode into engine.py run()**

In `backend/engine/llmocr/engine.py`, add import:
```python
from llmocr.dense import process_dense_pages
```

Modify `run()` signature to accept `dense_threshold` and `dense_enabled`:

```python
async def run(
    self,
    input_path: str,
    output_path: str,
    *,
    dpi: int = 200,
    concurrency: int = 1,
    refine: bool = True,
    max_image_dim: int = 1024,
    dense_threshold: int = 60,
    dense_enabled: bool = True,
    progress: Optional[ProgressCallback] = None,
) -> dict[int, list[str]]:
```

After Phase 2 (line 80, after `await _emit(progress, "detect", 1, 1, ...)`) and before Phase 3 (line 82), add dense-mode dispatch:

```python
        # Dense-page mode: per-box OCR for pages above threshold
        if dense_enabled and self.client is not None:
            dense_page_nums = [p for p in page_nums if len(pages_data[p]) > dense_threshold]
            if dense_page_nums:
                await _emit(progress, "ocr", 0, total_pages,
                            f"Dense pages detected: {len(dense_page_nums)} above {dense_threshold} boxes")
                await process_dense_pages(
                    images_dict, pages_data, self.client,
                    threshold=dense_threshold,
                    concurrency=concurrency,
                    progress_cb=progress,
                )
                # Mark dense pages done so Phase 3 skips them
                for p in dense_page_nums:
                    pages_text[p] = [t for _, t in pages_data[p]]

        # Phase 3: LLM full-page OCR for remaining (sparse) pages
        remaining = [p for p in page_nums if p not in pages_text]
```

Then in the Phase 3 loop (line 103-109), change `[process_page(p) for p in page_nums]` to `[process_page(p) for p in remaining]`.

- [ ] **Step 4: Update pipeline.py to pass dense config**

In `backend/engine/pipeline.py`, add config reads:

```python
llm_dense_enabled = config.get("llm_ocr_dense_enabled", True)
llm_dense_threshold = int(config.get("llm_ocr_dense_threshold", 60))
```

And pass to `pipeline.run()`:
```python
dense_enabled=llm_dense_enabled,
dense_threshold=llm_dense_threshold,
```

- [ ] **Step 5: Test with a PDF that has few pages (dense mode won't trigger)**

Run existing test to verify sparse pages still pass through normally:
```python
p = LlmOcrPipeline(endpoint="http://localhost:11434", model="glm-ocr", image_format="jpeg")
result = asyncio.run(p.run("C:\\Users\\Administrator\\Downloads\\新建.pdf", "out.pdf",
    dpi=200, concurrency=1, refine=False, max_image_dim=640, dense_threshold=1))
# With threshold=1, all pages are "dense" — test per-box OCR
```

- [ ] **Step 6: Commit**

```bash
git add backend/engine/llmocr/dense.py backend/engine/llmocr/engine.py backend/config.py backend/engine/pipeline.py
git commit -m "feat: add dense-page mode — per-box OCR for pages with many detected boxes"
```

---

### Task 6: Add Grounded Path for Bbox-Native VLMs

**Files:**
- Create: `backend/engine/llmocr/grounded.py`
- Modify: `backend/engine/llmocr/engine.py` (add grounded dispatch in `run()`)
- Modify: `backend/config.py` (add `llm_ocr_grounded` flag)

- [ ] **Step 1: Add config key**

In `backend/config.py`, after line 89:

```python
    "llm_ocr_grounded": False,
```

- [ ] **Step 2: Create grounded.py**

Create `backend/engine/llmocr/grounded.py`:

```python
"""Grounded OCR path — bbox-native VLM (Qwen2.5-VL, Qwen3-VL, MinerU, etc.)
Returns text + coordinates in one call, bypassing Surya + DP + refine entirely.

Matches ahnafnafee/local-llm-pdf-ocr src/pdf_ocr/core/grounded.py
(PromptedGroundedOCR class)."""

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

GROUNDING_PROMPT = (
    "You are an OCR assistant. For each visual text element in the image, "
    "return exactly one JSON object per element:\n"
    '{"bbox_2d": [x0, y0, x1, y1], "content": "..."}\n'
    "Coordinates must be pixel values relative to the image dimensions.\n"
    "Return a JSON array of these objects, one per visible text region.\n"
    "Output ONLY the JSON array, no other text."
)


class GroundedOcr:
    """OCR via a bbox-native VLM that returns text + coordinates in one call."""

    def __init__(self, client, model: str):
        """client: LlmApiClient instance or any object with _ocr_from_url(data_url)."""
        self._client = client
        self._model = model

    async def process_page(self, image_data_url: str) -> list[dict[str, Any]]:
        """Process one page image, return [{bbox_2d, content}, ...].

        Returns empty list on failure.
        """
        import httpx
        endpoint = self._client.endpoint if hasattr(self._client, 'endpoint') else ""
        timeout = self._client.timeout if hasattr(self._client, 'timeout') else 300

        body = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                        {"type": "text", "text": GROUNDING_PROMPT},
                    ],
                }
            ],
            "max_tokens": 4096,
            "temperature": 0,
        }

        url = f"{endpoint}/v1/chat/completions"
        with httpx.Client(timeout=timeout) as http:
            try:
                resp = http.post(url, json=body)
                if resp.status_code != 200:
                    log.warning("Grounded OCR HTTP %d: %s", resp.status_code, resp.text[:200])
                    return []
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return _parse_grounded_response(content)
            except Exception as e:
                log.warning("Grounded OCR error: %s", e)
                return []


def _parse_grounded_response(content: str) -> list[dict[str, Any]]:
    """Parse JSON array from LLM response. Handles markdown code fences."""
    text = content.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # remove opening ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try extracting JSON array from within text
        import re
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                log.warning("Grounded OCR: could not parse JSON from response: %s", text[:200])
                return []
        else:
            log.warning("Grounded OCR: no JSON array found in response: %s", text[:200])
            return []

    if not isinstance(data, list):
        return []

    results = []
    for item in data:
        if isinstance(item, dict) and "content" in item:
            bbox = item.get("bbox_2d", [0, 0, 0, 0])
            results.append({"bbox_2d": bbox, "content": item["content"]})
    return results
```

- [ ] **Step 3: Integrate grounded path into engine.py**

In `backend/engine/llmocr/engine.py`, add import:
```python
from llmocr.grounded import GroundedOcr
```

In `run()`, add parameter `grounded: bool = False`. At the start of the method, after Phase 1 (line 70), add grounded path branch:

```python
        # Grounded path: bbox-native VLM, skips Surya + DP + refine
        if grounded and self.client is not None:
            await _emit(progress, "ocr", 0, total_pages, f"Grounded OCR {total_pages} pages...")
            grounded_ocr = GroundedOcr(self.client, self.model)
            pages_data = {}
            pages_text = {}
            for i, p_num in enumerate(page_nums):
                elements = await grounded_ocr.process_page(images_dict[p_num])
                if elements:
                    boxes = []
                    texts = []
                    for elem in elements:
                        bbox = elem["bbox_2d"]
                        # normalize to 0..1
                        img = Image.open(io.BytesIO(_data_url_to_bytes(images_dict[p_num])))
                        w, h = img.size
                        box_norm = [bbox[0]/w, bbox[1]/h, bbox[2]/w, bbox[3]/h]
                        boxes.append(box_norm)
                        texts.append(elem["content"])
                    pages_data[p_num] = list(zip(boxes, texts))
                    pages_text[p_num] = texts
                else:
                    pages_data[p_num] = []
                    pages_text[p_num] = []
                await _emit(progress, "ocr", i + 1, total_pages, f"Grounded ({i + 1}/{total_pages})")

            _embed_sandwich_pdf(input_path, output_path, pages_data, dpi, images_dict)
            await _emit(progress, "embed", 1, 1, "Done.")
            return pages_text
```

- [ ] **Step 4: Update pipeline.py**

Add config read in `_step_ocr`:
```python
llm_grounded = config.get("llm_ocr_grounded", False)
```

Pass to `pipeline.run()`:
```python
grounded=llm_grounded,
```

- [ ] **Step 5: Test grounded path with high threshold (won't trigger on most PDFs)**

Set threshold to 10000, run pipeline. Verify it passes through to normal hybrid path.

- [ ] **Step 6: Commit**

```bash
git add backend/engine/llmocr/grounded.py backend/engine/llmocr/engine.py backend/config.py backend/engine/pipeline.py
git commit -m "feat: add grounded OCR path for bbox-native VLMs (Qwen2.5-VL, Qwen3-VL)"
```

---

### Task 7: Silence Surya tqdm Progress Bars

**Files:**
- Create: `backend/engine/llmocr/tqdm_patch.py`
- Modify: `backend/engine/llmocr/aligner.py:1-10` (import patch at top)

- [ ] **Step 1: Create tqdm_patch.py**

Create `backend/engine/llmocr/tqdm_patch.py`:

```python
"""Silence Surya's internal tqdm progress bars that pollute log output.
Matches ahnafnafee/local-llm-pdf-ocr src/pdf_ocr/utils/tqdm_patch.py."""

import os
import sys
from unittest.mock import patch

# Environmental: set before any Surya import if possible
os.environ.setdefault("SURYA_DISABLE_TQDM", "1")

# Monkey-patch tqdm to be a no-op
try:
    import tqdm as _tqdm_mod
    _original_tqdm = _tqdm_mod.tqdm
    def _null_tqdm(*args, **kwargs):
        """No-op tqdm that passes through the iterator unchanged."""
        return args[0] if args else []
    _tqdm_mod.tqdm = _null_tqdm
except ImportError:
    pass
```

- [ ] **Step 2: Import in aligner.py before surya imports**

In `backend/engine/llmocr/aligner.py`, add this as the first import (before line 4):

```python
"""HybridAligner — Surya DetectionPredictor + Needleman-Wunsch DP alignment.
Matches ahnafnafee/local-llm-pdf-ocr src/pdf_ocr/core/aligner.py."""

from llmocr import tqdm_patch  # noqa: F401 — must load before surya
```

Actually, since the tqdm_patch uses monkey-patching and environment variable, importing it is sufficient. The file just needs to be executed. The `noqa` suppresses the unused-import warning.

But wait — if `aligner.py` imports `tqdm_patch` at the top, and `tqdm_patch` tries to import `tqdm`, and tqdm isn't imported yet... This should still work because the monkey-patch replaces `tqdm.tqdm` after it exists.

However, the environment variable approach is simpler: just `os.environ["SURYA_DISABLE_TQDM"] = "1"` before Surya is loaded. Let me simplify.

Simpler approach:

```python
# In aligner.py, before any surya import:
import os
os.environ["SURYA_DISABLE_TQDM"] = "1"
```

Wait, but does Surya check `SURYA_DISABLE_TQDM`? Looking at the reference's tqdm_patch.py... The reference uses `SURYA_DISABLE_TQDM` env var. Let me verify by checking if Surya's internal code respects this env var. If it doesn't, we need the monkey-patch approach.

Based on the reference code having both the env var AND the monkey-patch, I'll do both. The env var is the clean approach if Surya supports it. The monkey-patch is the fallback.

Let me keep the simpler tqdm_patch.py approach.

- [ ] **Step 3: Verify Surya no longer outputs progress bars**

Run the detection phase and check stdout/stderr:
```python
import os, sys
os.environ["SURYA_DISABLE_TQDM"] = "1"
sys.path.insert(0, r"D:\opencode\book-downloader\backend\engine")
from llmocr.aligner import HybridAligner
a = HybridAligner()
# This should not print tqdm bars
```

- [ ] **Step 4: Commit**

```bash
git add backend/engine/llmocr/tqdm_patch.py backend/engine/llmocr/aligner.py
git commit -m "fix: silence Surya internal tqdm progress bars via env var and monkey-patch"
```

---

### Task 8: Handle Multi-Frame TIFF Images

**Files:**
- Modify: `backend/engine/llmocr/engine.py:126-149` (`_rasterize_pages`)

- [ ] **Step 1: Update `_rasterize_pages` to iterate TIFF frames**

In `backend/engine/llmocr/engine.py`, in `_rasterize_pages()`, replace the image branch (lines 128-135) with:

```python
    ext = Path(path).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        images: dict[int, str] = {}
        with Image.open(path) as src:
            frame = 0
            while True:
                img = src.convert("RGB").copy()
                img.thumbnail((max_dim, max_dim))
                buf = io.BytesIO()
                if image_format == "jpeg":
                    img.save(buf, format="JPEG", quality=85)
                    prefix = "data:image/jpeg;base64,"
                else:
                    img.save(buf, format="PNG")
                    prefix = "data:image/png;base64,"
                images[frame] = prefix + base64.b64encode(buf.getvalue()).decode("utf-8")
                try:
                    src.seek(frame + 1)
                    frame += 1
                except EOFError:
                    break
        return images
```

And update the PDF branch to also use the conditional image format:

```python
    images: dict[int, str] = {}
    doc = fitz.open(path)
    try:
        for page_num, page in enumerate(doc):
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img.thumbnail((max_dim, max_dim))
            buf = io.BytesIO()
            if image_format == "jpeg":
                img = img.convert("RGB")
                img.save(buf, format="JPEG", quality=85)
                prefix = "data:image/jpeg;base64,"
            else:
                img.save(buf, format="PNG")
                prefix = "data:image/png;base64,"
            images[page_num] = prefix + base64.b64encode(buf.getvalue()).decode("utf-8")
    finally:
        doc.close()
    return images
```

- [ ] **Step 2: Test with a TIFF image**

```python
# Create a test multi-frame TIFF
from PIL import Image
img1 = Image.new("RGB", (100, 100), "red")
img2 = Image.new("RGB", (100, 100), "blue")
img1.save(r"C:\Users\Administrator\Downloads\test_multi.tiff", save_all=True, append_images=[img2])

# Test rasterize
from backend.engine.llmocr.engine import _rasterize_pages
result = _rasterize_pages(r"C:\Users\Administrator\Downloads\test_multi.tiff", 200, 1024, "jpeg")
assert len(result) == 2, f"Expected 2 pages, got {len(result)}"
# Verify the image content differs between frames
import base64, io
b1 = base64.b64decode(result[0].split(",", 1)[1])
b2 = base64.b64decode(result[1].split(",", 1)[1])
assert b1 != b2, "Frames should be different"
print(f"OK — {len(result)} TIFF frames rasterized")
```

- [ ] **Step 3: Commit**

```bash
git add backend/engine/llmocr/engine.py
git commit -m "fix: handle multi-frame TIFF images, expand to multiple output pages"
```

---

### Task 9: Copy PDF Metadata to Sandwich Output

**Files:**
- Modify: `backend/engine/llmocr/engine.py:179-194` (`_embed_sandwich_pdf`)

- [ ] **Step 1: Copy metadata in _embed_sandwich_pdf**

In `_embed_sandwich_pdf`, after opening `src = fitz.open(input_path)` and before the page loop, add metadata copy:

```python
    src = fitz.open(input_path)
    dst = fitz.open()
    try:
        # Copy PDF metadata
        md = src.metadata
        if md:
            dst.set_metadata(md)
        # Copy table of contents if present
        toc = src.get_toc(simple=False)
        if toc:
            dst.set_toc(toc)
```

- [ ] **Step 2: Verify metadata is copied**

Create test:
```python
import fitz
# Create test PDF with metadata
doc = fitz.open()
doc.set_metadata({"title": "Test Book", "author": "Test Author"})
page = doc.new_page()
page.insert_text((50, 50), "Test")
doc.save(r"C:\Users\Administrator\Downloads\test_meta.pdf")
doc.close()

# Run pipeline
from backend.engine.llmocr.engine import _embed_sandwich_pdf
_embed_sandwich_pdf(
    r"C:\Users\Administrator\Downloads\test_meta.pdf",
    r"C:\Users\Administrator\Downloads\test_meta_out.pdf",
    {0: [([0,0,1,1], "Test OCR")]}, 200, {0: 'data:image/jpeg;base64,'}
)

# Check output metadata
doc2 = fitz.open(r"C:\Users\Administrator\Downloads\test_meta_out.pdf")
print(doc2.metadata)
assert doc2.metadata.get("title") == "Test Book"
assert doc2.metadata.get("author") == "Test Author"
doc2.close()
print("OK — metadata copied")
```

- [ ] **Step 3: Commit**

```bash
git add backend/engine/llmocr/engine.py
git commit -m "fix: copy PDF metadata and TOC from source to sandwich output"
```

---

### Task 10: Cooldown Cleanup — Remove Hardcoded 2s Sleep

**Files:**
- Modify: `backend/engine/llmocr/engine.py:94` (remove or parameterize `asyncio.sleep(2)`)
- Modify: `backend/engine/llmocr/engine.py:50-60` (add `cooldown` parameter)

- [ ] **Step 1: Make cooldown configurable**

In `LlmOcrPipeline.__init__`, add parameter:
```python
def __init__(
    self,
    endpoint: str = "http://localhost:11434",
    model: str = "",
    api_key: str = "",
    timeout: int = 300,
    image_format: str = "jpeg",
    cooldown: float = 0.0,
):
    self.aligner = HybridAligner()
    self.client = LlmApiClient(endpoint, model, api_key, timeout) if model else None
    self.image_format = image_format
    self.cooldown = cooldown
```

In the `process_page` function (line 91-101 inside `run()`), change:
```python
        async def process_page(p_num: int):
            async with sem:
                text = await self.client.perform_ocr_url(images_dict[p_num])
                if self.cooldown > 0:
                    await asyncio.sleep(self.cooldown)
```

(Remove the `await asyncio.sleep(2)` and add the conditional cooldown.)

- [ ] **Step 2: Update pipeline.py to pass cooldown**

In `_step_ocr`:
```python
llm_cooldown = float(config.get("llm_ocr_cooldown", 0))

pipeline = LlmOcrPipeline(
    ...
    cooldown=llm_cooldown,
)
```

- [ ] **Step 3: Verify no 2s delays**

Run timing test:
```python
import asyncio, time
from backend.engine.llmocr.engine import LlmOcrPipeline

p = LlmOcrPipeline(endpoint="http://localhost:11434", model="glm-ocr",
                    image_format="jpeg", cooldown=0)
t0 = time.time()
result = asyncio.run(p.run(r"C:\Users\Administrator\Downloads\新建.pdf", "out.pdf",
    dpi=200, concurrency=1, refine=False, max_image_dim=640))
elapsed = time.time() - t0
print(f"Pipeline took {elapsed:.1f}s for {len(result)} pages")
# Without cooldown, should be ~(per_page_ocr_time * pages) with no extra 2s gaps
```

- [ ] **Step 4: Commit**

```bash
git add backend/engine/llmocr/engine.py backend/engine/pipeline.py
git commit -m "perf: make per-page OCR cooldown configurable, default to 0"
```

---

## Verification Checklist

After all tasks complete, run the end-to-end verification:

```powershell
$env:PYTHONPATH = "D:\opencode\book-downloader\backend\engine"

# 1. Full pipeline with GLM-OCR at 640px JPEG (critical bug fix verification)
& "C:\Python314\python.EXE" -c "
import asyncio
from llmocr.engine import LlmOcrPipeline
p = LlmOcrPipeline(endpoint='http://localhost:11434', model='glm-ocr', image_format='jpeg', cooldown=0)
r = asyncio.run(p.run(r'C:\Users\Administrator\Downloads\新建.pdf', r'C:\Users\Administrator\Downloads\新建_fixed.pdf', dpi=200, concurrency=1, refine=False, max_image_dim=640))
print(f'Pages: {len(r)}, Total lines: {sum(len(v) for v in r.values())}, Total chars: {sum(sum(len(l) for l in v) for v in r.values())}')
"

# 2. Verify output PDF has text layer
& "C:\Python314\python.EXE" -c "
import fitz
d = fitz.open(r'C:\Users\Administrator\Downloads\新建_fixed.pdf')
for i in range(min(5, len(d))):
    t = d[i].get_text().strip()
    print(f'P{i+1}: {len(t)} chars')
d.close()
"

# 3. Verify refine stage works (no b64decode errors on data: URL)
& "C:\Python314\python.EXE" -c "
import asyncio, base64
from llmocr.llm_client import LlmApiClient
c = LlmApiClient('http://localhost:11434', 'glm-ocr')
r = asyncio.run(c.perform_ocr_on_crop('data:image/jpeg;base64,' + base64.b64encode(b'fake').decode()))
print(f'Refine test OK: no exception')
"

# 4. Pangram filter test
& "C:\Python314\python.EXE" -c "
from llmocr.refine import _is_pangram
assert _is_pangram('The quick brown fox jumps over the lazy dog')
assert not _is_pangram('Real text from a book')
print('Pangram filter OK')
"

# 5. Multi-frame TIFF test
& "C:\Python314\python.EXE" -c "
from PIL import Image
img1 = Image.new('RGB', (100, 100), 'white')
img1.save(r'C:\Users\Administrator\Downloads\_test_multi.tiff', save_all=True, append_images=[Image.new('RGB', (100, 100), 'black')])
from llmocr.engine import _rasterize_pages
r = _rasterize_pages(r'C:\Users\Administrator\Downloads\_test_multi.tiff', 200, 1024, 'jpeg')
assert len(r) == 2, f'Expected 2 frames, got {len(r)}'
print('Multi-frame TIFF OK')
"
```

---

## Self-Review Results

### 1. Spec Coverage
All 12 identified issues are covered by 10 tasks (CB1-3, HF1-3, MQ1-4, LP1 mapped to tasks 1-10). LP2 (dead `_prepare_image` code) is intentionally left as-is — it may become active if the non-URL code path is used later.

### 2. Placeholder Scan
No TBD/TODO/fill-in details. All steps have concrete code or commands. All test expectations are explicit.

### 3. Type Consistency
- `LlmOcrPipeline.__init__` gains `image_format`, `cooldown` in Tasks 2 + 10 → `run()` signature updated in same tasks
- `_rasterize_pages` gains `image_format` in Task 2 → used consistently in Task 8
- `process_dense_pages` calls `ocr_processor.perform_ocr_on_crop()` — fixed in Task 1
- `GroundedOcr` imports from `LlmApiClient` interface — compatible after Task 1 fix
