# PaddleOCR 三模式选择器 + MinerU 保持空间分配

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PaddleOCR online engine offers 3 OCR modes selectable in settings (spatial / perbox / hybrid), each with clear Chinese descriptions. MinerU stays on spatial allocation only.

**Architecture:** The pipeline reads `paddleocr_online_mode` config key (`"spatial"|"perbox"|"hybrid"`, default `"spatial"`). Three branches share Surya detection but diverge at text acquisition: spatial calls API once and uses `allocate_text_to_surya_boxes()`, perbox calls `embed_with_perbox_paddleocr()`, hybrid calls `hybrid_perbox_with_fallback()`. Frontend shows a segmented-radio selector with mode descriptions below.

**Tech Stack:** Python 3.12, React/TypeScript, existing pipeline + embed functions

---

## File Structure

| File | Role |
|---|---|
| `backend/engine/pipeline.py:2655-2757` | PaddleOCR block: branch by `paddleocr_online_mode` |
| `frontend/src/types.ts:133-134` | Add `paddleocr_online_mode?: string` to `AppConfig` |
| `frontend/src/components/ConfigSettings.tsx:2048-2081` | Add mode selector UI in PaddleOCR section |
| `frontend/src/constants.ts` | No change needed |

---

### Task 1: Backend — paddleocr_online_mode branching in pipeline

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pipeline.py:2655-2757`

- [ ] **Step 1: Read the current PaddleOCR block**

Read `D:\opencode\book-downloader\backend\engine\pipeline.py` from line 2655 to 2757. Note the current single path (spatial allocation only).

- [ ] **Step 2: Replace the PaddleOCR block**

Replace the entire `elif ocr_engine == "paddleocr_online":` block (from line 2655 through line 2757) with the version below. The Surya detection + fallback (lines 2655-2699) stays identical regardless of mode. The divergence starts after Surya detection succeeds:

```python
        elif ocr_engine == "paddleocr_online":
            paddle_token = config.get("paddleocr_online_token", "")
            if not paddle_token:
                task_store.add_log(task_id, "PaddleOCR online: no token configured, skipping")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            paddle_mode = config.get("paddleocr_online_mode", "spatial")
            task_store.add_log(task_id, f"PaddleOCR online ({paddle_mode}): Surya detection + PaddleOCR-VL-1.5 API")
            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 5, "detail": "Running Surya detection..."})

            try:
                from backend.engine.surya_detect import run_surya_detect, SuryaDetectError
                from backend.engine.paddleocr_online_client import PaddleOCRClient, parse_paddleocr_blocks
                from backend.engine.pdf_api_embed import allocate_text_to_surya_boxes, embed_with_surya_boxes

                # Step 1: Surya line detection (shared by all modes)
                try:
                    surya_boxes = await run_surya_detect(pdf_path, dpi=200)
                except SuryaDetectError as e:
                    task_store.add_log(task_id, f"PaddleOCR: Surya detection failed — {e}. Falling back to block-level layout.")
                    from backend.engine.pdf_api_embed import embed_api_text_layer
                    client = PaddleOCRClient(token=paddle_token)
                    try:
                        with open(pdf_path, "rb") as f:
                            pdf_bytes = f.read()
                        job_id = await client.submit_job_file(pdf_path, pdf_bytes)
                        result_data = await client.poll_job(job_id, progress_callback=None)
                        jsonl_url = result_data.get("resultUrl", {}).get("jsonUrl", "")
                        raw_jsonl = await client.download_raw_jsonl(jsonl_url)
                        layout = parse_paddleocr_blocks(raw_jsonl)
                    finally:
                        await client.close()
                    total_blocks = sum(len(v) for v in layout.values())
                    task_store.add_log(task_id, f"PaddleOCR fallback: parsed {len(layout)} pages, {total_blocks} blocks")
                    output_pdf = pdf_path + ".paddleocr.pdf"
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, embed_api_text_layer, pdf_path, output_pdf, layout)
                    if os.path.exists(output_pdf) and os.path.getsize(output_pdf) > 0:
                        os.replace(output_pdf, pdf_path)
                        report["ocr_done"] = True
                        task_store.add_log(task_id, "PaddleOCR online complete (fallback: block-level layout)")
                    else:
                        task_store.add_log(task_id, "PaddleOCR fallback: embedding produced empty or missing output file")
                    await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                    return report

                total_boxes = sum(len(v) for v in surya_boxes.values())
                task_store.add_log(task_id, f"PaddleOCR: Surya detected {total_boxes} boxes across {len(surya_boxes)} pages")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 20, "detail": f"Surya: {total_boxes} boxes"})

                # ── Mode branch ──

                if paddle_mode == "spatial":
                    # Spatial allocation: call API once, width-proportional split
                    task_store.add_log(task_id, "PaddleOCR (spatial): calling API for block-level layout...")
                    await _emit(task_id, "step_progress", {"step": "ocr", "progress": 25, "detail": "PaddleOCR-VL-1.5 API..."})

                    client = PaddleOCRClient(token=paddle_token)
                    try:
                        with open(pdf_path, "rb") as f:
                            pdf_bytes = f.read()
                        job_id = await client.submit_job_file(pdf_path, pdf_bytes)
                        result_data = await client.poll_job(job_id, progress_callback=None)
                        jsonl_url = result_data.get("resultUrl", {}).get("jsonUrl", "")
                        if not jsonl_url:
                            raise RuntimeError("PaddleOCR: no jsonl URL in completed job")
                        raw_jsonl_text = await client.download_raw_jsonl(jsonl_url)
                    finally:
                        await client.close()

                    layout = parse_paddleocr_blocks(raw_jsonl_text)
                    page_texts = allocate_text_to_surya_boxes(surya_boxes, layout)
                else:
                    # perbox / hybrid: need full-doc layout for fallback, pass to embed functions
                    task_store.add_log(task_id, f"PaddleOCR ({paddle_mode}): calling API...")
                    await _emit(task_id, "step_progress", {"step": "ocr", "progress": 25, "detail": "PaddleOCR-VL-1.5 API..."})

                    client = PaddleOCRClient(token=paddle_token)
                    try:
                        with open(pdf_path, "rb") as f:
                            pdf_bytes = f.read()
                        job_id = await client.submit_job_file(pdf_path, pdf_bytes)
                        result_data = await client.poll_job(job_id, progress_callback=None)
                        jsonl_url = result_data.get("resultUrl", {}).get("jsonUrl", "")
                        if not jsonl_url:
                            raise RuntimeError("PaddleOCR: no jsonl URL in completed job")
                        raw_jsonl_text = await client.download_raw_jsonl(jsonl_url)
                        api_layout = parse_paddleocr_blocks(raw_jsonl_text)
                    finally:
                        await client.close()

                    if paddle_mode == "perbox":
                        from backend.engine.pdf_api_embed import embed_with_perbox_paddleocr
                        task_store.add_log(task_id, "PaddleOCR (perbox): running per-box crop OCR...")
                        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 30, "detail": "Per-box OCR..."})
                        loop = asyncio.get_event_loop()
                        page_texts = await loop.run_in_executor(
                            None, embed_with_perbox_paddleocr,
                            pdf_path, surya_boxes, paddle_token, 200, 3,
                        )
                    else:  # hybrid
                        from backend.engine.pdf_api_embed import hybrid_perbox_with_fallback
                        task_store.add_log(task_id, "PaddleOCR (hybrid): per-box OCR + spatial fallback...")
                        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 30, "detail": "Hybrid OCR..."})
                        loop = asyncio.get_event_loop()
                        page_texts = await loop.run_in_executor(
                            None, hybrid_perbox_with_fallback,
                            pdf_path, surya_boxes, paddle_token, api_layout, 200, 3,
                        )

                total_text = sum(len(t) for v in page_texts.values() for t in v if t)
                all_boxes_count = sum(len(v) for v in page_texts.values())
                matched = sum(1 for v in page_texts.values() for t in v if t)
                task_store.add_log(task_id, f"PaddleOCR ({paddle_mode}): {matched}/{all_boxes_count} boxes received text ({total_text} chars)")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 85, "detail": f"{matched} boxes matched"})

                # Step 4: Embed with Surya bboxes (shared)
                output_pdf = pdf_path + ".paddleocr.pdf"
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, embed_with_surya_boxes,
                    pdf_path, output_pdf, surya_boxes, page_texts,
                )

                if os.path.exists(output_pdf) and os.path.getsize(output_pdf) > 0:
                    os.replace(output_pdf, pdf_path)
                    report["ocr_done"] = True
                    task_store.add_log(task_id, f"PaddleOCR online complete ({paddle_mode}: Surya boxes + PaddleOCR text)")
                else:
                    raise RuntimeError("PaddleOCR: embedding produced empty file")

                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})

            except asyncio.TimeoutError:
                task_store.add_log(task_id, "PaddleOCR online timed out")
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                last_lines = "\n".join(tb.split(chr(10))[-5:])
                task_store.add_log(task_id, f"PaddleOCR online error: {e} | {last_lines}"[:500])
```

- [ ] **Step 3: Verify syntax**

```bash
python -m py_compile backend\engine\pipeline.py
```

Work from: `D:\opencode\book-downloader`
Expected: silent success.

- [ ] **Step 4: Commit**

```bash
cd D:\opencode\book-downloader
git add backend/engine/pipeline.py
git commit -m "feat: PaddleOCR pipeline branches by paddleocr_online_mode (spatial/perbox/hybrid)"
```

---

### Task 2: Frontend — mode selector UI with descriptions

**Files:**
- Modify: `D:\opencode\book-downloader\frontend\src\types.ts` — add field
- Modify: `D:\opencode\book-downloader\frontend\src\components\ConfigSettings.tsx` — add UI

- [ ] **Step 1: Add config field to types.ts**

Read `D:\opencode\book-downloader\frontend\src\types.ts`. Find the `AppConfig` interface (around line 130-135). Add the field after `paddleocr_online_token`:

In the `AppConfig` interface, add after line 133 (`paddleocr_online_token?: string`):

```typescript
  paddleocr_online_mode?: string  // "spatial" | "perbox" | "hybrid"
```

- [ ] **Step 2: Add default value in ConfigSettings.tsx form init**

Read `D:\opencode\book-downloader\frontend\src\components\ConfigSettings.tsx`. Find the `const [form, setForm]` initialization (around line 170-180). Add after `paddleocr_online_token`:

Find where `paddleocr_online_token: '',` is defined in the form initial state and add after it:

```typescript
    paddleocr_online_mode: 'spatial',
```

- [ ] **Step 3: Add mode selector UI in PaddleOCR section**

In `ConfigSettings.tsx`, find the PaddleOCR section (after line 2048, inside `{form.ocr_engine === 'paddleocr_online' && (`). Add the mode selector BEFORE the Token input (after the help text). Insert this block after the `<p>` help text (lines 2050-2053) and BEFORE the `<div>` containing the token label (line 2054):

```tsx
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1.5">识别模式</label>
              <div className="flex rounded border border-gray-300 overflow-hidden text-xs">
                {[
                  { key: 'spatial', label: '空间分配', desc: '段落文字精准，行识别不精确' },
                  { key: 'perbox', label: '逐框识别', desc: '行识别精准，有乱码风险' },
                  { key: 'hybrid', label: '混合识别', desc: '逐框为主、空间填补，可能有重复' },
                ].map(({ key, label, desc }) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => updateForm({ paddleocr_online_mode: key })}
                    className={`flex-1 py-1.5 text-center transition-colors ${
                      (form.paddleocr_online_mode || 'spatial') === key
                        ? 'bg-blue-500 text-white'
                        : 'bg-white text-gray-600 hover:bg-gray-50'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <p className="text-[11px] text-gray-400 mt-1">
                {(form.paddleocr_online_mode || 'spatial') === 'spatial' && '段落识别精准，行识别不精准'}
                {(form.paddleocr_online_mode || 'spatial') === 'perbox' && '行识别精准，有乱码风险'}
                {(form.paddleocr_online_mode || 'spatial') === 'hybrid' && '逐框识别为主，空间分配填补，可能会产生识别重复'}
              </p>
            </div>
```

- [ ] **Step 4: Build frontend**

```bash
cd D:\opencode\book-downloader\frontend
npm run build
```

Expected: tsc + vite build both pass.

- [ ] **Step 5: Commit**

```bash
cd D:\opencode\book-downloader
git add frontend/src/types.ts frontend/src/components/ConfigSettings.tsx
git commit -m "feat: add PaddleOCR mode selector (spatial/perbox/hybrid) with descriptions"
```

---

### Self-Review

**1. Spec coverage:**
- MinerU stays spatial allocation → unchanged, already the case
- PaddleOCR 3 modes via config → Task 1 (backend) + Task 2 (frontend)
- UI descriptions → Task 2 Step 3
- Naming/style consistent → Task 2 Step 3 uses same blue/white button pattern as other settings

**2. Placeholder scan:** No TBD/TODO. All code shown in full.

**3. Type consistency:**
- `paddleocr_online_mode` default is `"spatial"` in both backend (`config.get("paddleocr_online_mode", "spatial")`) and frontend (`form.paddleocr_online_mode || 'spatial'`)
- `paddleocr_online_mode` values: `"spatial"`, `"perbox"`, `"hybrid"` — consistent across backend branching and frontend buttons
- `embed_with_perbox_paddleocr()` signature: `(input_path, surya_boxes, paddle_token, dpi=200, max_concurrency=3)` — called correctly in Task 1
- `hybrid_perbox_with_fallback()` signature: `(input_path, surya_boxes, paddle_token, api_layout, dpi=200, max_concurrency=3)` — called correctly in Task 1
- Both functions return `Dict[int, List[str]]` — compatible with `embed_with_surya_boxes()`'s `page_texts` parameter
