"""Layout analysis — word-level bounding boxes via Tesseract with PIL fallback."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image as PILImage

from ocrmypdf.models.ocr_element import BoundingBox

log = logging.getLogger(__name__)

_TESSERACT_PATHS_WIN = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
]

_DEFAULT_NUM_LINES = 30


@dataclass
class LayoutWord:
    bbox: BoundingBox
    text: str
    confidence: int = 0


@dataclass
class LayoutLine:
    bbox: BoundingBox
    words: list[LayoutWord] = field(default_factory=list)


class LayoutAnalyzer:
    """Detects text line bounding boxes from a page image.

    Uses Tesseract TSV output for precise word-level positions when available.
    Falls back to evenly-spaced PIL-based regions.
    """

    def __init__(self, language: str = "chi_sim+eng"):
        self.language = language

    def analyze(self, image_path: Path) -> list[LayoutLine]:
        """Run layout analysis on a page image.

        Returns a list of LayoutLine objects, each containing word-level
        bounding boxes. Lines are ordered top-to-bottom.
        """
        tess_path = self._find_tesseract()
        if tess_path:
            try:
                return self._analyze_tesseract(image_path, tess_path)
            except Exception as exc:
                log.warning("Tesseract layout failed, using fallback: %s", exc)
        return self._analyze_fallback(image_path)

    def _find_tesseract(self) -> str | None:
        for path in _TESSERACT_PATHS_WIN:
            if os.path.exists(path):
                return path
        return shutil.which("tesseract")

    def _analyze_tesseract(
        self, image_path: Path, tess_path: str
    ) -> list[LayoutLine]:
        result = subprocess.run(
            [
                tess_path,
                str(image_path),
                "stdout",
                "-l",
                self.language,
                "--psm",
                "6",
                "tsv",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Tesseract exited with code {result.returncode}")

        raw_words: list[dict[str, Any]] = []
        for raw_line in result.stdout.strip().split("\n")[1:]:
            cols = raw_line.split("\t")
            if len(cols) < 12:
                continue
            try:
                level = int(cols[0])
            except ValueError:
                continue
            if level != 5:
                continue
            try:
                left = int(cols[6])
                top = int(cols[7])
                w = int(cols[8])
                h = int(cols[9])
                conf = int(float(cols[10]))
                text = cols[11].strip()
                line_num = int(cols[4])
            except (ValueError, IndexError):
                continue
            raw_words.append(
                {
                    "text": text,
                    "conf": conf,
                    "bbox": BoundingBox(left, top, left + w, top + h),
                    "line_num": line_num,
                }
            )

        if not raw_words:
            raise RuntimeError("Tesseract produced no word-level output")

        lines_dict: dict[int, list] = {}
        for w in raw_words:
            lines_dict.setdefault(w["line_num"], []).append(w)

        lines: list[LayoutLine] = []
        for ln in sorted(lines_dict):
            words = sorted(lines_dict[ln], key=lambda w: w["bbox"].left)
            l_min_x = min(w["bbox"].left for w in words)
            l_min_y = min(w["bbox"].top for w in words)
            l_max_x = max(w["bbox"].right for w in words)
            l_max_y = max(w["bbox"].bottom for w in words)
            line_bbox = BoundingBox(l_min_x, l_min_y, l_max_x, l_max_y)
            line_words = [
                LayoutWord(bbox=w["bbox"], text=w["text"], confidence=w["conf"])
                for w in words
            ]
            lines.append(LayoutLine(bbox=line_bbox, words=line_words))
        return lines

    def _analyze_fallback(self, image_path: Path) -> list[LayoutLine]:
        with PILImage.open(image_path) as img:
            img_w, img_h = img.size

        margin = int(img_h * 0.05)
        line_h = (img_h - 2 * margin) / _DEFAULT_NUM_LINES

        lines: list[LayoutLine] = []
        for i in range(_DEFAULT_NUM_LINES):
            y = margin + i * line_h
            bbox = BoundingBox(margin, y, img_w - margin, y + line_h)
            lines.append(LayoutLine(bbox=bbox))
        return lines
