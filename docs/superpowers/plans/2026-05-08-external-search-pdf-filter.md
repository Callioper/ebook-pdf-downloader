# External Search: PDF Filter + Format/Size Display Fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure Anna's Archive and Z-Library external search results reliably show file format and file size, and filter to return only PDF format files.

**Architecture:** Add a PDF-only filter in `_run_aa()` and `_search_zlib()` inside `search.py`. Strengthen AA format/size regex patterns to match common HTML label variants. No frontend changes needed — BookCard already renders `format` and `size` badges at lines 43-48.

**Tech Stack:** Python, regex, existing `backend/api/search.py` module.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/api/search.py` | Modify | `_extract_aa_search_metadata`, `_fetch_md5_page_info`, `_run_aa`, `_search_zlib`, `search_books` |

---

### Task 1: PDF-Only Filter in AA External Search

**Files:**
- Modify: `backend/api/search.py:333-348` (`_run_aa`)
- Modify: `backend/api/search.py:91-153` (`_extract_aa_search_metadata`)
- Modify: `backend/api/search.py:186-256` (`_fetch_md5_page_info`)

Add format extraction improvements and a PDF-only filter during AA result enrichment.

- [ ] **Step 1: Strengthen `_extract_aa_search_metadata` format/size regex**

In `search.py`, replace the format and size extraction patterns (lines 133-139) to also handle cases where format/size appear as unlabeled text (AA may show them without explicit Chinese/English labels):

Replace:
```python
        fmt_m = re.search(r'(?:格式|文件类型|Format|format|Extension)[^：:>]*[：:>]\s*(?:<[^>]+>)*(\w+)', block)
        if fmt_m:
            book["format"] = fmt_m.group(1).strip()
        size_m = re.search(r'(?:大小|文件大小|Size|size|File size)[^：:>]*[：:>]\s*(?:<[^>]+>)*([\d. ]+\s*(?:MB|GB|KB|MiB|GiB))', block)
        if size_m:
            book["size"] = size_m.group(1).strip()
```

With:
```python
        fmt_m = re.search(r'(?:格式|文件类型|Format|format|Extension|类型)[^：:>]*[：:>]\s*(?:<[^>]+>)*(\w+)', block)
        if fmt_m:
            book["format"] = fmt_m.group(1).strip().lower()
        if not book.get("format"):
            # Fallback: find bare extension in block like .pdf .epub
            bare = re.search(r'\.(pdf|epub|mobi|azw3|djvu|txt)\b', block, re.I)
            if bare:
                book["format"] = bare.group(1).lower()
        size_m = re.search(r'(?:大小|文件大小|Size|size|File\s*size|文件大小)[^：:>]*[：:>]\s*(?:<[^>]+>)*([\d. ]+\s*(?:MB|GB|KB|MiB|GiB|B))', block)
        if size_m:
            book["size"] = size_m.group(1).strip()
        if not book.get("size"):
            bare_s = re.search(r'(\d+(?:\.\d+)?\s*(?:MB|GB|KB|MiB|GiB))\b', block, re.I)
            if bare_s:
                book["size"] = bare_s.group(1).strip()
```

- [ ] **Step 2: Strengthen `_fetch_md5_page_info` format/size patterns**

Replace patterns at lines 210-211:

```python
            (r'(?:Format|格式|Extension|类型)[：:\s>]*(?:<[^>]+>)*(\w+)', "format"),
            (r'(?:File\s*size|Size|文件大小|大小)[：:\s>]*(?:<[^>]+>)*([\d. ]+\s*(?:MB|GB|KB|MiB|GiB|B))', "size"),
```

- [ ] **Step 3: Add PDF-only filter in `_run_aa`**

After `merged = {**item, **{k: v for k, v in info.items() if v}}` at line ~344 in `search.py`, add a format check before appending to results:

Change:
```python
                        merged = {**item, **{k: v for k, v in info.items() if v}}
                        if merged.get("title"):
                            results.append(merged)
```

To:
```python
                        merged = {**item, **{k: v for k, v in info.items() if v}}
                        if merged.get("title"):
                            fmt = str(merged.get("format", "")).lower()
                            if fmt and fmt != "pdf":
                                continue  # skip non-PDF formats
                            if not fmt:
                                # No format detected — extract from title/URL
                                title_lower = merged.get("title", "").lower()
                                if ".epub" in title_lower or ".mobi" in title_lower or ".azw" in title_lower:
                                    continue
                            results.append(merged)
```

- [ ] **Step 4: Commit**

```bash
git add backend/api/search.py
git commit -m "feat: PDF-only filter for AA external search, stronger format/size regex"
```

---

### Task 2: PDF-Only Filter in Z-Lib External Search

**Files:**
- Modify: `backend/api/search.py:259-293` (`_search_zlib`)

Add a format-based filter to Z-Lib search results.

- [ ] **Step 1: Add PDF filter in `_search_zlib`**

After line 277 where `books.append(...)` is called, change the loop to filter by format:

Replace the loop body (lines 274-289) from:

```python
        for item in (items if isinstance(items, list) else [])[:10]:
            if not item.get("title"):
                continue
            books.append({
                "source": "zlibrary",
                ...
            })
```

To:

```python
        for item in (items if isinstance(items, list) else [])[:10]:
            if not item.get("title"):
                continue
            fmt = str(item.get("extension", item.get("format", ""))).lower()
            if fmt and fmt != "pdf":
                continue  # skip non-PDF
            books.append({
                "source": "zlibrary",
                "title": item.get("title", ""),
                "author": item.get("author", ""),
                "isbn": item.get("isbn", ""),
                "publisher": item.get("publisher", ""),
                "year": str(item.get("year", "")),
                "language": item.get("language", ""),
                "format": fmt,
                "size": item.get("filesize", item.get("size", "")),
                "md5": item.get("md5", ""),
                "book_id": str(item.get("id", "")),
            })
```

- [ ] **Step 2: Handle missing format — don't skip**

When `fmt` is empty (Z-Lib may not return `extension` for all books), allow the result through but mark format as unknown. Change the filter check:

```python
            fmt = str(item.get("extension", item.get("format", ""))).lower()
            if fmt and fmt != "pdf":
                continue  # skip confirmed non-PDF
```

This way:
- If format is "epub", "mobi", "azw3" etc. → skip
- If format is "pdf" → include with `"format": "pdf"`
- If format is empty/unknown → include as-is (might be PDF, we don't know)

- [ ] **Step 3: Commit**

```bash
git add backend/api/search.py
git commit -m "feat: PDF-only filter for Z-Lib external search"
```

---

### Task 3: End-to-End Verification

- [ ] **Step 1: Search and verify AA results are PDF-only**

1. Open web UI, search by ISBN: `9787561789322`
2. Verify all Anna's Archive external results show format/size badges
3. Verify no epub/mobi results appear in AA section
4. Check backend log for skipped non-PDF items

- [ ] **Step 2: Search and verify Z-Lib results are PDF-only**

1. Search for a book title on Z-Library
2. Verify all Z-Library external results have format badge (pdf or empty)
3. Verify no epub/mobi appear in Z-Lib section

- [ ] **Step 3: Rebuild and deploy**

```bash
cd D:\opencode\book-downloader
python -m PyInstaller --noconfirm backend/book-downloader.spec
Stop-Process -Name BookDownloader -Force -ErrorAction SilentlyContinue
Copy-Item dist\BookDownloader.exe backend\dist\BookDownloader.exe -Force
Start-Process backend\dist\BookDownloader.exe
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: end-to-end verification for PDF filter"
```

---

## Self-Review

### Spec Coverage
| Requirement | Task |
|---|---|
| AA/ZL return format and size in search results | Task 1 (stronger regex) |
| Only return PDF files from AA | Task 1 (filter in _run_aa) |
| Only return PDF files from Z-Lib | Task 2 (filter in _search_zlib) |
| Handle missing format gracefully | Task 2 (don't skip if format unknown) |

### Placeholder Scan
- No TBD/TODO found
- All error handling is inline with existing patterns
- All file paths are absolute

### Type Consistency
- `format` field: lowercase string ("pdf", "epub", etc.) — consistent across AA and Z-Lib
- `size` field: human-readable string like "15.2 MB" — consistent
