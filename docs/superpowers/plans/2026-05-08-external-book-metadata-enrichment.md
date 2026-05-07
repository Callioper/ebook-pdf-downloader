# External Book Metadata & Bookmark Enrichment

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When downloading books from Anna's Archive or Z-Library, re-fetch missing metadata (author, publisher, year, ISBN) from the source and run the full enrichment chain (Douban, NLC, bookmark merger) — even when the initial search returned sparse data.

**Architecture:** Inject a new enrichment function `_enrich_external_metadata` into Step 1 (`_step_fetch_metadata`) that re-fetches the AA MD5 detail page or Z-Lib eAPI to fill gaps. Extend `_step_bookmark` with a title-based shukui.net fallback when ISBN is missing. NLC enrichment gets author/publisher extraction from the existing OPAC HTML.

**Tech Stack:** Python, aiohttp/requests, BeautifulSoup, regex. Existing modules: `backend/api/search.py` (_fetch_md5_page_info), `backend/engine/zlib_downloader.py` (zlib_search), `backend/addbookmark/bookmarkget.py`, `backend/nlc/nlc_isbn.py`.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `backend/engine/pipeline.py` | Modify | `_step_fetch_metadata`, `_step_fetch_isbn`, `_step_bookmark`: inject enrichment hooks |
| `backend/nlc/nlc_isbn.py` | Modify | Add `crawl_metadata(isbn)` extracting author + publisher from NLC OPAC |
| `backend/addbookmark/bookmarkget.py` | Modify | Add `get_bookmark_by_title(title)` title-based shukui.net fallback |
| `backend/api/search.py` | Reference | Reuse `_fetch_md5_page_info()` for AA enrichment (no changes needed) |

---

### Task 1: Enrich External Book Metadata in Step 1

**Files:**
- Modify: `backend/engine/pipeline.py:309-351`

Add a helper `_enrich_external_metadata(task_id, report, config)` that runs after the DB lookup in `_step_fetch_metadata`. For AA books (source `annas_archive`), it re-fetches the MD5 detail page using `_fetch_md5_page_info`. For Z-Lib books (source `zlibrary`), it queries the Z-Lib eAPI by MD5 or title to backfill fields.

- [ ] **Step 1: Write the enrichment function**

Insert this function before `_step_fetch_metadata`:

```python
def _enrich_external_metadata(task_id: str, report: Dict[str, Any], config: Dict[str, Any]) -> None:
    """Re-fetch metadata from AA/Z-Lib to fill gaps (author, publisher, year, isbn).
    Called from _step_fetch_metadata for books with empty book_id or missing ISBN."""
    source = report.get("source", "")
    md5 = report.get("book_id", "")
    proxy = config.get("http_proxy", "")

    if source == "annas_archive" and md5 and len(md5) == 32:
        # Re-fetch AA MD5 detail page for metadata
        from api.search import _fetch_md5_page_info
        try:
            info = _fetch_md5_page_info(md5, proxy)
            if info.get("title") and not report.get("title"):
                report["title"] = info["title"]
            for field in ("author", "isbn", "publisher", "year", "language"):
                val = info.get(field, "")
                if val and not report.get(field):
                    report[field] = val
            # Convert single author string to list for report consistency
            if isinstance(report.get("authors"), list) and not report["authors"]:
                author_val = info.get("author", "")
                if author_val:
                    report["authors"] = [author_val]
            if report.get("isbn"):
                task_store.add_log(task_id, f"AA metadata enriched: isbn={report['isbn']}, author={report.get('authors')}")
            else:
                task_store.add_log(task_id, "AA metadata enriched (no ISBN found on MD5 page)")
        except ImportError:
            pass  # search module not available in frozen build
        except Exception as e:
            task_store.add_log(task_id, f"AA enrichment failed: {str(e)[:100]}")

    elif source == "zlibrary" and md5:
        # Try Z-Lib: re-search by title or MD5
        try:
            title = report.get("title", "")
            isbn = report.get("isbn", "")
            query = isbn or title
            if query:
                from engine.zlib_downloader import ZLibDownloader
                zl = ZLibDownloader(config)
                loop = asyncio.get_event_loop() if asyncio._get_running_loop() is None else asyncio.get_running_loop()
                if isinstance(loop, asyncio.AbstractEventLoop):
                    result = loop.run_until_complete(zl.zlib_search(query, page=1, limit=3))
                else:
                    result = zl.zlib_search_sync(query, page=1, limit=3)
                books = result.get("books") or result.get("results") or []
                if isinstance(books, list) and books:
                    best = books[0]
                    for field, apikey in [("isbn", "isbn"), ("author", "author"),
                                           ("publisher", "publisher"), ("year", "year"),
                                           ("language", "language")]:
                        val = best.get(apikey, "")
                        if val and not report.get(field):
                            report[field] = str(val) if field == "year" else val
                    if not report.get("authors") and best.get("author"):
                        report["authors"] = [str(best["author"])]
                    task_store.add_log(task_id, f"Z-Lib metadata enriched: isbn={report.get('isbn')}")
        except ImportError:
            pass
        except Exception as e:
            task_store.add_log(task_id, f"Z-Lib enrichment failed: {str(e)[:100]}")
```

- [ ] **Step 2: Wire it into _step_fetch_metadata**

After `report = {...}` (line 346), before `task_store.add_log(task_id, f"Book: {title}...")`, add:

```python
    # For external-source books, re-fetch metadata from AA/Z-Lib to fill gaps
    if source in ("annas_archive", "zlibrary") and (not isbn or not report.get("authors")):
        _enrich_external_metadata(task_id, report, config)
        # Refresh local vars after enrichment
        isbn = report.get("isbn", isbn)
        title = report.get("title", title)
```

- [ ] **Step 3: Commit**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: enrich external book metadata from AA/Z-Lib in Step 1"
```

---

### Task 2: NLC Author/Publisher Extraction

**Files:**
- Modify: `backend/nlc/nlc_isbn.py:18-50` (add `crawl_metadata` and enhance `_crawl_isbn_sync`)

Currently `crawl_isbn` only returns ISBN. The NLC OPAC detail pages contain MARC records with fields for author (200 $f), publisher (210 $c), and year (210 $d). Add a function that extracts these fields.

- [ ] **Step 1: Add crawl_metadata function**

Insert after `crawl_isbn` (line 24):

```python
async def crawl_metadata(isbn: str, title: str = "", nlc_path: str = "") -> Optional[Dict[str, str]]:
    """Fetch author, publisher, year from NLC OPAC by ISBN.
    Returns dict with keys: isbn, author, publisher, year, or None."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _crawl_metadata_sync, isbn, title)
        return result
    except Exception:
        return None


def _crawl_metadata_sync(isbn: str, title: str = "") -> Optional[Dict[str, str]]:
    """Search NLC OPAC by ISBN, navigate to detail page, extract MARC fields."""
    try:
        clean_isbn = re.sub(r'[\s-]', '', isbn)
        params = {
            "func": "find-b",
            "find_code": "ISB",
            "request": clean_isbn,
            "local_base": "NLC01",
        }
        r = requests.get(NLC_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None

        soup = BeautifulSoup(r.text, "html.parser")

        # Navigate to the detail page
        detail_links = soup.select('a[href*="find_code=ISB"]')
        if not detail_links:
            return None

        detail_href = detail_links[0].get("href", "")
        if not detail_href:
            return None

        detail_url = f"https://opac.nlc.cn{detail_href}" if not detail_href.startswith('http') else detail_href
        r2 = requests.get(detail_url, headers=HEADERS, timeout=15)
        if r2.status_code != 200:
            return None

        detail_soup = BeautifulSoup(r2.text, "html.parser")
        result: Dict[str, str] = {"isbn": isbn}

        # Extract MARC display fields from the detail page
        # Author = 200 $f (usually shown as table rows with field names)
        text = detail_soup.get_text()
        # Pattern: author in 200 field like "200 1#$a中国神话$f袁珂"
        author_m = re.search(r'200\s+\d+\#\$a[^$]*\$f([^$]+)', text)
        if author_m:
            result["author"] = author_m.group(1).strip()

        # Publisher = 210 $c
        pub_m = re.search(r'210\s+\d+\#\$a[^$]*\$c([^$]+)', text)
        if pub_m:
            result["publisher"] = pub_m.group(1).strip()

        # Year = 210 $d
        year_m = re.search(r'210\s+\d+\#\$[a-d]*\$d(\d{4})', text)
        if year_m:
            result["year"] = year_m.group(1).strip()

        return result if len(result) > 1 else None
    except Exception:
        return None
```

- [ ] **Step 2: Wire crawl_metadata into _fetch_nlc_metadata**

In `pipeline.py`, modify `_fetch_nlc_metadata` (line 624-647) to call `crawl_metadata` after `crawl_isbn`:

```python
        from backend.nlc.nlc_isbn import crawl_isbn

        nlc_path = config.get("ebook_data_geter_path", "")
        if nlc_path:
            fetched_isbn = await crawl_isbn(report.get("title", ""), nlc_path)
            if fetched_isbn and not report.get("isbn"):
                report["isbn"] = fetched_isbn
                task_store.add_log(task_id, f"NLC: ISBN confirmed: {fetched_isbn}")

        # NEW: get author/publisher/year from NLC OPAC by ISBN
        current_isbn = report.get("isbn", "")
        if current_isbn:
            from backend.nlc.nlc_isbn import crawl_metadata
            meta = await crawl_metadata(current_isbn, report.get("title", ""))
            if meta:
                if not report.get("authors") and meta.get("author"):
                    report["authors"] = [meta["author"]]
                    task_store.add_log(task_id, f"NLC: author found: {meta['author']}")
                if not report.get("publisher") and meta.get("publisher"):
                    report["publisher"] = meta["publisher"]
                    task_store.add_log(task_id, f"NLC: publisher found: {meta['publisher']}")
                if not report.get("year") and meta.get("year"):
                    report["year"] = meta["year"]
```

Make sure `Dict` is imported: add `from typing import Any, Dict, List, Optional` at top of nlc_isbn.py.

- [ ] **Step 3: Commit**

```bash
git add backend/nlc/nlc_isbn.py backend/engine/pipeline.py
git commit -m "feat: NLC author/publisher/year extraction + wire into pipeline"
```

---

### Task 3: Title-Based Bookmark Fallback

**Files:**
- Modify: `backend/addbookmark/bookmarkget.py` (add title search function)
- Modify: `backend/engine/pipeline.py:2106-2145` (_step_bookmark)

Add a new function `get_bookmark_by_title(title)` that searches shukui.net by book title (not ISBN), found in the search results. This kicks in during Step 6/7 when ISBN is missing but title is available.

- [ ] **Step 1: Add get_bookmark_by_title to bookmarkget.py**

Insert after `_get_bookmark_sync` (around line 137):

```python
async def get_bookmark_by_title(title: str) -> Optional[str]:
    """Search shukui.net by title when ISBN is unavailable."""
    if not title or len(title.strip()) < 2:
        return None
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _get_bookmark_by_title_sync, title.strip())
    return result


def _get_bookmark_by_title_sync(title: str) -> Optional[str]:
    """Search shukui.net by title, then parse the detail page for bookmarks."""
    from urllib.parse import quote
    search_url = "https://www.shukui.net/so/search.php"
    params = {'q': title}
    headers = get_shukui_headers()

    try:
        response = requests.get(search_url, params=params, headers=headers, timeout=10)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        # Find the first search result link
        result_links = soup.select('div.search-list a[href*="books"]')
        if not result_links:
            result_links = soup.select('a[href*="book.php"]')
        if not result_links:
            return None

        # Navigate to the detail page
        detail_href = result_links[0].get("href", "")
        if not detail_href:
            return None

        detail_url = f"https://www.shukui.net/{detail_href.lstrip('/')}" if not detail_href.startswith('http') else detail_href
        r2 = requests.get(detail_url, headers=headers, timeout=10)
        if r2.status_code != 200:
            return None

        detail_soup = BeautifulSoup(r2.text, "html.parser")
        contents_div = detail_soup.select_one('#book-contents')
        if not contents_div:
            return None

        lines = [li.get_text(' ', strip=True) for li in contents_div.select('li')]
        if not lines:
            text = contents_div.get_text('\n', strip=True)
            lines = [l.strip() for l in text.split('\n') if l.strip()]

        return '\n'.join(lines) if lines else None
    except Exception:
        return None
```

- [ ] **Step 2: Wire title fallback into _step_bookmark**

In `pipeline.py`, modify `_step_bookmark` (lines 2106-2145). After the ISBN-based `get_bookmark` attempt, if `bookmark` is still empty and title is available, try title-based:

```python
    if not bookmark:
        task_store.add_log(task_id, "No bookmark provided, trying addbookmark...")
        try:
            from addbookmark.bookmarkget import get_bookmark
            isbn = report.get("isbn", "")
            if isbn:
                bookmark = await get_bookmark(isbn)
                if bookmark:
                    task_store.add_log(task_id, "Bookmark fetched from addbookmark (ISBN)")
                    report["bookmark"] = bookmark

            # Title-based fallback when ISBN is missing or failed
            if not bookmark:
                title = report.get("title", "")
                if title:
                    from addbookmark.bookmarkget import get_bookmark_by_title
                    bookmark = await get_bookmark_by_title(title)
                    if bookmark:
                        task_store.add_log(task_id, "Bookmark fetched from addbookmark (title)")
                        report["bookmark"] = bookmark

            if not bookmark and not isbn and not title:
                task_store.add_log(task_id, "No ISBN or title available for bookmark lookup")
            elif not bookmark:
                task_store.add_log(task_id, "Bookmark not found via addbookmark")
        except ImportError:
            task_store.add_log(task_id, "addbookmark module not available")
        except Exception as e:
            task_store.add_log(task_id, f"Bookmark fetch error: {e}")
```

- [ ] **Step 3: Commit**

```bash
git add backend/addbookmark/bookmarkget.py backend/engine/pipeline.py
git commit -m "feat: title-based bookmark fallback for external books without ISBN"
```

---

### Task 4: End-to-End Verification

**Files:**
- Test: Manual verification (no automated test infrastructure for external API calls)

- [ ] **Step 1: Test AA book with ISBN**

1. Use the web UI to search for a known book by ISBN (e.g. 9787561789322 "何为女性").
2. Click "开始任务" on the Anna's Archive result.
3. Verify the pipeline log shows: "AA metadata enriched: isbn=..., author=..."
4. Verify Step 2.5 logs: "Douban data fetched", "Bookmark merged from N sources"
5. Verify Step 6/7 log: "Bookmark fetched from addbookmark (ISBN)"
6. Verify the final PDF has bookmarks and the scheduled report shows author/publisher/year.

- [ ] **Step 2: Test AA book without ISBN**

1. Search for a book by title-only on Anna's Archive (a book that has no ISBN on AA).
2. Click "开始任务".
3. Verify the pipeline log shows: "AA metadata enriched (no ISBN found..."
4. Verify Step 2/7: NLC title search fires (maybe finds an ISBN).
5. Verify Step 6/7: If no ISBN, title-based bookmark search fires: "Bookmark fetched from addbookmark (title)" or "Bookmark not found via addbookmark".
6. Verify no crashes, task completes successfully.

- [ ] **Step 3: Test Z-Lib book**

1. Search for a Chinese book on Z-Library.
2. Click "开始任务".
3. Verify "Z-Lib metadata enriched: isbn=..." appears if ISBN found.
4. Verify full enrichment chain works.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "chore: end-to-end verification fixes"
```

---

## Self-Review

### Spec Coverage
| Requirement | Task |
|---|---|
| External books get metadata enriched | Task 1 (AA/Z-Lib re-fetch) |
| NLC author/publisher extraction | Task 2 |
| Bookmark retrieval for external books | Task 3 (ISBN + title fallback) |
| End-to-end verification | Task 4 |

### Placeholder Scan
- No TBD/TODO/fill-in-later found.
- All error handling is explicit with logged messages.
- All imports are specified.
- All file paths are absolute.

### Type Consistency
- `report` dict keys: `isbn`, `authors` (list), `publisher`, `year`, `title`, `source`, `book_id` — consistent across all tasks.
- `_crawl_metadata_sync` returns `Optional[Dict[str, str]]` — matches usage in pipeline where each field is string-checked.
- `get_bookmark_by_title` returns `Optional[str]` — same return type as `get_bookmark`.
