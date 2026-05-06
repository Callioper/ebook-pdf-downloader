"""Split a PDF into N chunks, run PaddleOCR on each chunk in parallel, merge output."""

import asyncio
import logging
import os
import re
import tempfile
import time
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


def split_pdf(pdf_path: str, num_chunks: int) -> List[str]:
    """Split a PDF into `num_chunks` roughly equal parts.
    Returns list of paths to temporary chunk PDFs."""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        total_pages = len(doc)
        if total_pages == 0:
            return []

        chunks = []
        pages_per_chunk = max(1, total_pages // num_chunks)

        for i in range(num_chunks):
            start_page = i * pages_per_chunk
            if i == num_chunks - 1:
                end_page = total_pages
            else:
                end_page = start_page + pages_per_chunk

            if start_page >= total_pages:
                break

            chunk_doc = fitz.open()
            try:
                for pg in range(start_page, end_page):
                    chunk_doc.insert_pdf(doc, from_page=pg, to_page=pg)

                fd, chunk_path = tempfile.mkstemp(suffix=f'_chunk_{i}.pdf', prefix='paddleocr_')
                os.close(fd)
                chunk_doc.save(chunk_path, garbage=4, deflate=True)
                chunks.append(chunk_path)
            finally:
                chunk_doc.close()

        return chunks
    finally:
        doc.close()


def merge_pdfs(pdf_paths: List[str], output_path: str) -> bool:
    """Merge multiple OCR'd PDFs into one output PDF. Returns True on success."""
    import fitz

    merged = fitz.open()
    try:
        for path in pdf_paths:
            if not os.path.exists(path):
                logger.warning(f"merge_pdfs: missing chunk {path}")
                continue
            doc = fitz.open(path)
            try:
                merged.insert_pdf(doc)
            finally:
                doc.close()
        merged.save(output_path, garbage=4, deflate=True)
        return True
    except Exception as e:
        logger.error(f"merge_pdfs failed: {e}")
        return False
    finally:
        merged.close()


async def run_paddleocr_parallel(
    *,
    pdf_path: str,
    output_pdf: str,
    paddle_python: str,
    ocr_lang: str,
    num_workers: int,
    total_pages: int = 0,
    timeout_per_chunk: int = 1800,
    oversample: int = 200,
    optimize: str = "0",
    add_log: Optional[Callable] = None,
    emit_progress: Optional[Callable] = None,
) -> int:
    """Split PDF into num_workers chunks, run PaddleOCR on each chunk in parallel,
    merge results. Returns exit code (0 = success)."""
    if add_log is None:
        add_log = lambda msg: None
    if emit_progress is None:
        async def _noop(**kw): pass
        emit_progress = _noop

    add_log(f"PaddleOCR parallel: splitting PDF into {num_workers} chunks...")
    chunks = split_pdf(pdf_path, num_workers)

    if not chunks:
        add_log("PaddleOCR parallel: no pages to process")
        return 1

    # Pre-compute page counts per chunk
    chunk_page_counts = []
    for c in chunks:
        import fitz
        d = fitz.open(c)
        chunk_page_counts.append(len(d))
        d.close()

    if total_pages <= 0:
        total_pages = sum(chunk_page_counts)

    add_log(f"PaddleOCR parallel: {len(chunks)} chunks, {num_workers} workers, {total_pages} total pages")

    start_time = time.time()
    _spawned_procs = []

    async def process_chunk(i: int, chunk_path: str) -> Optional[str]:
        out_path = chunk_path.replace('.pdf', '_ocr.pdf')
        cmd = [
            paddle_python, "-m", "ocrmypdf",
            "--plugin", "ocrmypdf_paddleocr",
            "--optimize", optimize,
            "--oversample", str(oversample),
            "-l", ocr_lang or "chi_sim+eng",
            "-j", "1",
            "--output-type", "pdf",
            "--mode", "force",
            chunk_path,
            out_path,
        ]
        env = {**os.environ, "PATH": os.environ.get("PATH", "") + r";C:\Program Files\Tesseract-OCR",
               "PYTHONUNBUFFERED": "1"}

        chunk_pages = chunk_page_counts[i] if i < len(chunk_page_counts) else 0
        chunk_completed = 0

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            _spawned_procs.append(proc)

            async for line in proc.stdout:
                text = line.decode('utf-8', errors='replace').strip()
                if not text:
                    continue

                m = re.search(r'\[(\d+)/(\d+)\]', text)
                if m:
                    chunk_completed = int(m.group(1))
                    chunk_pages = max(chunk_pages, int(m.group(2)))
                else:
                    m = re.search(r'[Pp]age\s+(\d+)\s+[oO]f\s+(\d+)', text)
                    if m:
                        chunk_completed = int(m.group(1))
                        chunk_pages = max(chunk_pages, int(m.group(2)))

                if chunk_pages > 0 and chunk_completed > 0:
                    _pages_before = sum(chunk_page_counts[:i]) if i > 0 else 0
                    global_cur = _pages_before + chunk_completed
                    _pct = int(global_cur / total_pages * 100) if total_pages > 0 else 0
                    _elapsed = time.time() - start_time
                    _speed = global_cur / _elapsed if _elapsed > 0 else 0
                    _eta = (total_pages - global_cur) / _speed if _speed > 0 else 0
                    _eta_str = f"{int(_eta // 60)}分{int(_eta % 60)}秒" if _eta > 0 else ""
                    await emit_progress(
                        step="ocr",
                        progress=_pct,
                        detail=f"{global_cur}/{total_pages} 页",
                        eta=_eta_str,
                    )

            await proc.wait()

            if proc.returncode == 0 and os.path.exists(out_path):
                return out_path
            else:
                if os.path.exists(out_path):
                    try:
                        os.remove(out_path)
                    except Exception:
                        pass
                add_log(f"PaddleOCR chunk {i+1} failed: exit {proc.returncode}")
                return None
        except asyncio.TimeoutError:
            add_log(f"PaddleOCR chunk {i+1} timed out")
            try:
                proc.kill()
            except Exception:
                pass
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except Exception:
                    pass
            return None
        except Exception as e:
            add_log(f"PaddleOCR chunk {i+1} error: {e}")
            try:
                if proc:
                    proc.kill()
            except Exception:
                pass
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except Exception:
                    pass
            return None
        finally:
            if proc and proc in _spawned_procs:
                _spawned_procs.remove(proc)

    add_log(f"PaddleOCR parallel: processing {len(chunks)} chunks...")
    tasks = [process_chunk(i, chunk_path) for i, chunk_path in enumerate(chunks)]
    try:
        results = await asyncio.gather(*tasks)
    finally:
        for proc in _spawned_procs:
            try:
                if proc.returncode is None:
                    proc.kill()
            except Exception:
                pass

    chunk_outputs = [r for r in results if r is not None]
    add_log(f"PaddleOCR parallel: {len(chunk_outputs)}/{len(chunks)} chunks completed")

    if emit_progress:
        await emit_progress(step="ocr", progress=90, detail="合并分块结果...")

    if not chunk_outputs:
        add_log("PaddleOCR parallel: all chunks failed")
        for c in chunks:
            try:
                os.remove(c)
            except Exception:
                pass
        return 1

    add_log("PaddleOCR parallel: merging chunks...")
    ok = merge_pdfs(chunk_outputs, output_pdf)

    for c in chunks:
        try:
            os.remove(c)
        except Exception:
            pass
    for c in chunk_outputs:
        try:
            os.remove(c)
        except Exception:
            pass

    if not ok:
        add_log("PaddleOCR parallel: merge failed")
        return 1

    elapsed = time.time() - start_time
    add_log(f"PaddleOCR parallel: done in {elapsed:.1f}s")
    return 0
