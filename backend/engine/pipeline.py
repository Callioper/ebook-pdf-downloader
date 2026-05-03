# ==== pipeline.py ====
# 职责：书籍下载处理流水线，协调元数据获取、下载、转换、OCR和书签
# 入口函数：run_pipeline()
# 依赖：config, task_store, ws_manager, engine.flaresolverr, engine.zlib_downloader, nlc.nlc_isbn
# 注意：7步流水线，支持取消和错误处理

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from config import get_config
from task_store import task_store, STATUS_RUNNING, STATUS_CANCELLED, STATUS_FAILED
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

    report = {
        "book_id": book_id,
        "title": title,
        "source": source,
        "ss_code": task.get("ss_code", ""),
        "isbn": task.get("isbn", ""),
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

    source = report.get("source", "DX_6.0")
    book_id = report.get("book_id", "")
    ss_code = report.get("ss_code", "")

    if not book_id:
        task_store.add_log(task_id, "No book_id, searching with SS code...")
        book_id = ss_code

    task_store.add_log(task_id, f"Downloading from source: {source}")
    await _emit(task_id, "step_progress", {"step": "download_pages", "progress": 20})

    try:
        from engine.flaresolverr import download_via_flaresolverr
        from engine.zlib_downloader import ZLibDownloader
        dl = ZLibDownloader(config)
        await dl.download_file(task_id, book_id, report["tmp_dir"])
    except ImportError:
        task_store.add_log(task_id, "ZLib downloader not available")
        report["download_note"] = "ZLib downloader not available - manual download required"


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
