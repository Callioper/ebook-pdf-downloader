"""Wrapper for calling local-llm-pdf-ocr's Surya detection script as subprocess."""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional


class SuryaDetectError(Exception):
    pass


def _find_uv() -> Optional[str]:
    uv = shutil.which("uv") or shutil.which("uv.exe")
    if not uv:
        candidate = os.path.expanduser(r"~\.local\bin\uv.exe")
        if os.path.exists(candidate):
            uv = candidate
    return uv


def _find_project_root() -> Optional[str]:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        # Check current dir and parent dir (exe may be in dist/ subfolder)
        candidates = [base, base.parent]
    else:
        base = Path(__file__).resolve().parent.parent.parent
        candidates = [base]
    for c in candidates:
        p = str(c / "local-llm-pdf-ocr")
        if os.path.isdir(p):
            return p
    return None


async def run_surya_detect(
    pdf_path: str,
    dpi: int = 200,
    pages: Optional[str] = None,
    detect_batch_size: int = 20,
    text_threshold: Optional[float] = None,
    blank_threshold: Optional[float] = None,
) -> Dict[int, List[List[float]]]:
    """Run Surya detection on a PDF, return {page_idx: [[x0,y0,x1,y1], ...]} with normalized coords."""

    uv_bin = _find_uv()
    project_root = _find_project_root()

    if not uv_bin or not project_root:
        raise SuryaDetectError(
            f"Surya detection requires uv + local-llm-pdf-ocr. uv={'found' if uv_bin else 'missing'}, project={'found' if project_root else 'missing'}"
        )

    script = os.path.join(project_root, "scripts", "detect_boxes.py")
    if not os.path.exists(script):
        raise SuryaDetectError(f"detect_boxes.py not found at {script}")

    cmd = [uv_bin, "run", "--directory", project_root, script, pdf_path, "--dpi", str(dpi)]
    if pages:
        cmd.extend(["--pages", pages])
    cmd.extend(["--detect-batch-size", str(detect_batch_size)])
    if text_threshold is not None:
        cmd.extend(["--text-threshold", str(text_threshold)])
    if blank_threshold is not None:
        cmd.extend(["--blank-threshold", str(blank_threshold)])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise SuryaDetectError(
            f"Surya detection failed with exit code {proc.returncode}: {stderr.decode('utf-8', errors='replace')[:500]}"
        )

    return parse_detect_output(stdout.decode("utf-8", errors="replace"))


def parse_detect_output(raw: str) -> Dict[int, List[List[float]]]:
    """Parse JSON output from detect_boxes.py."""
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        raise SuryaDetectError(f"Invalid JSON from detection script: {e}") from e

    pages = data.get("pages", [])
    result: Dict[int, List[List[float]]] = {}
    for page in pages:
        pg = page["page"]
        result[pg] = page.get("boxes", [])
    return result
