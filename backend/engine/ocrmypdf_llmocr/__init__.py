"""ocrmypdf plugin — LLM-based OCR engine via OpenAI-compatible vision API."""

import logging

log = logging.getLogger(__name__)

from ocrmypdf import hookimpl


@hookimpl
def add_options(parser):
    group = parser.add_argument_group("LLM OCR", "LLM-based OCR options")
    group.add_argument(
        "--llm-ocr-endpoint",
        default="http://localhost:11434",
        help="LLM API endpoint (OpenAI-compatible, e.g. Ollama/LM Studio)",
    )
    group.add_argument(
        "--llm-ocr-model",
        default="",
        help="LLM model name (e.g. llava:13b, noctrex/paddleocr-vl-1.5)",
    )
    group.add_argument(
        "--llm-ocr-api-key",
        default="",
        help="API key (leave empty for local models)",
    )
    group.add_argument(
        "--llm-ocr-lang",
        default="chi_sim+eng",
        help="Language hint for OCR",
    )


@hookimpl
def check_options(options):
    if not getattr(options, 'llm_ocr_model', ''):
        log.warning("LLM OCR: no model configured (--llm-ocr-model)") 


@hookimpl
def get_ocr_engine(options):
    from .engine import LlmOcrEngine
    return LlmOcrEngine()


@hookimpl
def initialize(plugin_manager):
    pass
