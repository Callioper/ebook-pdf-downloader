"""LLM OCR engine — ocrmypdf OcrEngine implementation.
Uses Tesseract for layout (bboxes) and LLM vision model for high-quality text recognition."""

import logging
from pathlib import Path
from typing import Set

from ocrmypdf.pluginspec import OcrEngine

log = logging.getLogger(__name__)


class LlmOcrEngine(OcrEngine):

    @staticmethod
    def version() -> str:
        return "1.1.0"

    @staticmethod
    def creator_tag(options) -> str:
        return "LLM-OCR v1.1"

    def __str__(self) -> str:
        return "LLM OCR Engine"

    @staticmethod
    def languages(options) -> Set[str]:
        return {"chi_sim", "chi_tra", "eng", "jpn", "kor", "fra", "deu", "spa"}

    @staticmethod
    def get_orientation(input_file: Path, options) -> "OrientationConfidence":
        from ocrmypdf.pluginspec import OrientationConfidence
        # Delegate to Tesseract if available
        tess = _find_tesseract()
        if tess:
            try:
                import subprocess
                r = subprocess.run(
                    [tess, str(input_file), 'stdout', '--psm', '0'],
                    capture_output=True, text=True, timeout=15,
                )
                out = (r.stdout or r.stderr or '')
                for line in out.split('\n'):
                    if 'Orientation in degrees:' in line:
                        angle = int(line.split(':')[-1].strip())
                        conf = float(line.split('confidence:')[-1].strip()) if 'confidence:' in line else 0.0
                        return OrientationConfidence(angle=angle, confidence=conf / 100.0)
            except Exception:
                pass
        return OrientationConfidence(angle=0, confidence=0.0)

    @staticmethod
    def get_deskew(input_file: Path, options) -> float:
        return 0.0

    @staticmethod
    def generate_hocr(input_file, output_hocr, output_text, options):
        raise NotImplementedError("LLM OCR does not support hOCR output")

    @staticmethod
    def supports_generate_ocr() -> bool:
        return True  # Use modern OcrElement tree path for proper bbox positioning

    @staticmethod
    def generate_ocr(input_file, options, page_number: int = 0):
        """Generate OCR output. Uses Tesseract for precise word-level bboxes,
        LLM vision model for high-quality text. LLM characters are mapped
        one-to-one to Tesseract bbox positions for correct alignment."""
        from ocrmypdf.models.ocr_element import OcrElement, OcrClass, BoundingBox

        # 1. Get image dimensions
        from PIL import Image
        with Image.open(input_file) as img:
            img_width, img_height = img.size
            dpi = float(img.info.get('dpi', (300, 300))[0])

        # 2. Create page element
        page_el = OcrElement(
            ocr_class=OcrClass.PAGE,
            bbox=BoundingBox(0, 0, img_width, img_height),
            dpi=dpi,
            page_number=page_number,
        )

        # 3. Get word-level bboxes from Tesseract (layout source)
        ts_lines = _tesseract_word_boxes(input_file)

        # 4. Flatten all Tesseract words into ordered list (top-to-bottom, left-to-right)
        all_ts_words = []
        for line_info in ts_lines:
            for w in line_info['words']:
                all_ts_words.append(w)

        # 5. Get LLM text
        endpoint = getattr(options, 'llm_ocr_endpoint', 'http://localhost:11434')
        model = getattr(options, 'llm_ocr_model', '')
        api_key = getattr(options, 'llm_ocr_api_key', '')
        lang = getattr(options, 'llm_ocr_lang', 'chi_sim+eng')

        llm_text = None
        if model:
            import base64
            img_bytes = Path(input_file).read_bytes()
            img_b64 = base64.b64encode(img_bytes).decode('utf-8')
            llm_text = _call_llm_sync(endpoint, model, api_key, img_b64, lang)

        # 6. Build OcrElement tree
        if llm_text and all_ts_words:
            # Clean LLM text: keep only meaningful characters, join into one string
            llm_chars = [c for c in llm_text if c.strip() or c == ' ']
            # Map LLM characters to Tesseract bboxes (1:1)
            full_text = _build_llm_tree(page_el, ts_lines, llm_chars, all_ts_words)
        else:
            # Fallback: Tesseract's own text
            full_text = _build_tesseract_tree(page_el, ts_lines)

        return page_el, full_text

    @staticmethod
    def generate_pdf(input_file, output_pdf, output_text, options):
        """Fallback path when generate_ocr is not supported (older ocrmypdf versions)."""
        from .text_pdf import create_text_only_pdf, _write_empty_pdf
        import base64

        img_bytes = Path(input_file).read_bytes()
        img_b64 = base64.b64encode(img_bytes).decode('utf-8')

        endpoint = getattr(options, 'llm_ocr_endpoint', 'http://localhost:11434')
        model = getattr(options, 'llm_ocr_model', '')
        api_key = getattr(options, 'llm_ocr_api_key', '')
        lang = getattr(options, 'llm_ocr_lang', 'chi_sim+eng')

        if not model:
            output_text.write_text("", encoding='utf-8')
            _write_empty_pdf(output_pdf)
            return

        text = _call_llm_sync(endpoint, model, api_key, img_b64, lang)
        if text is None:
            text = ""
        output_text.write_text(text, encoding='utf-8')
        create_text_only_pdf(output_pdf, text, input_file)


def _build_tesseract_tree(page_el, ts_lines) -> str:
    """Build OcrElement tree using Tesseract's own text + word-level bboxes.
    These are always correctly aligned because both come from the same source.
    Returns the full page text string."""
    from ocrmypdf.models.ocr_element import OcrElement, OcrClass, BoundingBox

    full_parts = []
    for line_info in ts_lines:
        words = line_info['words']
        if not words:
            continue

        # Line bbox: union of all word bboxes in this line
        l_min_x = min(w['bbox'].left for w in words)
        l_min_y = min(w['bbox'].top for w in words)
        l_max_x = max(w['bbox'].right for w in words)
        l_max_y = max(w['bbox'].bottom for w in words)
        line_bbox = BoundingBox(l_min_x, l_min_y, l_max_x, l_max_y)
        line_el = OcrElement(ocr_class=OcrClass.LINE, bbox=line_bbox)

        line_text_parts = []
        for w in words:
            if not w['text']:
                continue
            conf = w.get('conf', None)
            if conf is not None and conf >= 0:
                conf = float(conf) / 100.0
            else:
                conf = 0.9

            word_el = OcrElement(
                ocr_class=OcrClass.WORD,
                bbox=w['bbox'],
                text=w['text'],
                confidence=conf,
            )
            line_el.children.append(word_el)
            line_text_parts.append(w['text'])

        page_el.children.append(line_el)
        if line_text_parts:
            full_parts.append(''.join(line_text_parts))

    return '\n'.join(full_parts)


def _build_llm_tree(page_el, ts_lines, llm_chars, all_ts_words) -> str:
    """Build OcrElement tree using Tesseract bboxes + LLM text.
    Maps LLM characters 1:1 to Tesseract word positions (top-to-bottom, left-to-right).
    Returns full page text string."""
    from ocrmypdf.models.ocr_element import OcrElement, OcrClass, BoundingBox

    char_idx = 0
    full_parts = []

    for line_info in ts_lines:
        words = line_info['words']
        if not words:
            continue

        l_min_x = min(w['bbox'].left for w in words)
        l_min_y = min(w['bbox'].top for w in words)
        l_max_x = max(w['bbox'].right for w in words)
        l_max_y = max(w['bbox'].bottom for w in words)
        line_bbox = BoundingBox(l_min_x, l_min_y, l_max_x, l_max_y)
        line_el = OcrElement(ocr_class=OcrClass.LINE, bbox=line_bbox)

        line_chars = []
        for w in words:
            if char_idx >= len(llm_chars):
                break
            # Map one LLM character to this Tesseract bbox
            word_el = OcrElement(
                ocr_class=OcrClass.WORD,
                bbox=w['bbox'],
                text=llm_chars[char_idx],
                confidence=0.9,
            )
            line_el.children.append(word_el)
            line_chars.append(llm_chars[char_idx])
            char_idx += 1

        if line_chars:
            page_el.children.append(line_el)
            full_parts.append(''.join(line_chars))

    return '\n'.join(full_parts)


def _find_tesseract() -> str | None:
    """Find Tesseract binary. Returns path or None."""
    import os
    import shutil

    for path in [
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        os.path.expandvars(r'%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe'),
    ]:
        if os.path.exists(path):
            return path
    return shutil.which('tesseract')


def _tesseract_word_boxes(image_path) -> list[dict]:
    """Run Tesseract in TSV mode to get per-word bounding boxes.
    Returns list of dicts: [{'words': [{'bbox': BoundingBox, 'text': str, 'conf': int}, ...]}, ...]"""
    import subprocess
    from ocrmypdf.models.ocr_element import BoundingBox

    tess = _find_tesseract()
    if not tess:
        return _fallback_layout(image_path)

    try:
        r = subprocess.run(
            [tess, str(image_path), 'stdout', '-l', 'chi_sim+eng', '--psm', '6', 'tsv'],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
        )
        if r.returncode != 0:
            return _fallback_layout(image_path)

        # Parse TSV: level page_num block_num par_num line_num word_num left top width height conf text
        raw_words = []
        for raw_line in r.stdout.strip().split('\n')[1:]:  # skip header
            cols = raw_line.split('\t')
            if len(cols) < 12:
                continue
            level = int(cols[0])
            if level != 5:  # word level
                continue
            try:
                left = int(cols[6])
                top = int(cols[7])
                w = int(cols[8])
                h = int(cols[9])
                conf = int(float(cols[10]))
                text = cols[11].strip()
                line_num = int(cols[4])
                raw_words.append({
                    'text': text,
                    'conf': conf,
                    'bbox': BoundingBox(left, top, left + w, top + h),
                    'line_num': line_num,
                })
            except (ValueError, IndexError):
                continue

        if not raw_words:
            return _fallback_layout(image_path)

        # Group words by line number
        lines_dict = {}
        for w_info in raw_words:
            ln = w_info['line_num']
            if ln not in lines_dict:
                lines_dict[ln] = []
            lines_dict[ln].append(w_info)

        # Sort lines
        result = []
        for ln in sorted(lines_dict.keys()):
            words = lines_dict[ln]
            # Sort words left-to-right
            words.sort(key=lambda w: w['bbox'].left)
            result.append({'words': words})

        return result

    except Exception:
        return _fallback_layout(image_path)


def _fallback_layout(image_path) -> list[dict]:
    """Fallback: create evenly-spaced regions when Tesseract is unavailable."""
    from PIL import Image
    from ocrmypdf.models.ocr_element import BoundingBox

    with Image.open(image_path) as img:
        w, h = img.size

    margin_h = h * 0.05
    num_lines = 30
    line_h = (h - 2 * margin_h) / num_lines

    result = []
    for i in range(num_lines):
        y = margin_h + i * line_h
        bbox = BoundingBox(margin_h, y, w - margin_h, y + line_h)
        result.append({
            'words': [{'text': '', 'conf': 0, 'bbox': bbox}],
        })
    return result


def _call_llm_sync(endpoint: str, model: str, api_key: str, img_b64: str, lang: str) -> str | None:
    """Synchronous wrapper around the LLM API call.
    Retries on model-unloaded errors with exponential backoff."""
    import httpx
    import time as _time

    lang_hint = "Chinese and English" if "chi_sim" in lang else "English"

    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                },
                {
                    "type": "text",
                    "text": (
                        f"Extract ALL text from this image. This is a scanned book page in {lang_hint}. "
                        "Preserve the original text layout, line breaks, and structure. "
                        "Do not add commentary. Output ONLY the extracted text."
                    ),
                },
            ],
        }],
        "max_tokens": 4096,
        "temperature": 0,
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    max_retries = 5
    for attempt in range(1, max_retries + 1):
        try:
            resp = httpx.post(
                f"{endpoint.rstrip('/')}/v1/chat/completions",
                json=body,
                headers=headers,
                timeout=120,
            )
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices", [])
                if not choices:
                    return None
                content = choices[0].get("message", {}).get("content", "")
                return content if content else None

            err_text = (resp.text or "")[:300].lower()
            if "model" in err_text and (
                "unloaded" in err_text
                or "not loaded" in err_text
                or "canceled" in err_text
                or "cancelled" in err_text
            ):
                if attempt < max_retries:
                    delay = min(2 ** attempt, 30)
                    log.info(
                        f"LLM OCR page: model unloaded, retrying in {delay}s (attempt {attempt}/{max_retries})"
                    )
                    _time.sleep(delay)
                    continue
            log.warning(f"LLM OCR page failed: HTTP {resp.status_code}")
            return None
        except Exception as e:
            log.warning(f"LLM OCR page error (attempt {attempt}): {e}")
            if attempt < max_retries:
                _time.sleep(min(2 ** attempt, 30))
                continue
            return None

    return None
