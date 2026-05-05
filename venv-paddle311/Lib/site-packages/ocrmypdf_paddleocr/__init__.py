# SPDX-License-Identifier: MPL-2.0

"""PaddleOCR engine plugin for OCRmyPDF."""

from __future__ import annotations

import logging

from ocrmypdf import hookimpl

log = logging.getLogger(__name__)


@hookimpl
def initialize(plugin_manager):
    """Check that PaddleOCR is importable at startup."""
    try:
        import paddleocr  # noqa: F401
    except ImportError:
        from ocrmypdf.exceptions import MissingDependencyError

        raise MissingDependencyError(
            "PaddleOCR is required but not installed. "
            "Install with: pip install paddleocr paddlepaddle"
        )


@hookimpl
def check_options(options):
    """Limit concurrency -- PaddlePaddle's inference crashes with multiple workers."""
    if options.jobs != 1:
        log.info("PaddleOCR: forcing jobs=1 (PaddlePaddle is not multi-process safe)")
        options.jobs = 1


@hookimpl
def get_ocr_engine():
    """Return PaddleOcrEngine."""
    from ocrmypdf_paddleocr.engine import PaddleOcrEngine

    return PaddleOcrEngine()
