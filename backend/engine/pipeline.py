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
from typing import Any, Dict, Optional

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


async def _download_from_aa(ss_code: str, tmp_dir: str, proxy: str = "", task_id: str = "") -> Optional[str]:
    """Search Anna's Archive by SS code and download the PDF. Returns the file path or None.
    Uses FlareSolverr for Cloudflare bypass when available.
    When task_id is provided, logs are also written to task_store."""
    def _log(msg: str):
        logger.warning(f"AA download: {msg}")
        if task_id:
            try:
                task_store.add_log(task_id, f"AA: {msg}")
            except Exception:
                pass

    import requests as _req
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    # Step 1: Search AA by SS code → get MD5
    search_url = f"https://annas-archive.gd/search?q={ss_code}"
    html = await _get_page_with_flare(search_url, proxy)
    if not html:
        _log(f"搜索页获取失败: {search_url}")
        return None
    if "Cloudflare" in html or "cf-browser-verification" in html:
        _log("Cloudflare 验证页面，FlareSolverr 未成功绕过")
        return None
    md5_m = re.search(r'href="/md5/([a-f0-9]{32})"', html)
    if not md5_m:
        _log(f"搜索结果中未找到 MD5 链接 (SS:{ss_code})")
        return None
    md5 = md5_m.group(1)
    _log(f"找到 MD5: {md5}")

    # Step 2: Visit MD5 page → extract download link
    md5_url = f"https://annas-archive.gd/md5/{md5}"
    md5_html = await _get_page_with_flare(md5_url, proxy, timeout=30)
    if not md5_html:
        _log(f"MD5 详情页获取失败: {md5_url}")
        return None

    dl_url = None

    # Pattern A: Extract download link directly from MD5 page HTML
    for p in [
        r'href="(https?://[^"]*/(?:d|dl|get)/[^"]*\.(?:pdf|epub|mobi)[^"]*)"',
        r'href="(https?://[^"]*\.(?:pdf|epub|mobi)\?[^"]*)"',
        r'href="(https?://[^"]*annas-archive[^"]*/[a-f0-9]{32}[^"]*)"',
        r'data-(?:url|file|download)="(https?://[^"]*)"',
    ]:
        m = re.search(p, md5_html)
        if m:
            dl_url = m.group(1)
            break

    # Pattern B: /d/{md5} redirect — fetch through FlareSolverr for Cloudflare bypass
    if not dl_url:
        d_url = f"https://annas-archive.gd/d/{md5}"
        d_html = await _get_page_with_flare(d_url, proxy, timeout=15)
        if d_html:
            for p in [
                r'href="(https?://[^"]*\.(?:pdf|epub|mobi)[^"]*)"',
                r'<meta[^>]*url=([^"\']+)',
                r'window\.location\s*=\s*["\']([^"\']+)',
            ]:
                m = re.search(p, d_html)
                if m:
                    dl_url = m.group(1)
                    break
            if not dl_url:
                try:
                    d_kwargs = {"timeout": 15, "headers": headers, "verify": False, "allow_redirects": False}
                    if proxy:
                        d_kwargs["proxies"] = {"http": proxy, "https": proxy}
                    resp = _req.get(d_url, **d_kwargs)
                    if resp.status_code in (301, 302, 303, 307):
                        dl_url = resp.headers.get("Location")
                except Exception:
                    pass

    if not dl_url:
        _log(f"未找到下载链接 (MD5:{md5})")
        return None

    _log(f"找到下载链接: {dl_url[:80]}...")

    # Step 3: Download the file
    try:
        f_kwargs = {"timeout": 60, "headers": headers, "verify": False, "stream": True}
        if proxy:
            f_kwargs["proxies"] = {"http": proxy, "https": proxy}
        file_resp = _req.get(dl_url, **f_kwargs)
        file_resp.raise_for_status()

        import urllib.parse as _up
        cd = file_resp.headers.get("Content-Disposition", "")
        fname = f"{md5}.pdf"
        if cd and "filename=" in cd:
            fname = cd.split("filename=")[-1].strip("\"' ")
        else:
            url_path = _up.urlparse(dl_url).path
            if url_path:
                fname = os.path.basename(url_path) or fname

        filepath = os.path.join(tmp_dir, fname)
        with open(filepath, "wb") as f:
            for chunk in file_resp.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)

        size = os.path.getsize(filepath)
        if size > 1024:
            _log(f"下载成功: {fname} ({size/1024:.0f} KB)")
            return filepath
        _log(f"文件太小 ({size} bytes)")
    except Exception as e:
        _log(f"文件下载失败: {e}")
    return None


async def _step_download_pages(task_id: str, task: Dict[str, Any], config: Dict[str, Any], report: Dict[str, Any]) -> Dict[str, Any]:
    task_store.add_log(task_id, "Step 3/7: Downloading book pages...")
    await _emit(task_id, "step_progress", {"step": "download_pages", "progress": 0})

    tmp_dir = config.get("tmp_dir", "")
    if tmp_dir:
        task_tmp = os.path.join(tmp_dir, task_id)
        os.makedirs(task_tmp, exist_ok=True)
        report["tmp_dir"] = task_tmp
    else:
        task_store.add_log(task_id, "No tmp_dir configured, using default")
        report["tmp_dir"] = os.path.join(os.path.dirname(__file__), "tmp", task_id)
        os.makedirs(report["tmp_dir"], exist_ok=True)

    ss_code = report.get("ss_code", "")
    isbn = report.get("isbn", "")
    proxy = config.get("http_proxy", "")
    title = report.get("title", "")
    downloaded = False

    # === Method 1: Anna's Archive (search by SS code → MD5 → download) ===
    if ss_code:
        task_store.add_log(task_id, f"Trying Anna's Archive (SS:{ss_code})...")
        await _emit(task_id, "step_progress", {"step": "download_pages", "progress": 30})
        filepath = await _download_from_aa(ss_code, report["tmp_dir"], proxy, task_id)
        if filepath:
            task_store.add_log(task_id, f"Downloaded from Anna's Archive: {os.path.basename(filepath)}")
            report["download_path"] = filepath
            report["download_source"] = "annas_archive"
            downloaded = True
        else:
            task_store.add_log(task_id, "Anna's Archive download failed, trying next method...")

    # === Method 2: Z-Library (search by ISBN → download via eAPI) ===
    if not downloaded and isbn:
        task_store.add_log(task_id, f"Trying Z-Library (ISBN:{isbn})...")
        await _emit(task_id, "step_progress", {"step": "download_pages", "progress": 50})
        try:
            from engine.zlib_downloader import ZLibDownloader
            dl = ZLibDownloader(config)
            result = await dl.zlib_search(isbn, page=1, limit=5)
            raw_items = result.get("books") or result.get("results") or result.get("data") or []
            if isinstance(raw_items, dict):
                raw_items = raw_items.get("books", raw_items.get("results", []))
            # raw_items should now be a list
            for item in (raw_items if isinstance(raw_items, list) else []):
                book_id = str(item.get("id", ""))
                book_hash = item.get("hash") or item.get("book_hash") or ""
                task_store.add_log(task_id, f"ZL result: id={book_id}, hash={'yes' if book_hash else 'no'}")
                if book_id and book_hash:
                    ok = await dl.zlib_download_book(book_id, book_hash, report["tmp_dir"])
                    if ok:
                        saved_files = list(Path(report["tmp_dir"]).glob(f"{book_id}.*"))
                        valid = False
                        for f in saved_files:
                            if f.stat().st_size > 1024:
                                valid = True
                                report["download_path"] = str(f)
                                break
                        if valid:
                            task_store.add_log(task_id, f"Downloaded from Z-Library: {book_id}")
                            report["download_source"] = "zlibrary"
                            downloaded = True
                            break
                        else:
                            task_store.add_log(task_id, f"Z-Library file for {book_id} is empty or invalid")
                    else:
                        task_store.add_log(task_id, f"Z-Library download attempt failed for book {book_id}")
        except Exception as e:
            task_store.add_log(task_id, f"Z-Library download error: {e}")

    if not downloaded:
        task_store.add_log(task_id, "All download methods failed")
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
                    f.write(img2pdf.convert([str(p) for p in image_files]))
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
