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
        """Called by ocrmypdf for each page image."""
        import base64

        from .text_pdf import create_text_only_pdf

        img_bytes = open(input_file, 'rb').read()
        img_b64 = base64.b64encode(img_bytes).decode('utf-8')

        endpoint = getattr(options, 'llm_ocr_endpoint', 'http://localhost:11434')
        model = getattr(options, 'llm_ocr_model', '')
        api_key = getattr(options, 'llm_ocr_api_key', '')
        lang = getattr(options, 'llm_ocr_lang', 'chi_sim+eng')

        if not model:
            log.error("LLM OCR: no model configured, skipping page")
            output_text.write_text("", encoding='utf-8')
            _write_empty_pdf(output_pdf)
            return

        text = _call_llm_sync(endpoint, model, api_key, img_b64, lang)
        if text is None:
            text = ""

        output_text.write_text(text, encoding='utf-8')
        create_text_only_pdf(output_pdf, text, input_file)


def _call_llm_sync(endpoint: str, model: str, api_key: str, img_b64: str, lang: str) -> str | None:
    """Synchronous wrapper around the LLM API call. Called from worker processes."""
    import httpx

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

    try:
        resp = httpx.post(
            f"{endpoint.rstrip('/')}/v1/chat/completions",
            json=body,
            headers=headers,
            timeout=120,
        )
        if resp.status_code != 200:
            log.warning(f"LLM OCR page failed: HTTP {resp.status_code}")
            return None
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return None
        content = choices[0].get("message", {}).get("content", "")
        return content if content else None
    except Exception as e:
        log.warning(f"LLM OCR page error: {e}")
        return None


def _write_empty_pdf(output_pdf):
    """Minimal empty PDF for pages with no text."""
    import pikepdf
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    pdf.save(output_pdf)
    pdf.close()
