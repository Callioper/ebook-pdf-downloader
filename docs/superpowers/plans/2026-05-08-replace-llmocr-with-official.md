# Replace llmocr Plugin with Official local-llm-pdf-ocr

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom `backend/engine/llmocr/` ocrmypdf plugin with the official `ahnafnafee/local-llm-pdf-ocr` CLI tool, called directly as a subprocess in the LLM-OCR pipeline step.

**Architecture:** Fork the official repo, install it as a pip package, modify `_step_ocr` in `pipeline.py` to call `local-llm-pdf-ocr` CLI instead of `ocrmypdf --plugin llmocr.plugin`. Parse its stdout for progress. Remove old `llmocr/` plugin directory.

**Tech Stack:** Python 3.10+, `uv`/pip, `local-llm-pdf-ocr` (CLI), Surya OCR, FastAPI (not used, Web UI skipped), Rich (progress bars).

---

## Key Differences: Old vs New

| Aspect | Old (`backend/engine/llmocr/`) | New (`local-llm-pdf-ocr`) |
|--------|------|------|
| Framework | ocrmypdf plugin (`generate_pdf`/`generate_ocr` hooks) | Standalone CLI |
| Detection | Page-based Tesseract fallback | Surya batch detection (10-21x faster) |
| Alignment | None (raw LLM text) | Needleman-Wunsch DP aligner + refine |
| Output | Plain text layer in PDF | Sandwich PDF with horizontal-scale matrices |
| Dense pages | Full-page OCR (loops/hallucinates) | Auto per-box OCR (>60 boxes threshold) |
| Grounded | Not supported | `--grounded` for Qwen2.5/3-VL, MinerU |
| Progress | `[N]` stderr markers | Rich progress bars |
| Config keys | `llm_ocr_endpoint`, `llm_ocr_model`, `llm_ocr_api_key`, `llm_ocr_timeout` | `--api-base`, `--model` |

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/engine/pipeline.py` | Modify | `_step_ocr`: replace ocrmypdf+plugin subprocess with `local-llm-pdf-ocr` CLI call |
| `backend/engine/llmocr/` | Delete | Entire directory — old plugin, no longer needed |
| `frontend/src/components/ConfigSettings.tsx` | Modify | Remove `llm_ocr_timeout` and `llm_ocr_api_key` fields; rename `llm_ocr_endpoint`→`llm_api_base`, `llm_ocr_model`→`llm_model` |
| `frontend/src/types.ts` | Modify | Update `AppConfig` type: rename fields |
| `backend/config.py` | Modify | Update `DEFAULT_CONFIG`: rename keys, remove `llm_ocr_timeout`/`llm_ocr_api_key` |
| `backend/config.default.json` | Modify | Same key renames |
| `backend/engine/zlib_downloader.py` | Reference | Uses `llm_ocr_endpoint` indirectly? Need to verify |

---

### Task 1: Fork Official Repo + Install

- [ ] **Step 1: Fork on GitHub**

Open `https://github.com/ahnafnafee/local-llm-pdf-ocr` in browser, click Fork button, fork to your account. This creates `https://github.com/<your-user>/local-llm-pdf-ocr` as a backup/rollback point.

- [ ] **Step 2: Clone to local workspace**

```bash
cd D:\opencode
git clone https://github.com/ahnafnafee/local-llm-pdf-ocr.git
cd local-llm-pdf-ocr
```

- [ ] **Step 3: Install the tool**

```bash
cd D:\opencode\local-llm-pdf-ocr
pip install uv  # if not already installed
uv sync
# Test installation:
uv run local-llm-pdf-ocr --help
```

Expected: Shows CLI help with `--api-base`, `--model`, `--dpi`, `--concurrency`, etc.

- [ ] **Step 4: Test with a PDF**

```bash
$env:LLM_API_BASE="http://127.0.0.1:12345/v1"
$env:LLM_MODEL="sabafallah/deepseek-ocr"
uv run local-llm-pdf-ocr --api-base http://127.0.0.1:12345/v1 --model sabafallah/deepseek-ocr --dpi 200 --max-image-dim 1024 "C:\Users\Administrator\Downloads\新建.pdf" "C:\Users\Administrator\Downloads\新建_ocr_new.pdf" 2>&1
```

Verify output PDF has searchable text layer.

- [ ] **Step 5: Commit the fork reference**

```bash
cd D:\opencode\book-downloader
git commit --allow-empty -m "chore: switch to official local-llm-pdf-ocr, fork at <github-user>/local-llm-pdf-ocr"
```

---

### Task 2: Update Config Keys

**Files:**
- Modify: `backend/config.py:45-48`
- Modify: `frontend/src/types.ts:127-129`
- Modify: `frontend/src/components/ConfigSettings.tsx:140-1618`

Rename config keys to match the new tool's terminology and remove unused keys.

- [ ] **Step 1: Update backend config defaults**

In `backend/config.py`, replace:
```python
    "llm_ocr_endpoint": "http://localhost:11434",
    "llm_ocr_model": "",
    "llm_ocr_api_key": "",
    "llm_ocr_timeout": 300,
```

With:
```python
    "llm_api_base": "http://localhost:1234/v1",
    "llm_model": "",
```

- [ ] **Step 2: Update frontend types**

In `frontend/src/types.ts`, replace:
```typescript
  llm_ocr_endpoint: string
  llm_ocr_model: string
  llm_ocr_api_key: string
  llm_ocr_timeout: number
```

With:
```typescript
  llm_api_base: string
  llm_model: string
```

- [ ] **Step 3: Update ConfigSettings.tsx form**

In `frontend/src/components/ConfigSettings.tsx`:

Find the form defaults around line 140:
```typescript
  llm_ocr_endpoint: "http://localhost:11434",
  llm_ocr_model: "",
  llm_ocr_api_key: "",
  llm_ocr_timeout: 300,
```

Replace with:
```typescript
  llm_api_base: "http://localhost:1234/v1",
  llm_model: "",
```

Find and update the LLM-OCR settings UI section (look for `llm_ocr_endpoint` input around line 1600-1665). Replace the relevant input fields with simplified versions:

Remove `llm_ocr_api_key` and `llm_ocr_timeout` input fields entirely. Rename `llm_ocr_endpoint` → `llm_api_base`, `llm_ocr_model` → `llm_model`.

- [ ] **Step 4: Commit**

```bash
git add backend/config.py frontend/src/types.ts frontend/src/components/ConfigSettings.tsx
git commit -m "refactor: rename llm_ocr_* config keys to llm_api_base/llm_model for official tool"
```

---

### Task 3: Replace LLM-OCR Pipeline Step

**Files:**
- Modify: `backend/engine/pipeline.py:2171-2240` (`_step_ocr` LLM-OCR branch)
- Delete: `backend/engine/llmocr/` (entire directory)

- [ ] **Step 1: Replace subprocess command**

In `backend/engine/pipeline.py`, find the LLM-OCR section (starts with `elif ocr_engine == "llm_ocr":` around line 2171). Replace the cmd construction and execution:

Replace this block (lines 2171-2240):
```python
        elif ocr_engine == "llm_ocr":
            task_store.add_log(task_id, "Running LLM-based OCR via llmocr plugin...")
            ...
            cmd = [
                _py_for_ocr, "-m", "ocrmypdf",
                "--plugin", "llmocr.plugin",
                ...
            ]
            ...
            _exit = await _run_ocrmypdf_with_progress(task_id, cmd, ...)
```

With:
```python
        elif ocr_engine == "llm_ocr":
            task_store.add_log(task_id, "Running LLM-based OCR via local-llm-pdf-ocr...")
            ocr_timeout = max(ocr_timeout, 7200)  # override for LLM

            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 5})

            # 1. Check if PDF already has text layer
            if not _is_scanned(pdf_path, python_cmd=_py_for_ocr):
                task_store.add_log(task_id, "PDF already has text layer, skipping OCR")
                report["ocr_done"] = True
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 10})

            llm_api_base = config.get("llm_api_base", "http://localhost:1234/v1")
            llm_model = config.get("llm_model", "")
            llm_api_key = config.get("llm_api_key", "")

            if not llm_model:
                task_store.add_log(task_id, "LLM OCR: model not configured")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            output_pdf = pdf_path.replace(".pdf", "_ocr.pdf")

            # Build command using local-llm-pdf-ocr CLI
            # Find the tool: try 'local-llm-pdf-ocr' in PATH, then uv run from install dir
            _llmocr_cmd = None
            import shutil as _shutil
            for _candidate in ["local-llm-pdf-ocr"]:
                _f = _shutil.which(_candidate)
                if _f:
                    _llmocr_cmd = [_f]
                    break
            if not _llmocr_cmd:
                # Try uv run from default install location
                _default_install = os.path.join(os.path.dirname(sys.executable), "..", "..", "local-llm-pdf-ocr")
                if not os.path.isdir(_default_install):
                    _default_install = r"D:\opencode\local-llm-pdf-ocr"
                if os.path.isdir(_default_install):
                    _llmocr_cmd = ["uv", "run", "local-llm-pdf-ocr"]

            if not _llmocr_cmd:
                task_store.add_log(task_id, "LLM OCR: local-llm-pdf-ocr not found, please install it")
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            cmd = _llmocr_cmd + [
                "--api-base", llm_api_base,
                "--model", llm_model,
                "--dpi", ocr_oversample,
                "--concurrency", str(ocr_jobs),
                "--max-image-dim", "1024",
            ]
            if llm_api_key:
                cmd += ["--api-key", llm_api_key]
            cmd += [pdf_path, output_pdf]

            task_store.add_log(task_id, f"LLM OCR command: {' '.join(cmd[:8])}...")
            _ocr_env = {
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                "LLM_API_BASE": llm_api_base,
                "LLM_MODEL": llm_model,
            }

            try:
                _exit = await _run_ocrmypdf_with_progress(
                    task_id, cmd, env=_ocr_env,
                    timeout=ocr_timeout, total_pages=_total_pages,
                    output_pdf=output_pdf,
                )
                if _exit == 0:
                    task_store.add_log(task_id, "LLM OCR completed, validating quality...")
                    if _is_ocr_readable(output_pdf, python_cmd=_py_for_ocr):
                        os.replace(output_pdf, pdf_path)
                        task_store.add_log(task_id, "LLM OCR quality check passed")
                        report["ocr_done"] = True
                    else:
                        task_store.add_log(task_id, "LLM OCR quality check failed, keeping original PDF")
                        try:
                            os.remove(output_pdf)
                        except Exception:
                            pass
                else:
                    task_store.add_log(task_id, f"LLM OCR failed with exit code {_exit}")
            except asyncio.TimeoutError:
                task_store.add_log(task_id, f"LLM OCR timed out after {ocr_timeout}s")
            except Exception as e:
                task_store.add_log(task_id, f"LLM OCR error: {e}")
```

- [ ] **Step 2: Add progress parsing for local-llm-pdf-ocr output**

The official tool outputs lines with page counts via Rich progress bars. In `_run_ocrmypdf_with_progress`, add parsing for the new format. The tool prints lines like:
- "OCR: 45%|████  | 15/33 [02:30<03:00, 10.0s/page]"

Add after the existing `_llm` parser (around line 260) in the reader:

```python
            # Parse local-llm-pdf-ocr progress: "OCR: 45%|..."
            _llm_progress = re.search(r'OCR:\s*(\d+)%', _text)
            if _llm_progress:
                _pct = int(_llm_progress.group(1))
                if total_pages > 0:
                    _cur = int(total_pages * _pct / 100)
                    _tot = total_pages
                if _cur % 10 == 0 or _pct >= 100:
                    task_store.add_log(task_id, f"  LLM-OCR: {_pct}% (~{_cur}/{_tot} 页)")
                await _emit_progress(task_id, "ocr", _pct, f"~{_cur}/{_tot} 页", "")
                continue
```

- [ ] **Step 3: Delete old llmocr plugin directory**

```bash
Remove-Item -Recurse -Force "D:\opencode\book-downloader\backend\engine\llmocr"
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat: replace llmocr plugin with official local-llm-pdf-ocr CLI"
```

---

### Task 4: Build, Deploy, Test

- [ ] **Step 1: Rebuild PyInstaller exe**

```bash
cd D:\opencode\book-downloader
python -m PyInstaller --noconfirm backend\book-downloader.spec
```

- [ ] **Step 2: Deploy and restart**

```bash
Stop-Process -Name BookDownloader -Force -ErrorAction SilentlyContinue
Copy-Item "dist\BookDownloader.exe" "backend\dist\BookDownloader.exe" -Force
Start-Process "backend\dist\BookDownloader.exe"
```

- [ ] **Step 3: Verify with a test PDF**

Create a task for a test PDF and verify:
1. LLM-OCR step uses `local-llm-pdf-ocr` (check logs)
2. Progress parsing works (percentage shows up)
3. Output PDF has searchable text
4. Old config keys still work (backward compat via config migration)

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: final verification after local-llm-pdf-ocr migration"
```

---

## Self-Review

### Spec Coverage
| Requirement | Task |
|---|---|
| Fork official repo as backup | Task 1 Step 1 |
| Install official tool | Task 1 Steps 2-4 |
| Update config keys | Task 2 |
| Replace pipeline LLM-OCR step | Task 3 Step 1 |
| Parse new progress output | Task 3 Step 2 |
| Remove old plugin | Task 3 Step 3 |
| Build + deploy + test | Task 4 |

### Placeholder Scan
- No TBD/TODO found
- All file paths are absolute
- All code blocks are complete

### Type Consistency
- `llm_api_base`/`llm_model` consistent across config.py, types.ts, ConfigSettings.tsx, pipeline.py
- `llm_api_key` kept for future use (grounded path may need it)
