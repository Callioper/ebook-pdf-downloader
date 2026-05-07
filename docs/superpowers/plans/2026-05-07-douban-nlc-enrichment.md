# Douban + NLC TOC Enhancement Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Douban book page and NLC detail page as additional metadata + TOC/bookmark sources, enriching task reports with description, rating, tags, and alternate bookmark text.

**Architecture:** New `backend/book_sources/douban.py` scrapes book.douban.com for metadata+TOC. Extend existing `backend/nlc/nlc_isbn.py` to also extract TOC from MARC records. Pipeline Step 2 calls both, merges into report.

**Tech Stack:** requests, BeautifulSoup, re

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/book_sources/__init__.py` | 创建 | 包标记 |
| `backend/book_sources/douban.py` | 创建 | 豆瓣爬虫：元数据 + 目录 |
| `backend/nlc/nlc_isbn.py` | 修改 | 添加 `crawl_toc()` 提取 NLC 目录 |
| `backend/engine/pipeline.py` | 修改 | Step 2 调用新源并合并 |
| `backend/book-downloader.spec` | 修改 | 添加 book_sources 到 datas |
| `frontend/src/components/TaskReport.tsx` | 修改 | 显示 enriched metadata |

---

### Task 1: NLC TOC 增强 — 从 NLC 书目详情提取目录

**Files:**
- Modify: `D:\opencode\book-downloader\backend\nlc\nlc_isbn.py`

NLC 详情页的 MARC 记录字段 `330` 或 `327` 包含目录信息。添加 `crawl_toc(isbn)` 函数。

- [ ] **Step 1: 添加 `crawl_toc_sync` 同步函数**

在文件末尾（`return None` 之前）添加：

```python
def crawl_toc_sync(isbn: str) -> Optional[str]:
    """从 NLC OPAC 获取目录(330/327字段)。"""
    if not isbn:
        return None
    try:
        params = {
            "func": "find-b",
            "find_code": "ISB",
            "request": isbn,
            "local_base": "NLC01",
        }
        r = requests.get(NLC_SEARCH_URL, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        # Follow first detail link
        detail_link = soup.select_one('a[href*="find_code=ISB"]')
        if not detail_link:
            return None
        href = detail_link.get("href", "")
        detail_url = f"http://opac.nlc.cn{href}" if href.startswith("/") else href
        dr = requests.get(detail_url, headers=HEADERS, timeout=10)
        if dr.status_code != 200:
            return None
        dsoup = BeautifulSoup(dr.text, "html.parser")
        # Search for TOC in MARC display
        for td in dsoup.select("td.td1"):
            text = td.get_text(strip=True)
            # MARC field 330 or 327
            if text.startswith("330") or text.startswith("327"):
                toc_td = td.find_next_sibling("td")
                if toc_td:
                    toc_text = toc_td.get_text(strip=True)
                    if toc_text and len(toc_text) > 20:
                        return toc_text
        return None
    except Exception:
        return None


async def crawl_toc(isbn: str) -> Optional[str]:
    """Async wrapper for crawl_toc_sync."""
    try:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, crawl_toc_sync, isbn)
    except Exception:
        return None
```

- [ ] **Step 2: 测试 NLC TOC 获取**

```bash
python -c "
import sys; sys.path.insert(0, r'D:\opencode\book-downloader\backend')
from nlc.nlc_isbn import crawl_toc_sync
result = crawl_toc_sync('9787561789322')
if result:
    print(f'NLC TOC ({len(result)} chars):')
    print(result[:500])
else:
    print('No TOC found')
"
```

- [ ] **Step 3: 提交**

```bash
git add backend/nlc/nlc_isbn.py
git commit -m "feat: add NLC TOC extraction from MARC 330/327 fields"
```

---

### Task 2: 豆瓣爬虫 — 元数据 + 目录获取

**Files:**
- Create: `D:\opencode\book-downloader\backend\book_sources\__init__.py`
- Create: `D:\opencode\book-downloader\backend\book_sources\douban.py`

Douban 书籍页面 URL 格式：`https://book.douban.com/subject/{id}/`
通过 ISBN 搜索定位：`https://www.douban.com/search?cat=1001&q={isbn}`

- [ ] **Step 1: 创建目录和 __init__.py**

```bash
New-Item -ItemType Directory -Path "D:\opencode\book-downloader\backend\book_sources" -Force
New-Item -ItemType File -Path "D:\opencode\book-downloader\backend\book_sources\__init__.py" -Force
```

- [ ] **Step 2: 创建 `douban.py`**

```python
"""Douban book metadata + TOC scraper."""
import re
import requests
from bs4 import BeautifulSoup
from typing import Optional, Dict, Any, List

DOUBAN_SEARCH = "https://www.douban.com/search"
DOUBAN_BOOK = "https://book.douban.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _search_by_isbn(isbn: str) -> Optional[str]:
    """Search Douban by ISBN and return the first book detail URL."""
    params = {"cat": "1001", "q": isbn}
    try:
        r = requests.get(DOUBAN_SEARCH, params=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.nbg"):
            href = a.get("href", "")
            if "book.douban.com/subject/" in href:
                return href
        # Fallback: search result list
        for a in soup.select("div.result-list a[href*='subject']"):
            href = a.get("href", "")
            if "/subject/" in href:
                return href
    except Exception:
        pass
    return None


def _parse_douban_book(html: str) -> Dict[str, Any]:
    """Parse Douban book detail page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    result: Dict[str, Any] = {}

    # Title
    title_el = soup.select_one("span[property='v:itemreviewed']")
    if title_el:
        result["title"] = title_el.get_text(strip=True)

    # Authors
    authors = []
    for a in soup.select("span.pl"):
        text = a.get_text(strip=True)
        if text.startswith("作者"):
            parent = a.find_parent()
            if parent:
                for author_a in parent.select("a"):
                    name = author_a.get_text(strip=True)
                    if name:
                        authors.append(name)
    result["authors"] = authors

    # Publisher
    pub_info = []
    for span in soup.select("span.pl"):
        text = span.get_text(strip=True)
        if any(text.startswith(kw) for kw in ["出版社", "出版年", "ISBN"]):
            tail = _get_tail(span)
            if tail:
                pub_info.append(f"{text}:{tail}")
    result["pub_info"] = pub_info

    # ISBN
    isbn_el = soup.select_one("span.pl:-soup-contains('ISBN')")
    if isbn_el:
        tail = _get_tail(isbn_el)
        if tail and re.search(r'\d{10,13}', tail):
            result["isbn"] = re.search(r'\d{10,13}', tail).group(0)

    # Rating
    rating_el = soup.select_one("strong[property='v:average']")
    if rating_el:
        try:
            result["rating"] = float(rating_el.get_text(strip=True))
        except ValueError:
            pass

    # Description / Intro
    intro_el = soup.select_one("div.intro")
    if intro_el:
        result["description"] = intro_el.get_text(strip=True)[:2000]

    # Tags
    tags = []
    for a in soup.select("a.tag"):
        tag = a.get_text(strip=True)
        if tag:
            tags.append(tag)
    result["tags"] = tags

    # TOC / 目录
    toc = _extract_toc(soup)
    if toc:
        result["toc"] = toc

    return result


def _extract_toc(soup: BeautifulSoup) -> Optional[str]:
    """Extract table of contents from Douban book page."""
    # Method 1: hidden full TOC div
    toc_div = soup.select_one("div#dir_72144_full")
    if not toc_div:
        toc_div = soup.select_one("div.indent div#dir_72144_full")
    if toc_div:
        text = toc_div.get_text(strip=True)
        if text:
            return text

    # Method 2: short TOC display
    for div in soup.select("div.indent"):
        label_span = div.select_one("span.pl")
        if label_span and "目录" in label_span.get_text():
            # Find text nodes after the label
            texts = []
            for child in div.children:
                if hasattr(child, 'get_text'):
                    t = child.get_text(strip=True)
                    if t and "目录" not in t:
                        texts.append(t)
                elif isinstance(child, str):
                    t = child.strip()
                    if t:
                        texts.append(t)
            text = "\n".join(texts)
            if text and len(text) > 10:
                return text[:5000]

    # Method 3: <pre> tag in TOC section
    for pre in soup.select("pre"):
        text = pre.get_text(strip=True)
        if text and ("章" in text or "节" in text or "部分" in text):
            return text[:5000]

    return None


def _get_tail(element) -> str:
    """Get text after an element (next sibling text nodes)."""
    texts = []
    for sibling in element.next_siblings:
        if hasattr(sibling, 'get_text'):
            t = sibling.get_text(strip=True)
            if t:
                texts.append(t)
        elif isinstance(sibling, str):
            t = sibling.strip()
            if t:
                texts.append(t)
    return "".join(texts)


def fetch_douban(isbn: str) -> Optional[Dict[str, Any]]:
    """Fetch Douban book metadata by ISBN. Returns dict or None."""
    if not isbn:
        return None
    try:
        url = _search_by_isbn(isbn)
        if not url:
            return None
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return None
        data = _parse_douban_book(r.text)
        data["url"] = url
        return data if data.get("title") else None
    except Exception:
        return None
```

- [ ] **Step 3: 测试豆瓣抓取**

```bash
python -c "
import sys; sys.path.insert(0, r'D:\opencode\book-downloader\backend')
from book_sources.douban import fetch_douban
result = fetch_douban('9787561789322')
if result:
    print(f'Title: {result.get(\"title\", \"\")}')
    print(f'Authors: {result.get(\"authors\", [])}')
    print(f'Rating: {result.get(\"rating\", \"N/A\")}')
    print(f'Tags: {result.get(\"tags\", [])}')
    print(f'ISBN: {result.get(\"isbn\", \"N/A\")}')
    toc = result.get('toc', '')
    print(f'TOC ({len(toc)} chars): {toc[:300]}')
    desc = result.get('description', '')
    print(f'Description ({len(desc)} chars): {desc[:200]}')
else:
    print('Fetch failed')
"
```

- [ ] **Step 4: 提交**

```bash
git add backend/book_sources/
git commit -m "feat: add Douban book scraper for metadata + TOC"
```

---

### Task 3: Pipeline 集成 — Step 2 调用新源

**Files:**
- Modify: `D:\opencode\book-downloader\backend\engine\pipeline.py`

在 Step 2 完成现有元数据获取后，异步调用 douban + NLC TOC，合并到 report。

- [ ] **Step 1: 添加异步调用**

在 `pipeline.py` 的 `_step_fetch_isbn` 函数末尾（return report 之前），添加：

```python
    # Step 2.5: Enrich metadata from Douban and NLC TOC
    isbn_val = report.get("isbn", "")
    if isbn_val:
        try:
            from book_sources.douban import fetch_douban
            loop = asyncio.get_running_loop()
            douban_data = await loop.run_in_executor(None, fetch_douban, isbn_val)
            if douban_data:
                if douban_data.get("description"):
                    report["description"] = douban_data["description"]
                if douban_data.get("rating"):
                    report["rating"] = douban_data["rating"]
                if douban_data.get("tags"):
                    report["tags"] = douban_data["tags"]
                if douban_data.get("toc") and not bookmark:
                    report["douban_toc"] = douban_data["toc"]
                    task_store.add_log(task_id, "Douban: TOC extracted")
                task_store.add_log(task_id, f"Douban: metadata enriched (rating={douban_data.get('rating', 'N/A')})")
        except ImportError:
            task_store.add_log(task_id, "Douban module not available")
        except Exception as e:
            task_store.add_log(task_id, f"Douban fetch error: {e}")

        try:
            from nlc.nlc_isbn import crawl_toc
            nlc_toc = await crawl_toc(isbn_val)
            if nlc_toc and not bookmark:
                report["nlc_toc"] = nlc_toc
                task_store.add_log(task_id, f"NLC: TOC extracted ({len(nlc_toc)} chars)")
        except ImportError:
            pass
        except Exception as e:
            task_store.add_log(task_id, f"NLC TOC error: {e}")
```

- [ ] **Step 2: 验证语法**

```bash
python -c "import py_compile; py_compile.compile(r'D:\opencode\book-downloader\backend\engine\pipeline.py', doraise=True); print('Syntax OK')"
```

- [ ] **Step 3: 提交**

```bash
git add backend/engine/pipeline.py
git commit -m "feat: integrate Douban + NLC TOC into pipeline step 2 enrichment"
```

---

### Task 4: PyInstaller spec 更新

**Files:**
- Modify: `D:\opencode\book-downloader\backend\book-downloader.spec`

- [ ] **Step 1: 添加 book_sources 目录**

在 spec 的 datas 列表中添加：

```python
(str(BACKEND_DIR / "book_sources"), "book_sources"),
```

- [ ] **Step 2: 提交**

```bash
git add backend/book-downloader.spec
git commit -m "build: include book_sources module in PyInstaller bundle"
```

---

### Task 5: 前端任务报告增强

**Files:**
- Modify: `D:\opencode\book-downloader\frontend\src\components\TaskReport.tsx`

- [ ] **Step 1: 显示 description, rating, tags, douban_toc**

在 TaskReport 中添加新字段展示：

```tsx
{report.description && (
  <div className="mt-2">
    <h4 className="text-xs font-medium text-gray-600">简介</h4>
    <p className="text-xs text-gray-700 mt-0.5 leading-relaxed">{report.description.substring(0, 500)}</p>
  </div>
)}
{report.rating && (
  <div className="mt-1 text-xs text-gray-600">
    豆瓣评分: {report.rating} / 10
  </div>
)}
{report.tags && report.tags.length > 0 && (
  <div className="mt-1 flex flex-wrap gap-1">
    {report.tags.map((t: string, i: number) => (
      <span key={i} className="px-1.5 py-0.5 bg-gray-100 text-gray-600 rounded text-xs">{t}</span>
    ))}
  </div>
)}
{report.douban_toc && (
  <details className="mt-2">
    <summary className="text-xs font-medium text-gray-600 cursor-pointer">豆瓣目录</summary>
    <pre className="mt-1 text-xs text-gray-700 whitespace-pre-wrap bg-gray-50 p-2 rounded max-h-48 overflow-y-auto">{report.douban_toc}</pre>
  </details>
)}
{report.nlc_toc && (
  <details className="mt-2">
    <summary className="text-xs font-medium text-gray-600 cursor-pointer">NLC 目录</summary>
    <pre className="mt-1 text-xs text-gray-700 whitespace-pre-wrap bg-gray-50 p-2 rounded max-h-48 overflow-y-auto">{report.nlc_toc}</pre>
  </details>
)}
```

- [ ] **Step 2: 构建前端**

```bash
cmd /c "npm run build" 2>&1
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/TaskReport.tsx
git commit -m "feat: display Douban/NLC enriched metadata in task report"
```

---

### Task 6: 构建部署 + 端到端测试

- [ ] **Step 1: 构建 exe**

```bash
python -m PyInstaller --noconfirm "D:\opencode\book-downloader\backend\book-downloader.spec" 2>&1 | Select-Object -Last 3
```

- [ ] **Step 2: 部署**

```bash
Stop-Process -Name "BookDownloader" -Force -ErrorAction SilentlyContinue
Start-Sleep 1
Copy-Item "D:\opencode\book-downloader\dist\BookDownloader.exe" "D:\opencode\book-downloader\backend\dist\BookDownloader.exe" -Force
```

- [ ] **Step 3: 端到端测试**

用已知 ISBN 创建任务，观察日志和任务报告：
- Step 2 日志应显示 `Douban: metadata enriched` 和 `NLC: TOC extracted`
- 任务报告应显示简介、评分、标签、目录

- [ ] **Step 4: 提交**

```bash
git add backend/dist/BookDownloader.exe
git commit -m "build: deploy exe with Douban + NLC TOC enrichment"
```
