"""LLM OCR engine — ocrmypdf OcrEngine implementation."""

import logging
from pathlib import Path
from typing import Set

from ocrmypdf.pluginspec import OcrEngine

log = logging.getLogger(__name__)


class LlmOcrEngine(OcrEngine):

    @staticmethod
    def version() -> str:
        return "1.0.0"

    @staticmethod
    def creator_tag(options) -> str:
        return "LLM-OCR v1.0"

    def __str__(self) -> str:
        return "LLM OCR Engine"

    @staticmethod
    def languages(options) -> Set[str]:
        return {"chi_sim", "chi_tra", "eng", "jpn", "kor", "fra", "deu", "spa"}

    @staticmethod
    def get_orientation(input_file: Path, options) -> "OrientationConfidence":
        from ocrmypdf.pluginspec import OrientationConfidence
        return OrientationConfidence(angle=0, confidence=0.0)

    @staticmethod
    def get_deskew(input_file: Path, options) -> float:
        return 0.0

    @staticmethod
    def generate_hocr(input_file, output_hocr, output_text, options):
        raise NotImplementedError("LLM OCR does not support hOCR output")

    @staticmethod
    def generate_pdf(input_file, output_pdf, output_text, options):
        """
        Called by ocrmypdf for each page image.
        Will be implemented in Task 2.
        """
        raise NotImplementedError("text_pdf module not yet created")
