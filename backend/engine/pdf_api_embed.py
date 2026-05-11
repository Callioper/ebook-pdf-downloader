"""Embed text layer into PDF from online API layout results (MinerU/PaddleOCR)."""

from pathlib import Path
from typing import Any, Dict, List

import pikepdf

PageTextBlocks = Dict[int, List[Dict[str, Any]]]

_SIMSUN_PATH = r"C:\Windows\Fonts\simsun.ttc"

A4_WIDTH = 595.0
A4_HEIGHT = 842.0

DEFAULT_FONT_SIZE = 10.0
DEFAULT_LINE_HEIGHT = 14.0
DEFAULT_MARGIN_LEFT = 60.0
DEFAULT_MARGIN_TOP = 60.0


def _load_cjk_font(pdf):
    if _SIMSUN_PATH and Path(_SIMSUN_PATH).exists():
        try:
            font = pikepdf.Font(pdf, _SIMSUN_PATH)
            return font
        except Exception:
            pass
    try:
        return pikepdf.Font(pdf, "Helvetica")
    except Exception:
        return None


def embed_api_text_layer(
    input_path: str,
    output_path: str,
    layout: PageTextBlocks,
    font_size: float = DEFAULT_FONT_SIZE,
    line_height: float = DEFAULT_LINE_HEIGHT,
) -> None:
    """Embed text from API layout results into PDF as an invisible text layer.

    Args:
        input_path: Path to source PDF
        output_path: Path for output PDF with text layer
        layout: {page_index: [{"text": str, "bbox": (x0,y0,x1,y1) or None, ...}]}
        font_size: Font size in points
        line_height: Line height in points
    """
    with pikepdf.open(input_path) as pdf:
        font = _load_cjk_font(pdf)
        font_name = font.name if font else "F1"

        for page_idx, blocks in sorted(layout.items()):
            if page_idx >= len(pdf.pages):
                continue

            page = pdf.pages[page_idx]
            page_height = float(page.MediaBox[3]) if "/MediaBox" in page else A4_HEIGHT

            stream_lines = []
            stream_lines.append("/GS0 gs")

            if blocks:
                for i, block in enumerate(blocks):
                    text = block.get("text", "")
                    if not text:
                        continue

                    bbox = block.get("bbox")
                    if bbox and len(bbox) == 4:
                        x = bbox[0]
                        y = page_height - bbox[3]
                    else:
                        x = DEFAULT_MARGIN_LEFT
                        y = page_height - DEFAULT_MARGIN_TOP - i * line_height

                    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

                    block_lines = []
                    block_lines.append("BT")
                    if font:
                        block_lines.append(f"/{font_name} {font_size:.1f} Tf")
                    else:
                        block_lines.append(f"/{font_name} {font_size:.1f} Tf")
                    block_lines.append(f"{x:.1f} {y:.1f} Td ({escaped}) Tj")
                    block_lines.append("ET")
                    stream_lines.extend(block_lines)

            content_stream = pikepdf.Stream(pdf, "\n".join(stream_lines).encode("utf-8"))

            if "/Contents" in page and page.Contents is not None:
                existing = page.Contents
                if isinstance(existing, pikepdf.Array):
                    existing.append(content_stream)
                else:
                    page.Contents = pikepdf.Array([existing, content_stream])
            else:
                page.Contents = content_stream

            if "/Resources" not in page:
                page.Resources = pikepdf.Dictionary()

            resources = page.Resources
            if "/ExtGState" not in resources:
                resources.ExtGState = pikepdf.Dictionary()
            resources.ExtGState.GS0 = pikepdf.Dictionary(
                Type=pikepdf.Name.ExtGState,
                TR=pikepdf.Integer(3),
            )

            if font and "/Font" not in resources:
                resources.Font = pikepdf.Dictionary()
            if font and "/Font" in resources:
                resources.Font[pikepdf.Name(font_name)] = font

        pdf.save(output_path, compress_streams=True)
