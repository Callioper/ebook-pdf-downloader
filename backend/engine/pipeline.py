# ==== pipeline.py ====
# 职责：书籍下载处理流水线，协调元数据获取、下载、转换、OCR和书签
# 入口函数：run_pipeline()
# 依赖：config, task_store, ws_manager, engine.flaresolverr, engine.zlib_downloader, nlc.nlc_isbn
# 注意：7步流水线，支持取消和错误处理

import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from config import get_config
from task_store import task_store, STATUS_COMPLETED, STATUS_RUNNING, STATUS_CANCELLED, STATUS_FAILED
from ws_manager import ws_manager

PIPELINE_STEPS = [
    "fetch_metadata",
    "fetch_isbn",
    "download_pages",
    "convert_pdf",
    "ocr",
    "bookmark",
    "finalize",
]


async def _emit(task_id: str, event_type: str, data: Dict[str, Any]):
    await ws_manager.broadcast_task(task_id, {
        "type": event_type,
        "task_id": task_id,
        **data,
    })


async def _step_fetch_metadata(task_id: str, task: Dict[str, Any], config: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    task_store.add_log(task_id, "Step 1/7: Fetching metadata from database...")
    await _emit(task_id, "step_progress", {"step": "fetch_metadata", "progress": 50})

    book_id = task.get("book_id", "")
    title = task.get("title", "")
    source = task.get("source", "DX_6.0")

    # If book_id is empty but ISBN is known, look up the local DB for the real book_id
    isbn = task.get("isbn", "")
    if not book_id and isbn:
        try:
            from search_engine import SearchEngine
            se = SearchEngine()
            se.set_db_dir(config.get("ebook_db_path", ""))
            result = se.search(field="isbn", query=isbn, page=1, page_size=1)
            books = result.get("books", [])
            if books:
                book_id = books[0].get("book_id", "")
                if not book_id:
                    book_id = books[0].get("id", "")
                # Fill in missing metadata from DB
                if not title:
                    title = books[0].get("title", "")
                source = books[0].get("source", source)
                task_store.add_log(task_id, f"Found book in database: ID={book_id}")
        except Exception as e:
            task_store.add_log(task_id, f"Database lookup failed: {e}")

    report = {
        "book_id": book_id,
        "title": title,
        "source": source,
        "ss_code": task.get("ss_code", ""),
        "isbn": isbn,
        "authors": task.get("authors", []),
        "publisher": task.get("publisher", ""),
    }

    task_store.add_log(task_id, f"Book: {title} (ID: {book_id})")
    await _emit(task_id, "step_progress", {"step": "fetch_metadata", "progress": 100})

    return report


async def _step_fetch_isbn(task_id: str, task: Dict[str, Any], config: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Step 2/7: 获取图书元数据和书签

    三种路径（根据输入类型自动选择）:
      1. SS码模式: 直接用 SS码查 EbookDatabase（最准确）
      2. 书名模式: 提取主标题 → fuzzy EbookDatabase
      3. ISBN模式: 精确匹配 EbookDatabase → 未命中时 NLC fallback candidate

    共享补全逻辑: EbookDatabase 为主 → NLC 补全(作者/出版社/年/内容提要) → 书葵网书签
    """
    task_store.add_log(task_id, "Step 2/7: Fetching book metadata & bookmark...")
    await _emit(task_id, "step_progress", {"step": "fetch_isbn", "progress": 0})

    ss_code = report.get("ss_code", "")
    title = report.get("title", "")
    isbn = report.get("isbn", "")
    db_path = config.get("ebook_db_path", "")

    book_from_db = None

    # ═══════════════ Phase 1: 主搜索 ═══════════════

    # Path A: SS码模式 — 优先，最准确
    if ss_code and not book_from_db:
        task_store.add_log(task_id, f"Path: SS code mode — searching by SS={ss_code}")
        await _emit(task_id, "step_progress", {"step": "fetch_isbn", "progress": 20})
        book_from_db = _search_db_by_ss(ss_code, db_path)
        if book_from_db:
            task_store.add_log(task_id, f"Found in DB via SS code: {book_from_db.get('title', '')}")
            # Merge DB data into report
            _merge_db_book(book_from_db, report)

    # Path B: 书名模式 — 提取主标题后 fuzzy 搜索
    if not book_from_db and title:
        main_title = _extract_main_title(title)
        if main_title != title:
            task_store.add_log(task_id, f"Path: Title mode — main title: '{main_title}'")
        else:
            task_store.add_log(task_id, "Path: Title mode — searching DB by title")
        await _emit(task_id, "step_progress", {"step": "fetch_isbn", "progress": 30})
        book_from_db = _search_db_by_title(main_title, db_path)
        if book_from_db:
            task_store.add_log(task_id, f"Found in DB via title: {book_from_db.get('title', '')}")
            _merge_db_book(book_from_db, report)
        else:
            task_store.add_log(task_id, f"No DB match for title '{main_title}', will use NLC")

    # Path C: ISBN模式 — 精确匹配 EbookDatabase
    if not book_from_db and isbn:
        task_store.add_log(task_id, f"Path: ISBN mode — searching DB by ISBN={isbn}")
        await _emit(task_id, "step_progress", {"step": "fetch_isbn", "progress": 40})
        book_from_db = _search_db_by_isbn(isbn, db_path)
        if book_from_db:
            task_store.add_log(task_id, f"Found in DB via ISBN: {book_from_db.get('title', '')}")
            _merge_db_book(book_from_db, report)
        else:
            task_store.add_log(task_id, f"No DB match for ISBN {isbn}, creating NLC fallback candidate")
            # ISBN fallback: 标记 _fallback=True (无 SS码，步骤3只能走 AA MD5 搜索)
            report["_fallback"] = True

    # ═══════════════ Phase 2: NLC 补全 ═══════════════

    await _emit(task_id, "step_progress", {"step": "fetch_isbn", "progress": 60})

    # 如果有 ISBN 且缺少元数据，从 NLC 补全
    if report.get("isbn"):
        missing = []
        if not report.get("authors"):
            missing.append("authors")
        if not report.get("publisher"):
            missing.append("publisher")
        if missing:
            await _fetch_nlc_metadata(task_id, report, config)

    # ═══════════════ Phase 3: 书葵网书签 ═══════════════
    # （书签获取在 Step 6 通过 NLC/SS码 处理，不使用 ISBN）
    await _emit(task_id, "step_progress", {"step": "fetch_isbn", "progress": 80})

    # 记录完成状态并回写到 task_store（只补全非空字段，不覆盖已有数据）
    update_fields = {}
    for key in ("title", "isbn", "publisher", "ss_code", "book_id"):
        val = report.get(key)
        if val:
            update_fields[key] = val if isinstance(val, str) else str(val)
    if report.get("authors"):
        update_fields["authors"] = report.get("authors", [])
    task_store.update(task_id, update_fields)

    await _emit(task_id, "step_progress", {"step": "fetch_isbn", "progress": 100})
    task_store.add_log(task_id, "Step 2/7: metadata & bookmark fetch complete")
    return report


# ═══════════════════════════ 辅助函数 ═══════════════════════════


def _extract_main_title(title: str) -> str:
    """
    提取主标题，去除副标题分隔符。
    分隔符: ：:  —— --- － ( ) （ ）【 】［ ］
    """
    import re
    if not title:
        return ""
    # 常见副标题分隔符（从前往后分割）
    for sep in ["：", ":", "　", "——", "---", "－", "—", "‧", "•"]:
        idx = title.find(sep)
        if idx > 0 and idx < len(title) - 1:
            candidate = title[:idx].strip()
            if len(candidate) >= 2:  # 主标题至少2字
                return candidate
    # 去掉括号内的副标题
    title = re.sub(r'[（(][^）)]*[）)]', '', title).strip()
    return title


def _search_db_by_ss(ss_code: str, db_path: str) -> Optional[Dict[str, Any]]:
    """通过 SS 码搜索 EbookDatabase"""
    try:
        from search_engine import SearchEngine
        se = SearchEngine()
        se.set_db_dir(db_path)
        result = se.search(field="ss_code", query=ss_code, page=1, page_size=1)
        books = result.get("books", [])
        if books:
            return books[0]
    except Exception as e:
        logger.warning(f"DB search by SS failed: {e}")
    return None


def _search_db_by_title(title: str, db_path: str) -> Optional[Dict[str, Any]]:
    """通过书名 fuzzy 搜索 EbookDatabase"""
    try:
        from search_engine import SearchEngine
        se = SearchEngine()
        se.set_db_dir(db_path)
        result = se.search(field="title", query=title, page=1, page_size=5)
        books = result.get("books", [])
        # 选标题最匹配的
        if books:
            best = books[0]
            for book in books[1:]:
                if _title_similarity(book.get("title", ""), title) > _title_similarity(best.get("title", ""), title):
                    best = book
            return best
    except Exception as e:
        logger.warning(f"DB search by title failed: {e}")
    return None


def _search_db_by_isbn(isbn: str, db_path: str) -> Optional[Dict[str, Any]]:
    """通过 ISBN 精确搜索 EbookDatabase"""
    try:
        from search_engine import SearchEngine
        se = SearchEngine()
        se.set_db_dir(db_path)
        clean_isbn = isbn.replace("-", "").replace(" ", "")
        result = se.search(field="isbn", query=clean_isbn, page=1, page_size=1)
        books = result.get("books", [])
        if books:
            return books[0]
        # Try partial match
        result = se.search(field="isbn", query=isbn, page=1, page_size=3)
        for b in result.get("books", []):
            db_isbn = b.get("isbn", "").replace("-", "").replace(" ", "")
            if clean_isbn == db_isbn or clean_isbn in db_isbn or db_isbn in clean_isbn:
                return b
    except Exception as e:
        logger.warning(f"DB search by ISBN failed: {e}")
    return None


def _title_similarity(a: str, b: str) -> float:
    """简单标题相似度（字符重叠率）"""
    if not a or not b:
        return 0
    a_chars = set(a.lower())
    b_chars = set(b.lower())
    overlap = len(a_chars & b_chars)
    return overlap / max(len(a_chars), len(b_chars), 1)


def _merge_db_book(book: Dict[str, Any], report: Dict[str, Any]):
    """将 EbookDatabase 的数据合并到 report 中，不覆盖已有值"""
    fields = {
        "book_id": ("book_id", "id"),
        "title": ("title",),
        "isbn": ("isbn",),
        "ss_code": ("ss_code",),
        "authors": ("author", "authors"),
        "publisher": ("publisher",),
    }
    for report_key, db_keys in fields.items():
        if report.get(report_key):
            continue
        for db_key in db_keys:
            val = book.get(db_key, "")
            if val:
                if isinstance(val, str) and val.strip():
                    report[report_key] = val.strip()
                    break
                elif not isinstance(val, str) and val:
                    report[report_key] = val
                    break

    # second_pass_code 不是真实 MD5，不能给 stacks 使用
    second_pass = book.get("second_pass_code", "")
    if second_pass and not report.get("_second_pass_code"):
        report["_second_pass_code"] = second_pass
        logger.debug(f"Stored second_pass_code for {report.get('book_id', '?')}")


async def _fetch_nlc_metadata(task_id: str, report: Dict[str, Any], config: Dict[str, Any]):
    """从 NLC 国家图书馆补全作者/出版社/出版年/内容提要/主题词"""
    isbn = report.get("isbn", "")
    if not isbn:
        return

    task_store.add_log(task_id, f"NLC: fetching metadata for ISBN={isbn}")
    try:
        from backend.nlc.nlc_isbn import crawl_isbn

        nlc_path = config.get("ebook_data_geter_path", "")
        if nlc_path:
            # crawl_isbn 目前只返回 ISBN，这里可以根据需要扩展
            fetched_isbn = await crawl_isbn(report.get("title", ""), nlc_path)
            if fetched_isbn and not report.get("isbn"):
                report["isbn"] = fetched_isbn
                task_store.add_log(task_id, f"NLC: ISBN confirmed: {fetched_isbn}")

        # NLC API 可以直接补全作者/出版社/年/内容提要/主题词
        # 目前 nlc_isbn 模块只实现了 ISBN 查询，后续可扩展
    except ImportError:
        task_store.add_log(task_id, "NLC: module not available")
    except Exception as e:
        task_store.add_log(task_id, f"NLC: error: {str(e)[:100]}")


async def _get_page_with_flare(url: str, proxy: str = "", timeout: int = 30) -> Optional[str]:
    """Fetch a web page, trying FlareSolverr first (for Cloudflare bypass), then direct."""
    try:
        from engine.flaresolverr import get_page_content
        result = await get_page_content(url, proxy)
        if result:
            return result
    except ImportError:
        pass
    # Direct fallback
    import requests as _req
    try:
        h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        kwargs = {"timeout": timeout, "headers": h, "verify": False}
        if proxy:
            kwargs["proxies"] = {"http": proxy, "https": proxy}
        r = _req.get(url, **kwargs)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


async def _download_via_aa_and_stacks(
    task_id: str, config: Dict[str, Any], report: Dict[str, Any],
    ss_code: str, isbn: str, title: str, proxy: str,
) -> Optional[str]:
    """
    Anna's Archive 搜索 → 提取MD5 → stacks下载 → 直接兜底
    返回下载文件路径，失败返回None
    """
    tmp_dir = report.get("tmp_dir", "")
    if not tmp_dir:
        return None

    # Step A: 搜索 AA 获取所有 MD5 条目
    search_queries = []
    if ss_code:
        search_queries.append(("SS", ss_code))
    if isbn:
        search_queries.append(("ISBN", isbn))
    if title and not search_queries:
        search_queries.append(("title", title))

    from engine.aa_downloader import search_aa, get_md5_details, get_stacks_api_key, _calc_title_relevance, verify_md5, resolve_download_url

    all_md5_entries = []
    for qtype, qval in search_queries:
        task_store.add_log(task_id, f"AA: searching by {qtype}={qval}")
        entries = await search_aa(qval, proxy)
        if entries:
            task_store.add_log(task_id, f"AA: found {len(entries)} MD5 entries via {qtype}")
            all_md5_entries.extend(entries)
            if len(all_md5_entries) >= 5:
                break
        await asyncio.sleep(1)

    if not all_md5_entries:
        task_store.add_log(task_id, "AA: no MD5 entries found for any search query")
        return None

    # 去重（按MD5）
    seen = set()
    deduped = []
    for e in all_md5_entries:
        if e["md5"] not in seen:
            seen.add(e["md5"])
            deduped.append(e)
    all_md5_entries = deduped
    task_store.add_log(task_id, f"AA: {len(all_md5_entries)} unique MD5 entries to try")

    # Step B: 尝试 stacks 下载（优先 — 仅当 Docker 服务运行）
    # （stacks 是 Anna's Archive 下载管理器，与 FlareSolverr 不同）
    stacks_api_key = config.get("stacks_api_key", "") or get_stacks_api_key()
    stacks_url = config.get("stacks_base_url", "http://localhost:7788")
    stacks_timeout = config.get("stacks_timeout", 300)
    use_stacks = bool(stacks_api_key)

    # 即使没有 API key，也尝试检测 stacks 是否运行
    if not use_stacks:
        try:
            import requests as _req
            hc = _req.get(f"{stacks_url}/api/health", timeout=3)
            if hc.status_code < 500:
                use_stacks = True
                task_store.add_log(task_id, f"AA: stacks detected at {stacks_url} (no API key, limited endpoints)")
        except Exception:
            task_store.add_log(task_id, f"AA: stacks not reachable at {stacks_url} — will fall back to FlareSolverr+CDN")

    if use_stacks:
        task_store.add_log(task_id, f"AA: stacks {'configured' if stacks_api_key else 'reachable'} ({stacks_url})")

        # Step C: 遍历 MD5 尝试下载
        for i, entry in enumerate(all_md5_entries[:10]):
            md5 = entry["md5"]
            task_store.add_log(task_id, f"AA [{i+1}/{min(len(all_md5_entries), 10)}]: trying MD5={md5}")

            # 获取 MD5 详情（zlib_id, title, isbn 等）
            details = await get_md5_details(md5, proxy)
            filesize_bytes = details.get("filesize_bytes", entry.get("size_bytes", 0))
            md5_title = details.get("title", "")

            # 匹配 MD5 详情中的标题/ISBN 与 Step1 元数据
            if title or isbn:
                skip = False
                if md5_title and title:
                    rel_score = _calc_title_relevance(md5_title, title)
                    if rel_score < 10:
                        task_store.add_log(task_id, f"AA: MD5 {md5} title mismatch ('{md5_title[:30]}' vs '{title[:30]}', score={rel_score}), skipping")
                        skip = True
                if not skip and isbn and details.get("isbn"):
                    if isbn.replace("-", "") != details["isbn"].replace("-", ""):
                        task_store.add_log(task_id, f"AA: MD5 {md5} ISBN mismatch ({details['isbn']} vs {isbn}), skipping")
                        skip = True
                if skip:
                    continue
                if md5_title:
                    task_store.add_log(task_id, f"AA: MD5 {md5} title matched ('{md5_title[:30]}')")

            # 唯一下载路径: stacks（参考代码做法—不用直连/FlareSolverr）
            # stacks 不可用或失败时直接返回 None，走 ZL 降级
            if use_stacks:
                task_store.add_log(task_id, f"AA: submitting MD5 to stacks...")
                try:
                    from engine.stacks_client import StacksClient
                    sc = StacksClient(base_url=stacks_url, api_key=str(stacks_api_key or ""))
                    result = await sc.add_task(md5)
                    if result.get("ok"):
                        filepath = await sc.wait_for_download(md5, timeout=stacks_timeout)
                        if filepath:
                            fixed = sc.validate_and_fix_file(filepath, tmp_dir)
                            if fixed:
                                task_store.add_log(task_id, f"AA: stacks download OK → {os.path.basename(fixed)}")
                                if verify_md5(fixed, md5):
                                    return fixed
                                else:
                                    task_store.add_log(task_id, f"AA: MD5 mismatch for stacks download")
                    else:
                        err = result.get("error", "")
                        task_store.add_log(task_id, f"AA: stacks add_task fail (401): {err}")
                        task_store.add_log(task_id, "💡 打开 http://localhost:7788 → Settings → Authentication → 复制 Admin API Key → 填入设置页 stacks API Key")
                        task_store.add_log(task_id, "💡 默认账号密码: admin / stacks（首次启动时设置）")
                except ImportError:
                    task_store.add_log(task_id, "AA: stacks_client module not available")
                except Exception as e:
                    task_store.add_log(task_id, f"AA: stacks error: {str(e)[:100]}")

            # stacks 不可用或失败 → FlareSolverr 兜底下载
            # 通过 FlareSolverr session 获取 /d/{md5} 的 CDN 重定向 URL
            try:
                from engine.flaresolverr import _get_flare_port
                port = _get_flare_port(config)
                task_store.add_log(task_id, f"AA: trying FlareSolverr direct download (port {port})...")
                fs_url = await resolve_download_url(md5, proxy)
                if fs_url and "annas-archive" not in fs_url.lower():
                    task_store.add_log(task_id, f"AA: CDN URL from FlareSolverr: {fs_url[:80]}")
                    import requests as _req
                    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                    fs_resp = _req.get(fs_url, headers=hdrs, timeout=120, verify=False, stream=True)
                    if fs_resp.status_code == 200:
                        cd = fs_resp.headers.get("Content-Disposition", "")
                        fname = f"{md5}.pdf"
                        if cd and "filename=" in cd:
                            fname = cd.split("filename=")[-1].strip("\"' ")
                        fpath = os.path.join(tmp_dir, fname)
                        with open(fpath, "wb") as f:
                            for chunk in fs_resp.iter_content(65536):
                                if chunk:
                                    f.write(chunk)
                        if os.path.getsize(fpath) > 1024:
                            with open(fpath, "rb") as fh:
                                if fh.read(4) == b"%PDF" and verify_md5(fpath, md5):
                                    task_store.add_log(task_id, f"AA: FlareSolverr download OK")
                                    return fpath
                            os.remove(fpath)
            except Exception as e:
                task_store.add_log(task_id, f"AA: FlareSolverr download failed: {str(e)[:100]}")

            # 只试第一个 MD5
            break

        return None


async def _download_via_libgen(
    task_id: str, report: Dict[str, Any], config: Dict[str, Any],
    title: str, isbn: str, authors: List[str], proxy: str,
) -> Optional[str]:
    """LibGen 兜底下载（所有其他方式失败后的最后选择）"""
    task_store.add_log(task_id, "LibGen: trying as last resort...")
    try:
        import libgen_api_enhanced as lg
        from libgen_api_enhanced import LibgenSearch
        searcher = LibgenSearch()
    except ImportError:
        task_store.add_log(task_id, "LibGen: libgen-api-enhanced not installed")
        return None

    tmp_dir = report.get("tmp_dir", "")
    if not tmp_dir:
        return None

    try:
        filters = {}
        search_term = ""
        try:
            if isbn:
                search_term = isbn
                filters["search_in"] = "identifier"
            elif title:
                search_term = title
                if authors:
                    search_term = f"{title} {authors[0]}"
        except TypeError:
            pass

        if not search_term:
            return None

        results = searcher.search(search_term, search_type="title")
        if not results or not isinstance(results, list):
            task_store.add_log(task_id, "LibGen: no results found")
            return None

        task_store.add_log(task_id, f"LibGen: found {len(results)} results")
        for item in results[:5]:
            try:
                md5 = item.get("md5", item.get("Mirror_MD5", ""))
                if md5:
                    dl_urls = item.get("mirrors", item.get("Mirrors", []))
                    if not dl_urls:
                        dl_urls = [item.get("Mirror_1", ""), item.get("Mirror_2", "")]
                    for dl_url in dl_urls:
                        if not dl_url or not dl_url.startswith("http"):
                            continue
                        try:
                            import requests as _req
                            hdrs = {"User-Agent": "Mozilla/5.0"}
                            kwargs = {"timeout": 60, "headers": hdrs, "verify": False}
                            if proxy:
                                kwargs["proxies"] = {"http": proxy, "https": proxy}
                            resp = _req.get(dl_url, **kwargs)
                            if resp.status_code == 200 and len(resp.content) > 1024:
                                ext = item.get("extension", "pdf")
                                filepath = os.path.join(tmp_dir, f"{md5}.{ext}")
                                with open(filepath, "wb") as f:
                                    f.write(resp.content)
                                task_store.add_log(task_id, f"LibGen: downloaded {md5}.{ext} ({len(resp.content)/1024:.0f} KB)")
                                return filepath
                        except Exception:
                            continue
            except Exception:
                continue

        task_store.add_log(task_id, "LibGen: all download attempts failed")
    except Exception as e:
        task_store.add_log(task_id, f"LibGen: error: {str(e)[:100]}")
    return None


async def _wait_for_user_confirmation(
    task_id: str,
    report: Dict[str, Any],
    confirm_key: str = "zl_confirm",
    timeout: int = 300,
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """
    Emit confirmation request to frontend and wait for user response.
    Used for ZL download (consumes quota) and other destructive operations.
    When candidates are provided, user can pick one from the list.
    """
    info = {
        "type": "confirm_download",
        "task_id": task_id,
        "key": confirm_key,
        "title": report.get("title", ""),
        "isbn": report.get("isbn", ""),
        "authors": report.get("authors", []),
        "publisher": report.get("publisher", ""),
        "download_source": report.get("download_source", ""),
        "file_size": report.get("download_path", ""),
    }
    if candidates:
        info["candidates"] = candidates

    task_store.add_log(task_id, f"⏳ Waiting for user confirmation (key={confirm_key})...")
    task_store.update(task_id, {f"_{confirm_key}": None, f"_{confirm_key}_selection": None, "waiting_confirmation": True})
    await ws_manager.broadcast_all(info)

    for _ in range(timeout):
        await asyncio.sleep(1)
        task = task_store.get(task_id)
        if not task:
            return False
        decision = task.get(f"_{confirm_key}")
        if decision is True:
            task_store.update(task_id, {"waiting_confirmation": False})
            return True  # selected book stored in _zl_confirm_selection
        if decision is False:
            task_store.update(task_id, {"waiting_confirmation": False})
            task_store.add_log(task_id, f"⏭️ User declined {confirm_key}")
            return False
        if task.get("status") == "cancelled":
            return False

    task_store.add_log(task_id, f"⏰ Confirmation timeout ({timeout}s), skipping")
    task_store.update(task_id, {"waiting_confirmation": False})
    return False


async def _step_download_pages(task_id: str, task: Dict[str, Any], config: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    """
    Step 3/7: Download book PDF — 多级降级策略
    本地检索 → Anna's Archive(stacks优先→直接兜底) → Z-Library(三层检索) → LibGen兜底
    """
    task_store.add_log(task_id, "Step 3/7: Downloading book PDF...")
    await _emit(task_id, "step_progress", {"step": "download_pages", "progress": 0})

    # 准备临时目录
    tmp_dir = config.get("tmp_dir", "")
    if tmp_dir:
        task_tmp = os.path.join(tmp_dir, task_id)
        os.makedirs(task_tmp, exist_ok=True)
        report["tmp_dir"] = task_tmp
    else:
        report["tmp_dir"] = os.path.join(os.path.dirname(__file__), "tmp", task_id)
        os.makedirs(report["tmp_dir"], exist_ok=True)

    ss_code = report.get("ss_code", "")
    isbn = report.get("isbn", "")
    proxy = config.get("http_proxy", "")
    title = report.get("title", "")
    authors = report.get("authors", [])
    downloaded = False
    download_source = ""

    # ── 本地检索：检查是否已存在 ──
    finished_dir = config.get("finished_dir", "")
    if finished_dir and title:
        safe_title = title.replace("/", "_").replace("\\", "_")
        for ext in (".pdf", ".epub", ".mobi"):
            existing = os.path.join(finished_dir, f"{safe_title}{ext}")
            if os.path.exists(existing) and os.path.getsize(existing) > 1024:
                task_store.add_log(task_id, f"Book already downloaded: {os.path.basename(existing)}")
                report["download_path"] = existing
                report["download_source"] = "local_cache"
                await _emit(task_id, "step_progress", {"step": "download_pages", "progress": 100})
                return report

    # ── 确保 FlareSolverr 运行（供 AA 访问） ──
    await _emit(task_id, "step_progress", {"step": "download_pages", "progress": 5})
    try:
        from engine.flaresolverr import check_flaresolverr, start_flaresolverr, set_flare_port
        set_flare_port(int(config.get("flaresolverr_port", 8191)))
        if not await check_flaresolverr(config):
            task_store.add_log(task_id, "Starting FlareSolverr for AA access...")
            started, msg = await start_flaresolverr(config)
            if started:
                task_store.add_log(task_id, "FlareSolverr started")
            else:
                task_store.add_log(task_id, f"FlareSolverr: {msg}")
                # 继续尝试（AA直接请求可能仍有效）
    except ImportError:
        task_store.add_log(task_id, "FlareSolverr module not available")
    except Exception as e:
        task_store.add_log(task_id, f"FlareSolverr check: {e}")

    # ── 路径A：Anna's Archive → stacks/MD5 → 直接下载 ──
    task_store.add_log(task_id, "=== Path A: Anna's Archive ===")
    await _emit(task_id, "step_progress", {"step": "download_pages", "progress": 10})

    aa_result = await _download_via_aa_and_stacks(
        task_id, config, report, ss_code, isbn, title, proxy,
    )
    if aa_result:
        downloaded = True
        download_source = "annas_archive"
        report["download_path"] = aa_result

    # ── 路径B：Z-Library 三层检索 ──
    if not downloaded:
        task_store.add_log(task_id, "=== Path B: Z-Library ===")
        await _emit(task_id, "step_progress", {"step": "download_pages", "progress": 50})

        zlib_email = config.get("zlib_email", "")
        zlib_password = config.get("zlib_password", "")
        if zlib_email and zlib_password:
            try:
                from engine.zlib_downloader import ZLibDownloader
                dl = ZLibDownloader(config)

                # 先登录获取配额信息
                login_result = await dl.zlib_login()
                if login_result.get("ok"):
                    task_store.add_log(task_id, "ZL: logged in")
                    balance = login_result.get("balance", "")
                    if balance:
                        task_store.add_log(task_id, f"ZL: {balance}")

                    # 搜索全部候选条目（不做标题过滤，返回所有结果让用户选）
                    candidates = await dl.zlib_search_candidates(
                        isbn=isbn, title=title, authors=authors,
                    )
                    if candidates:
                        task_store.add_log(task_id, f"ZL: found {len(candidates)} candidates, requesting user selection...")
                        confirmed = await _wait_for_user_confirmation(
                            task_id, report, "zl_confirm", 300, candidates,
                        )
                        if confirmed:
                            # 读取用户选择的书籍
                            task = task_store.get(task_id)
                            selection = task.get("_zl_confirm_selection", {})
                            sel_id = selection.get("id", "")
                            sel_hash = selection.get("hash", "")
                            if sel_id and sel_hash:
                                task_store.add_log(task_id, f"ZL: user selected book {sel_id}")
                                # 用书名做文件名（参考代码做法）
                                sel_title = selection.get("title", "")
                                if not sel_title:
                                    sel_title = report.get("title", "")
                                zl_path = await dl.zlib_download_verified(
                                    sel_id, sel_hash, report["tmp_dir"],
                                    filename=sel_title,
                                )
                                if zl_path:
                                    task_store.add_log(task_id, f"ZL: downloaded {os.path.basename(zl_path)}")
                                    downloaded = True
                                    download_source = "zlibrary"
                                    report["download_path"] = zl_path
                                else:
                                    task_store.add_log(task_id, "ZL: download verification failed")
                            else:
                                task_store.add_log(task_id, "ZL: no book selected by user")
                        else:
                            task_store.add_log(task_id, "ZL: user declined, skipping")
                    else:
                        task_store.add_log(task_id, "ZL: no candidates found on Z-Library")
                else:
                    task_store.add_log(task_id, f"ZL: login failed — {login_result.get('message', 'unknown')}")
            except ImportError:
                task_store.add_log(task_id, "ZL: module not available")
            except Exception as e:
                task_store.add_log(task_id, f"ZL: error: {str(e)[:150]}")
        else:
            task_store.add_log(task_id, "ZL: no credentials configured, skipping")

    # ── 路径C：LibGen 兜底 ──
    if not downloaded and config.get("libgen_enabled", True):
        task_store.add_log(task_id, "=== Path C: LibGen (last resort) ===")
        await _emit(task_id, "step_progress", {"step": "download_pages", "progress": 80})

        libgen_path = await _download_via_libgen(
            task_id, report, config, title, isbn, authors, proxy,
        )
        if libgen_path:
            downloaded = True
            download_source = "libgen"
            report["download_path"] = libgen_path

    # ── 结果 ──
    if downloaded:
        report["download_source"] = download_source
        task_store.add_log(task_id, f"Download complete via {download_source}: {os.path.basename(report['download_path'])}")
    else:
        task_store.add_log(task_id, "All download paths (AA/stacks → ZL → LibGen) exhausted — download failed")
        report["download_note"] = "download failed"

    await _emit(task_id, "step_progress", {"step": "download_pages", "progress": 100})
    return report


async def _step_convert_pdf(task_id: str, task: Dict[str, Any], config: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    task_store.add_log(task_id, "Step 4/7: Converting pages to PDF...")
    await _emit(task_id, "step_progress", {"step": "convert_pdf", "progress": 0})

    tmp_dir = report.get("tmp_dir", "")
    output_dir = config.get("download_dir", "")
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    title = report.get("title", "book").replace("/", "_").replace("\\", "_")
    pdf_name = f"{title}.pdf"
    pdf_path = os.path.join(output_dir, pdf_name) if output_dir else os.path.join(tmp_dir, pdf_name)

    await _emit(task_id, "step_progress", {"step": "convert_pdf", "progress": 30})

    try:
        image_files = []
        if tmp_dir and os.path.exists(tmp_dir):
            for ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
                image_files.extend(sorted(Path(tmp_dir).glob(f"*{ext}")))
                image_files.extend(sorted(Path(tmp_dir).glob(f"*{ext.upper()}")))

        if image_files:
            task_store.add_log(task_id, f"Found {len(image_files)} images, converting to PDF...")
            await _emit(task_id, "step_progress", {"step": "convert_pdf", "progress": 50})

            try:
                import fitz
                doc = fitz.open()
                for img_file in image_files:
                    try:
                        img = fitz.open(str(img_file))
                        rect = img[0].rect
                        page = doc.new_page(width=rect.width, height=rect.height)
                        page.insert_image(rect, filename=str(img_file))
                        img.close()
                    except Exception:
                        page = doc.new_page()
                        page.insert_image(page.rect, filename=str(img_file))
                doc.save(pdf_path)
                doc.close()
                task_store.add_log(task_id, f"PDF created: {pdf_path}")
            except ImportError:
                task_store.add_log(task_id, "PyMuPDF not available, trying img2pdf...")
                import img2pdf
                with open(pdf_path, "wb") as f:
                    data = img2pdf.convert([str(p) for p in image_files])
                    if data:
                        f.write(data)
                task_store.add_log(task_id, f"PDF created via img2pdf: {pdf_path}")

            report["pdf_path"] = pdf_path
            report["page_count"] = len(image_files)
        else:
            task_store.add_log(task_id, "No image files found in tmp dir, checking for existing PDF...")
            pdf_files = list(Path(tmp_dir).glob("*.pdf")) if tmp_dir else []
            if pdf_files:
                from_path = str(pdf_files[0])
                task_store.add_log(task_id, f"Found PDF: {from_path}")
                # 复制到 download_dir（设置中的下载目录）
                out_dir = config.get("download_dir", "")
                if out_dir:
                    os.makedirs(out_dir, exist_ok=True)
                    ss_code = report.get("ss_code", "")
                    safe_title = re.sub(r'[<>:"/\\|?*]', '_', report.get("title", "book")).strip()[:80]
                    ext = os.path.splitext(from_path)[1] or ".pdf"
                    new_name = f"{ss_code}_{safe_title}{ext}" if ss_code else f"{safe_title}{ext}"
                    dest_path = os.path.join(out_dir, new_name)
                    shutil.copy2(from_path, dest_path)
                    report["pdf_path"] = dest_path
                    task_store.add_log(task_id, f"PDF copied to download dir: {dest_path}")
                else:
                    report["pdf_path"] = from_path
            else:
                task_store.add_log(task_id, "No images or PDF found to convert")
                await _emit(task_id, "step_progress", {"step": "convert_pdf", "progress": 100})
                return report
    except Exception as e:
        task_store.add_log(task_id, f"PDF conversion error: {e}")

    await _emit(task_id, "step_progress", {"step": "convert_pdf", "progress": 100})
    return report


def _is_scanned(pdf_path: str, sample_pages: int = 5) -> bool:
    """判断PDF是否为扫描件（文字占比低），返回True=需要OCR"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        blank = 0
        for i in range(min(sample_pages, len(doc))):
            text = doc[i].get_text()
            non_ws = sum(1 for c in text if c.strip())
            if len(text) == 0 or non_ws < len(text) * 0.6:
                blank += 1
        doc.close()
        return blank >= sample_pages * 0.6
    except ImportError:
        return True
    except Exception:
        return True


def _is_ocr_readable(pdf_path: str, sample_pages: int = 5, min_cjk_ratio: float = 0.15) -> bool:
    """检测OCR后的PDF文字层是否为可读中文（非乱码），CJK比率>=15%"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        total = doc.page_count
        indices = [int(total * i / (sample_pages + 1)) for i in range(1, sample_pages + 1)]
        readable = 0
        for idx in indices:
            text = doc[idx].get_text()
            if not text.strip():
                continue
            total_chars = sum(1 for c in text if not c.isspace())
            cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf' or '\uf900' <= c <= '\ufaff')
            ratio = cjk / total_chars if total_chars > 0 else 0
            if ratio >= min_cjk_ratio:
                readable += 1
        doc.close()
        return readable >= sample_pages * 0.6
    except ImportError:
        return True  # 无法验证时假设通过
    except Exception:
        return True


async def _step_ocr(task_id: str, task: Dict[str, Any], config: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    task_store.add_log(task_id, "Step 5/7: Running OCR...")
    await _emit(task_id, "step_progress", {"step": "ocr", "progress": 0})

    ocr_enabled = config.get("ocr_jobs", 0) > 0
    if not ocr_enabled:
        task_store.add_log(task_id, "OCR disabled in config, skipping")
        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
        return report

    pdf_path = report.get("pdf_path", "")
    if not pdf_path or not os.path.exists(pdf_path):
        task_store.add_log(task_id, "No PDF to OCR")
        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
        return report

    ocr_engine = config.get("ocr_engine", "tesseract")
    ocr_lang = config.get("ocr_languages", "chi_sim+eng")
    ocr_jobs = config.get("ocr_jobs", 4)
    ocr_timeout = config.get("ocr_timeout", 7200)

    task_store.add_log(task_id, f"OCR engine: {ocr_engine}, languages: {ocr_lang}, jobs: {ocr_jobs}")

    try:
        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 10})

        if ocr_engine == "tesseract":
            task_store.add_log(task_id, "Running OCRmyPDF with Tesseract...")
            output_pdf = pdf_path.replace(".pdf", "_ocr.pdf")
            cmd = [
                "ocrmypdf",
                "-l", ocr_lang,
                "-j", str(ocr_jobs),
                "--output-type", "pdf",
                pdf_path,
                output_pdf,
            ]
            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 30})

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=ocr_timeout)
                if proc.returncode == 0:
                    os.replace(output_pdf, pdf_path)
                    task_store.add_log(task_id, "OCR completed successfully")
                    report["ocr_done"] = True
                else:
                    task_store.add_log(task_id, f"OCR failed: {stderr.decode()}")
            except asyncio.TimeoutError:
                proc.kill()
                task_store.add_log(task_id, f"OCR timed out after {ocr_timeout}s")
        elif ocr_engine == "paddleocr":
            task_store.add_log(task_id, "Running OCRmyPDF with PaddleOCR...")
            
            # 1. Check if PDF already has text layer
            if not _is_scanned(pdf_path):
                task_store.add_log(task_id, "PDF already has text layer, skipping OCR")
                report["ocr_done"] = True
                await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
                return report

            output_pdf = pdf_path.replace(".pdf", "_ocr.pdf")
            cmd = [
                "ocrmypdf",
                "--plugin", "ocrmypdf_paddleocr",
                "-l", ocr_lang or "chi_sim+eng",
                "-j", "1",  # PaddleOCR thread safety
                "--output-type", "pdf",
                "--mode", "force",
                pdf_path,
                output_pdf,
            ]

            await _emit(task_id, "step_progress", {"step": "ocr", "progress": 30})
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=ocr_timeout)
                if proc.returncode == 0:
                    task_store.add_log(task_id, "OCR completed, validating quality...")
                    if _is_ocr_readable(output_pdf):
                        os.replace(output_pdf, pdf_path)
                        task_store.add_log(task_id, "OCR quality check passed")
                        report["ocr_done"] = True
                    else:
                        task_store.add_log(task_id, "OCR quality check failed (possible garbled text), keeping original PDF")
                        try:
                            os.remove(output_pdf)
                        except Exception:
                            pass
                else:
                    err = stderr.decode()[:500] if stderr else "unknown error"
                    task_store.add_log(task_id, f"PaddleOCR failed: {err}")
            except asyncio.TimeoutError:
                proc.kill()
                task_store.add_log(task_id, f"PaddleOCR timed out after {ocr_timeout}s")

        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
    except FileNotFoundError:
        task_store.add_log(task_id, "ocrmypdf not found in PATH — 请安装: pip install ocrmypdf, 或见设置页→OCR→安装指引")
    except Exception as e:
        task_store.add_log(task_id, f"OCR error: {e}")

    # PDF compression (qpdf, optional)
    if report.get("ocr_done") and config.get("pdf_compress", False):
        if report.get("pdf_path") and os.path.exists(report["pdf_path"]):
            task_store.add_log(task_id, "Compressing PDF with qpdf...")
            try:
                qpdf_cmd = [
                    "qpdf",
                    "--recompress-flate",
                    "--object-streams=generate",
                    report["pdf_path"],
                    report["pdf_path"] + ".compressed",
                ]
                qp = await asyncio.create_subprocess_exec(
                    *qpdf_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, qe = await asyncio.wait_for(qp.communicate(), timeout=300)
                if qp.returncode == 0:
                    before = os.path.getsize(report["pdf_path"])
                    after = os.path.getsize(report["pdf_path"] + ".compressed")
                    os.replace(report["pdf_path"] + ".compressed", report["pdf_path"])
                    task_store.add_log(task_id, f"qpdf compression: {before/1024/1024:.1f}MB → {after/1024/1024:.1f}MB ({after*100//before}%)")
                else:
                    err = qe.decode()[:200] if qe else "unknown"
                    task_store.add_log(task_id, f"qpdf compression skipped: {err}")
                    try:
                        os.remove(report["pdf_path"] + ".compressed")
                    except Exception:
                        pass
            except FileNotFoundError:
                task_store.add_log(task_id, "qpdf not installed, skipping compression")
            except asyncio.TimeoutError:
                task_store.add_log(task_id, "qpdf compression timed out")
            except Exception as e:
                task_store.add_log(task_id, f"qpdf compression error: {str(e)[:100]}")

    return report


async def _step_bookmark(task_id: str, task: Dict[str, Any], config: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    task_store.add_log(task_id, "Step 6/7: Processing bookmarks/TOC...")
    await _emit(task_id, "step_progress", {"step": "bookmark", "progress": 0})

    bookmark = task.get("bookmark", "")
    pdf_path = report.get("pdf_path", "")

    if not bookmark:
        task_store.add_log(task_id, "No bookmark provided, trying shukui.net (by ISBN)...")
        try:
            from backend.nlc.bookmarkget import get_bookmark
            isbn = report.get("isbn", "")
            if isbn:
                bookmark = await get_bookmark(isbn)
                if bookmark:
                    task_store.add_log(task_id, "Bookmark fetched from shukui.net")
                    report["bookmark"] = bookmark
                else:
                    task_store.add_log(task_id, "Bookmark not found on shukui.net")
            else:
                task_store.add_log(task_id, "No ISBN available for bookmark lookup")
        except ImportError:
            task_store.add_log(task_id, "NLC bookmark module not available")
        except Exception as e:
            task_store.add_log(task_id, f"Bookmark fetch error: {e}")

    if bookmark and pdf_path and os.path.exists(pdf_path):
        task_store.add_log(task_id, "Applying bookmark to PDF...")
        try:
            from backend.nlc.bookmarkget import apply_bookmark_to_pdf
            await apply_bookmark_to_pdf(pdf_path, bookmark)
            task_store.add_log(task_id, "Bookmark applied to PDF")
            report["bookmark_applied"] = True
        except ImportError:
            task_store.add_log(task_id, "Bookmark PDF module not available")
        except Exception as e:
            task_store.add_log(task_id, f"Bookmark apply error: {e}")

    await _emit(task_id, "step_progress", {"step": "bookmark", "progress": 100})
    return report


async def _step_finalize(task_id: str, task: Dict[str, Any], config: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    task_store.add_log(task_id, "Step 7/7: Finalizing...")
    await _emit(task_id, "step_progress", {"step": "finalize", "progress": 0})

    pdf_path = report.get("pdf_path", "")
    download_dir = config.get("download_dir", "")
    finished_dir = config.get("finished_dir", "")

    if pdf_path and os.path.exists(pdf_path):
        # 确定目标目录：优先 download_dir，其次 finished_dir
        target_dir = download_dir or finished_dir
        if target_dir:
            try:
                os.makedirs(target_dir, exist_ok=True)
                ext = os.path.splitext(pdf_path)[1] or ".pdf"
                # 文件名格式: SSID_书名.扩展名
                ss_code = report.get("ss_code", "")
                title = report.get("title", "book")
                safe_title = re.sub(r'[<>:"/\\|?*]', '_', title).strip()[:80]
                if ss_code:
                    new_name = f"{ss_code}_{safe_title}{ext}"
                else:
                    new_name = f"{safe_title}{ext}"
                dest_pdf = os.path.join(target_dir, new_name)
                if os.path.abspath(pdf_path) != os.path.abspath(dest_pdf):
                    shutil.move(pdf_path, dest_pdf)
                    report["pdf_path"] = dest_pdf
                    task_store.add_log(task_id, f"PDF saved: {dest_pdf}")
                task_store.add_log(task_id, f"任务输出: {dest_pdf}")
            except Exception as e:
                task_store.add_log(task_id, f"Finalize move error: {e}")

    tmp_dir = report.get("tmp_dir", "")
    if tmp_dir and os.path.exists(tmp_dir):
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            task_store.add_log(task_id, "Temporary files cleaned up")
        except Exception:
            pass

    report["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    task_store.add_log(task_id, "Task completed successfully!")

    await _emit(task_id, "step_progress", {"step": "finalize", "progress": 100})
    return report


async def run_pipeline(task_id: str):
    config = get_config()
    task = task_store.get(task_id)
    if not task:
        return

    task_status = task.get("status")
    if task_status == STATUS_CANCELLED:
        return

    task_store.update(task_id, {"status": STATUS_RUNNING, "current_step": "fetch_metadata"})
    await _emit(task_id, "task_started", {"task_id": task_id})

    # Log current settings at pipeline start
    db_path = config.get("ebook_db_path", "") or "未设置"
    proxy = config.get("http_proxy", "") or "无"
    ocr_engine = config.get("ocr_engine", "tesseract")
    ocr_langs = config.get("ocr_languages", "chi_sim+eng")
    ocr_jobs = config.get("ocr_jobs", 1)
    ocr_timeout = config.get("ocr_timeout", 1800)
    task_store.add_log(task_id, f"⚙ 数据库: {db_path} | 代理: {proxy}")
    task_store.add_log(task_id, f"⚙ OCR引擎: {ocr_engine} | 语言: {ocr_langs} | 线程: {ocr_jobs} | 超时: {ocr_timeout}s")
    # Log download source from task
    source = task.get("source", "未知")
    task_store.add_log(task_id, f"⚙ 下载源: {source}")

    report = {}

    try:
        for step_idx, step_name in enumerate(PIPELINE_STEPS):
            task = task_store.get(task_id)
            if not task or task.get("status") == STATUS_CANCELLED:
                task_store.add_log(task_id, "Task cancelled")
                task_store.update(task_id, {"status": STATUS_CANCELLED})
                await _emit(task_id, "task_update", {
                    "task_id": task_id,
                    "status": STATUS_CANCELLED,
                })
                return

            task_store.update(task_id, {"current_step": step_name, "progress": int((step_idx / 7) * 100)})

            step_func = {
                "fetch_metadata": _step_fetch_metadata,
                "fetch_isbn": _step_fetch_isbn,
                "download_pages": _step_download_pages,
                "convert_pdf": _step_convert_pdf,
                "ocr": _step_ocr,
                "bookmark": _step_bookmark,
                "finalize": _step_finalize,
            }.get(step_name)

            if step_func:
                report = await step_func(task_id, task, config, report)
                if report is None:
                    report = {}

            task_store.update(task_id, {"report": report, "progress": int(((step_idx + 1) / 7) * 100)})
            await _emit(task_id, "task_update", {
                "task_id": task_id,
                "current_step": step_name,
                "progress": int(((step_idx + 1) / 7) * 100),
            })

            await asyncio.sleep(0.1)

        task_store.update(task_id, {
            "status": STATUS_COMPLETED,
            "progress": 100,
            "report": report,
        })
        await _emit(task_id, "task_completed", {"task_id": task_id})

    except Exception as e:
        import traceback
        error_msg = f"{e}\n{traceback.format_exc()}"
        task_store.add_log(task_id, f"Pipeline error: {e}")
        task_store.update(task_id, {
            "status": STATUS_FAILED,
            "error": str(e),
            "report": report,
        })
        await _emit(task_id, "task_failed", {"task_id": task_id, "error": str(e)})
