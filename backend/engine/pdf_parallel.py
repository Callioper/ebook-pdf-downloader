"""Split a PDF into N chunks, run PaddleOCR on each chunk in parallel, merge output."""

import asyncio
import logging
import os
import subprocess
import tempfile
import time
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def split_pdf(pdf_path: str, num_chunks: int) -> List[str]:
    """Split a PDF into `num_chunks` roughly equal parts.
    Returns list of paths to temporary chunk PDFs."""
    import fitz

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
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
        for pg in range(start_page, end_page):
            chunk_doc.insert_pdf(doc, from_page=pg, to_page=pg)

        fd, chunk_path = tempfile.mkstemp(suffix=f'_chunk_{i}.pdf', prefix='paddleocr_')
        os.close(fd)
        chunk_doc.save(chunk_path, garbage=4, deflate=True)
        chunk_doc.close()
        chunks.append(chunk_path)

    doc.close()
    return chunks


def merge_pdfs(pdf_paths: List[str], output_path: str) -> bool:
    """Merge multiple OCR'd PDFs into one output PDF. Returns True on success."""
    import fitz

    try:
        merged = fitz.open()
        for path in pdf_paths:
            if not os.path.exists(path):
                logger.warning(f"merge_pdfs: missing chunk {path}")
                continue
            doc = fitz.open(path)
            merged.insert_pdf(doc)
            doc.close()
        merged.save(output_path, garbage=4, deflate=True)
        merged.close()
        return True
    except Exception as e:
        logger.error(f"merge_pdfs failed: {e}")
        return False


async def run_paddleocr_parallel(
    *,
    pdf_path: str,
    output_pdf: str,
    paddle_python: str,
    ocr_lang: str,
    num_workers: int,
    timeout_per_chunk: int = 1800,
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

    add_log(f"PaddleOCR parallel: {len(chunks)} chunks, {num_workers} workers")

    start_time = time.time()
    chunk_outputs: List[str] = []

    async def process_chunk(i: int, chunk_path: str) -> Optional[str]:
        out_path = chunk_path.replace('.pdf', '_ocr.pdf')
        cmd = [
            paddle_python, "-m", "ocrmypdf",
            "--plugin", "ocrmypdf_paddleocr",
            "--optimize", "0",
            "--oversample", "200",
            "-l", ocr_lang or "chi_sim+eng",
            "-j", "1",
            "--output-type", "pdf",
            "--mode", "force",
            chunk_path,
            out_path,
        ]
        env = {**os.environ, "PATH": os.environ.get("PATH", "") + r";C:\Program Files\Tesseract-OCR",
               "PYTHONUNBUFFERED": "1"}

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_per_chunk)
            if proc.returncode == 0 and os.path.exists(out_path):
                return out_path
            else:
                add_log(f"PaddleOCR chunk {i+1} failed: exit {proc.returncode}")
                return None
        except asyncio.TimeoutError:
            add_log(f"PaddleOCR chunk {i+1} timed out")
            try:
                proc.kill()
            except Exception:
                pass
            return None
        except Exception as e:
            add_log(f"PaddleOCR chunk {i+1} error: {e}")
            return None

    add_log(f"PaddleOCR parallel: processing {len(chunks)} chunks...")
    tasks = [process_chunk(i, chunk_path) for i, chunk_path in enumerate(chunks)]
    results = await asyncio.gather(*tasks)

    chunk_outputs = [r for r in results if r is not None]
    add_log(f"PaddleOCR parallel: {len(chunk_outputs)}/{len(chunks)} chunks completed")

    # Progress
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

    # Clean up temp files
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
