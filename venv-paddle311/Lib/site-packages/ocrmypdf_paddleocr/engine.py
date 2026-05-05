# SPDX-License-Identifier: MPL-2.0

"""PaddleOCR engine implementation for OCRmyPDF."""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from ocrmypdf.models.ocr_element import BoundingBox, OcrClass, OcrElement
from ocrmypdf.pluginspec import OcrEngine, OrientationConfidence

from ocrmypdf_paddleocr.lang_map import SUPPORTED_LANGUAGES, tesseract_to_paddle

if TYPE_CHECKING:
    from ocrmypdf._options import OcrOptions

log = logging.getLogger(__name__)

_paddle_engine = None
_paddle_lang = None


def _create_paddle_engine(lang: str):
    """Create a new PaddleOCR engine instance."""
    # Tesseract's plugin sets OMP_THREAD_LIMIT=1 which cripples PaddlePaddle.
    saved = os.environ.pop('OMP_THREAD_LIMIT', None)

    from paddleocr import PaddleOCR

    engine = PaddleOCR(
        lang=lang,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=True,
    )

    if saved is not None:
        os.environ['OMP_THREAD_LIMIT'] = saved

    return engine


def _get_paddle_engine(options: OcrOptions):
    """Get or create a cached PaddleOCR engine instance."""
    global _paddle_engine, _paddle_lang

    lang = tesseract_to_paddle(options.languages[0]) if options.languages else 'en'

    if _paddle_engine is not None and _paddle_lang == lang:
        return _paddle_engine

    _paddle_engine = _create_paddle_engine(lang)
    _paddle_lang = lang

    return _paddle_engine


def _reset_paddle_engine():
    """Force recreation of the engine on next call."""
    global _paddle_engine, _paddle_lang
    _paddle_engine = None
    _paddle_lang = None


def _quad_to_bbox(quad) -> BoundingBox | None:
    """Convert a 4-point quad ((x1,y1),(x2,y2),(x3,y3),(x4,y4)) to BoundingBox."""
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    left, right = float(min(xs)), float(max(xs))
    top, bottom = float(min(ys)), float(max(ys))
    if right <= left or bottom <= top:
        return None
    return BoundingBox(left=left, top=top, right=right, bottom=bottom)


class PaddleOcrEngine(OcrEngine):
    """OCR engine using PaddleOCR."""

    @staticmethod
    def version() -> str:
        import paddleocr

        return getattr(paddleocr, '__version__', 'unknown')

    @staticmethod
    def creator_tag(options: OcrOptions) -> str:
        return f"PaddleOCR {PaddleOcrEngine.version()}"

    def __str__(self) -> str:
        return f"PaddleOCR {self.version()}"

    @staticmethod
    def languages(options: OcrOptions) -> set[str]:
        return SUPPORTED_LANGUAGES

    @staticmethod
    def get_orientation(
        input_file: Path, options: OcrOptions
    ) -> OrientationConfidence:
        from paddleocr._models.doc_img_orientation_classification import (
            DocImgOrientationClassification,
        )

        clf = DocImgOrientationClassification()
        result = list(clf.predict(str(input_file)))
        if not result:
            return OrientationConfidence(angle=0, confidence=0.0)
        angle = int(result[0]['label_names'][0])
        score = float(result[0]['scores'][0])
        # Map score (0-1) to OCRmyPDF confidence scale (0-15)
        confidence = score * 15.0
        return OrientationConfidence(angle=angle, confidence=confidence)

    @staticmethod
    def get_deskew(input_file: Path, options: OcrOptions) -> float:
        engine = _get_paddle_engine(options)
        result = engine.predict(str(input_file))
        if not result or not result[0]:
            return 0.0

        dt_polys = result[0].get('dt_polys', [])
        if not dt_polys:
            return 0.0

        # Compute skew from the top edge of each text line polygon
        angles = []
        for poly in dt_polys:
            if len(poly) < 2:
                continue
            # Top edge: poly[0] -> poly[1]
            dx = float(poly[1][0] - poly[0][0])
            dy = float(poly[1][1] - poly[0][1])
            if abs(dx) < 1:
                continue
            angles.append(math.degrees(math.atan2(dy, dx)))

        if not angles:
            return 0.0

        # Median angle is more robust than mean against outliers
        angles.sort()
        mid = len(angles) // 2
        if len(angles) % 2 == 0:
            return (angles[mid - 1] + angles[mid]) / 2.0
        return angles[mid]

    @staticmethod
    def supports_generate_ocr() -> bool:
        return True

    @staticmethod
    def generate_ocr(
        input_file: Path,
        options: OcrOptions,
        page_number: int = 0,
    ) -> tuple[OcrElement, str]:
        """Run PaddleOCR and return an OcrElement tree."""
        engine = _get_paddle_engine(options)

        with Image.open(input_file) as img:
            img_width, img_height = img.size
            dpi_info = img.info.get('dpi', (300, 300))
            dpi = float(dpi_info[0] if isinstance(dpi_info, tuple) else dpi_info)

        page = OcrElement(
            ocr_class=OcrClass.PAGE,
            bbox=BoundingBox(left=0, top=0, right=img_width, bottom=img_height),
            dpi=dpi,
            page_number=page_number,
        )

        try:
            result = engine.predict(str(input_file), return_word_box=True)
        except KeyError:
            # PaddleOCR bug: return_word_box=True crashes on blank images.
            result = engine.predict(str(input_file))
        except RuntimeError:
            # PaddlePaddle's C++ predictor can become stale across
            # ThreadPoolExecutor lifecycles. Recreate and retry once.
            log.debug("PaddlePaddle inference failed, recreating engine")
            _reset_paddle_engine()
            engine = _get_paddle_engine(options)
            result = engine.predict(str(input_file), return_word_box=True)

        if not result or not result[0]:
            return page, ""

        ocr_data = result[0]
        rec_texts = ocr_data.get('rec_texts', [])
        rec_scores = ocr_data.get('rec_scores', [])
        rec_boxes = ocr_data.get('rec_boxes', [])
        text_words = ocr_data.get('text_word', [])
        text_word_regions = ocr_data.get('text_word_region', [])

        if not rec_texts:
            return page, ""

        has_word_boxes = bool(text_words and text_word_regions)
        text_parts = []

        for i, (text, score, box) in enumerate(zip(rec_texts, rec_scores, rec_boxes)):
            if not text.strip():
                continue

            x1, y1, x2, y2 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
            if x2 <= x1 or y2 <= y1:
                continue

            line_bbox = BoundingBox(left=x1, top=y1, right=x2, bottom=y2)
            line = OcrElement(ocr_class=OcrClass.LINE, bbox=line_bbox)

            if has_word_boxes and i < len(text_words) and text_words[i]:
                # Word-level bounding boxes from PaddleOCR
                for token, quad in zip(text_words[i], text_word_regions[i]):
                    token = str(token).strip()
                    if not token:
                        continue
                    word_bbox = _quad_to_bbox(quad)
                    if word_bbox is None:
                        continue
                    word = OcrElement(
                        ocr_class=OcrClass.WORD,
                        bbox=word_bbox,
                        text=token,
                        confidence=float(score),
                    )
                    line.children.append(word)
            else:
                # Fallback: whole line as single word
                word = OcrElement(
                    ocr_class=OcrClass.WORD,
                    bbox=line_bbox,
                    text=text,
                    confidence=float(score),
                )
                line.children.append(word)

            if line.children:
                page.children.append(line)
                text_parts.append(text)

        full_text = '\n'.join(text_parts)
        return page, full_text

    @staticmethod
    def generate_hocr(input_file, output_hocr, output_text, options):
        raise NotImplementedError("Use generate_ocr()")

    @staticmethod
    def generate_pdf(input_file, output_pdf, output_text, options):
        raise NotImplementedError("Use generate_ocr()")
