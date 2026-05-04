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
    task_store.add_log(task_id, "Step 2/7: Fetching ISBN from NLC...")
    await _emit(task_id, "step_progress", {"step": "fetch_isbn", "progress": 0})

    if report.get("isbn"):
        task_store.add_log(task_id, f"ISBN already present: {report['isbn']}")
        await _emit(task_id, "step_progress", {"step": "fetch_isbn", "progress": 100})
        return report

    try:
        from backend.nlc.nlc_isbn import crawl_isbn
        nlc_path = config.get("ebook_data_geter_path", "")
        title = report.get("title", "")
        if title and nlc_path:
            await _emit(task_id, "step_progress", {"step": "fetch_isbn", "progress": 30})
            isbn = await crawl_isbn(title, nlc_path)
            if isbn:
                report["isbn"] = isbn
                task_store.add_log(task_id, f"ISBN fetched: {isbn}")
                task_store.update(task_id, {"isbn": isbn})
            else:
                task_store.add_log(task_id, "ISBN not found on NLC")
    except ImportError:
        task_store.add_log(task_id, "NLC ISBN module not available, skipping")
    except Exception as e:
        task_store.add_log(task_id, f"ISBN fetch error: {e}")

    await _emit(task_id, "step_progress", {"step": "fetch_isbn", "progress": 100})
    return report


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

    from engine.aa_downloader import search_aa, get_md5_details, resolve_download_url, get_stacks_api_key, _calc_title_relevance

    all_md5_entries = []
    for qtype, qval in search_queries:
        task_store.add_log(task_id, f"AA: searching by {qtype}={qval}")
        entries = await search_aa(qval, proxy, preferred_title=title, preferred_isbn=isbn)
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

    # Step B: 尝试 stacks 下载（优先）
    stacks_api_key = config.get("stacks_api_key", "") or get_stacks_api_key()
    stacks_url = config.get("stacks_base_url", "http://localhost:7788")
    stacks_timeout = config.get("stacks_timeout", 300)
    use_stacks = bool(stacks_api_key)

    if use_stacks:
        task_store.add_log(task_id, f"AA: stacks enabled ({stacks_url})")

    # Step C: 遍历 MD5 尝试下载
    for i, entry in enumerate(all_md5_entries[:10]):
        md5 = entry["md5"]
        task_store.add_log(task_id, f"AA [{i+1}/{min(len(all_md5_entries), 10)}]: trying MD5={md5} ({entry.get('size_label', '?')})")

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

        # 路径A: stacks 下载
        if use_stacks:
            task_store.add_log(task_id, f"AA: submitting to stacks...")
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
                            return fixed
                    else:
                        task_store.add_log(task_id, "AA: stacks download timeout/failed")
                else:
                    err = result.get("error", "")
                    if "unreachable" in err.lower() or "connection" in err.lower():
                        task_store.add_log(task_id, "AA: stacks service unreachable, disabling")
                        use_stacks = False
            except ImportError:
                task_store.add_log(task_id, "AA: stacks_client module not available")
                use_stacks = False
            except Exception as e:
                task_store.add_log(task_id, f"AA: stacks error: {e}")

        # 路径B: AA 直接下载（先尝试直连，403 时通过 FlareSolverr cookies 重试）
        task_store.add_log(task_id, f"AA: trying direct download...")
        dl_url = await resolve_download_url(md5, proxy)
        if dl_url:
            task_store.add_log(task_id, f"AA: direct download URL found")

            async def _try_download(url: str, use_flare: bool = False) -> Optional[str]:
                """尝试下载文件，use_flare=True时通过FlareSolverr获取cookies"""
                import requests as _req
                import urllib.parse as _up

                hdrs = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                }
                cookies = {}
                ref = f"https://annas-archive.gd/md5/{md5}"

                if use_flare:
                    task_store.add_log(task_id, "AA: getting FlareSolverr cookies for download...")
                    try:
                        from engine.flaresolverr import download_file_via_flaresolverr
                        fpath = os.path.join(tmp_dir, f"{md5}_fs.pdf")
                        ok = await download_file_via_flaresolverr(url, fpath, proxy, ref)
                        if ok and os.path.getsize(fpath) > 1024:
                            # 验证 %PDF
                            with open(fpath, "rb") as fh:
                                if fh.read(4) == b"%PDF":
                                    task_store.add_log(task_id, f"AA: FlareSolverr download OK ({os.path.getsize(fpath)/1024:.0f} KB)")
                                    return fpath
                            os.remove(fpath)
                    except ImportError:
                        pass
                    except Exception as e:
                        task_store.add_log(task_id, f"AA: FlareSolverr download error: {str(e)[:100]}")
                    return None

                try:
                    dl_kwargs = {"timeout": 120, "headers": hdrs, "verify": False, "stream": True, "cookies": cookies}
                    if proxy:
                        dl_kwargs["proxies"] = {"http": proxy, "https": proxy}
                    resp = _req.get(url, **dl_kwargs)
                    resp.raise_for_status()

                    cd = resp.headers.get("Content-Disposition", "")
                    fname = f"{md5}.pdf"
                    if cd and "filename=" in cd:
                        fname = cd.split("filename=")[-1].strip("\"' ")
                    else:
                        url_path = _up.urlparse(url).path
                        if url_path:
                            fname = os.path.basename(url_path) or fname

                    filepath = os.path.join(tmp_dir, fname)
                    with open(filepath, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                    size = os.path.getsize(filepath)
                    if size > 1024:
                        if fname.lower().endswith(".pdf"):
                            with open(filepath, "rb") as fh:
                                if fh.read(4) != b"%PDF":
                                    task_store.add_log(task_id, f"AA: downloaded file is not valid PDF")
                                    os.remove(filepath)
                                    return None
                        return filepath
                    os.remove(filepath)
                except _req.exceptions.HTTPError as e:
                    if "403" in str(e) or "Forbidden" in str(e):
                        task_store.add_log(task_id, "AA: direct download blocked (403), trying through FlareSolverr...")
                        return None  # Will trigger FlareSolverr retry
                    elif "404" in str(e):
                        return None  # Not found, skip
                    raise
                except Exception as e:
                    task_store.add_log(task_id, f"AA: direct download failed: {str(e)[:100]}")
                return None

            # Attempt 1: direct download
            result = await _try_download(dl_url, use_flare=False)
            # Attempt 2: retry with FlareSolverr cookies if direct failed
            if not result:
                result = await _try_download(dl_url, use_flare=True)
            if result:
                return result

        # 短暂休息避免触发速率限制
        await asyncio.sleep(2)

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
) -> bool:
    """
    Emit confirmation request to frontend and wait for user response.
    Used for ZL download (consumes quota) and other destructive operations.
    """
    # Build book info summary
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

    task_store.add_log(task_id, f"⏳ Waiting for user confirmation (key={confirm_key})...")
    task_store.update(task_id, {f"_{confirm_key}": None, "waiting_confirmation": True})
    # 广播给所有 WebSocket 客户端（非仅任务订阅者）
    await ws_manager.broadcast_all(info)

    # Poll for user response
    for _ in range(timeout):
        await asyncio.sleep(1)
        task = task_store.get(task_id)
        if not task:
            return False
        decision = task.get(f"_{confirm_key}")
        if decision is True:
            task_store.update(task_id, {"waiting_confirmation": False})
            task_store.add_log(task_id, f"✅ User confirmed {confirm_key}")
            return True
        if decision is False:
            task_store.update(task_id, {"waiting_confirmation": False})
            task_store.add_log(task_id, f"⏭️ User declined {confirm_key}")
            return False
        # Check if task was cancelled while waiting
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
        from engine.flaresolverr import check_flaresolverr, start_flaresolverr
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
            # 需要用户确认是否消耗 ZL 额度
            task_store.add_log(task_id, "ZL: requesting user confirmation (will consume download quota)...")
            confirmed = await _wait_for_user_confirmation(task_id, report, "zl_confirm", 300)
            if not confirmed:
                task_store.add_log(task_id, "ZL: user not confirmed, skipping Z-Library")
            else:
                try:
                    from engine.zlib_downloader import ZLibDownloader
                    dl = ZLibDownloader(config)

                    # 登录
                    login_result = await dl.zlib_login()
                    if login_result.get("ok"):
                        task_store.add_log(task_id, "ZL: logged in")
                        balance = login_result.get("balance", "")
                        if balance:
                            task_store.add_log(task_id, f"ZL: {balance}")

                        # 三层检索
                        match = await dl.zlib_search_tiered(
                            isbn=isbn, title=title, authors=authors, expected_size=0,
                        )
                        if match:
                            task_store.add_log(task_id,
                                f"ZL: matched book {match['id']} via {match['strategy']} "
                                f"(tier {match['tier']}, level={match['match_level']})")
                            zl_path = await dl.zlib_download_verified(
                                match["id"], match["hash"], report["tmp_dir"],
                                expected_size=match.get("size", 0),
                            )
                            if zl_path:
                                task_store.add_log(task_id, f"ZL: downloaded {os.path.basename(zl_path)}")
                                downloaded = True
                                download_source = "zlibrary"
                                report["download_path"] = zl_path
                            else:
                                task_store.add_log(task_id, "ZL: download verification failed")
                        else:
                            task_store.add_log(task_id, "ZL: no matching book found in any tier")
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
                pdf_path = str(pdf_files[0])
                task_store.add_log(task_id, f"Using existing PDF: {pdf_path}")
                report["pdf_path"] = pdf_path
            else:
                task_store.add_log(task_id, "No images or PDF found to convert")
                await _emit(task_id, "step_progress", {"step": "convert_pdf", "progress": 100})
                return report
    except Exception as e:
        task_store.add_log(task_id, f"PDF conversion error: {e}")

    await _emit(task_id, "step_progress", {"step": "convert_pdf", "progress": 100})
    return report


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
        else:
            task_store.add_log(task_id, "PaddleOCR selected but not yet implemented in pipeline")

        await _emit(task_id, "step_progress", {"step": "ocr", "progress": 100})
    except FileNotFoundError:
        task_store.add_log(task_id, "ocrmypdf not found in PATH, skipping OCR")
    except Exception as e:
        task_store.add_log(task_id, f"OCR error: {e}")

    return report


async def _step_bookmark(task_id: str, task: Dict[str, Any], config: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    task_store.add_log(task_id, "Step 6/7: Processing bookmarks/TOC...")
    await _emit(task_id, "step_progress", {"step": "bookmark", "progress": 0})

    bookmark = task.get("bookmark", "")
    pdf_path = report.get("pdf_path", "")

    if not bookmark:
        task_store.add_log(task_id, "No bookmark provided, trying NLC bookmark getter...")
        try:
            from backend.nlc.bookmarkget import get_bookmark
            nlc_path = config.get("ebook_data_geter_path", "")
            book_id = report.get("book_id", "")
            if book_id and nlc_path:
                bookmark = await get_bookmark(book_id, nlc_path)
                if bookmark:
                    task_store.add_log(task_id, "Bookmark fetched from NLC")
                    report["bookmark"] = bookmark
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
    finished_dir = config.get("finished_dir", "")

    if pdf_path and os.path.exists(pdf_path) and finished_dir:
        try:
            os.makedirs(finished_dir, exist_ok=True)
            dest_pdf = os.path.join(finished_dir, os.path.basename(pdf_path))
            if os.path.abspath(pdf_path) != os.path.abspath(dest_pdf):
                shutil.move(pdf_path, dest_pdf)
                report["pdf_path"] = dest_pdf
                task_store.add_log(task_id, f"PDF moved to finished dir: {dest_pdf}")
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
