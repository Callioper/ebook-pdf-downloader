"""Text-only PDF generation using pikepdf for sandwich renderer path.

Creates a text-only PDF with invisible text positioned at exact word
bounding box positions. Uses a glyphless font for proper CID-to-Unicode
mapping without needing actual glyphs (text is invisible anyway).
"""

from __future__ import annotations

import logging
from pathlib import Path

from pikepdf import Dictionary, Name, Pdf, Stream, unparse_content_stream
from PIL import Image
from ocrmypdf.models.ocr_element import BoundingBox
from llmocr.layout import LayoutWord

from llmocr.layout import LayoutLine

log = logging.getLogger(__name__)

CHAR_ASPECT = 2

# Minimal ToUnicode CMap that maps all CIDs to themselves (identity)
_TUNICODE_CMAP = (
    b"/CIDInit /ProcSet findresource begin\n"
    b"12 dict begin\n"
    b"begincmap\n"
    b"/CIDSystemInfo\n"
    b"<< /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
    b"/CMapName /Adobe-Identity-UCS def\n"
    b"/CMapType 2 def\n"
    b"1 begincodespacerange\n"
    b"<0000> <FFFF>\n"
    b"endcodespacerange\n"
    b"1 beginbfrange\n"
    b"<0000> <FFFF> <0000>\n"
    b"endbfrange\n"
    b"endcmap\n"
    b"CMapName currentdict /CMap defineresource pop\n"
    b"end\n"
    b"end\n"
)


def _build_glyphless_font(pdf: Pdf) -> Name:
    """Register a glyphless Type0 CIDFont for invisible text."""
    font_name = Name.GlyphLessFont

    # Build font descriptor with FontFile2
    fd = pdf.make_indirect(
        Dictionary(
            Ascent=1000,
            CapHeight=1000,
            Descent=-1,
            Flags=5,
            FontBBox=[0, 0, 500, 1000],
            FontName=font_name,
            ItalicAngle=0,
            StemV=80,
            Type=Name.FontDescriptor,
        )
    )

    # CIDFontType2
    cid_font = pdf.make_indirect(
        Dictionary(
            Subtype=Name.CIDFontType2,
            Type=Name.Font,
            BaseFont=font_name,
            CIDSystemInfo=Dictionary(
                Ordering="Identity",
                Registry="Adobe",
                Supplement=0,
            ),
            FontDescriptor=fd,
            DW=1000 // CHAR_ASPECT,
            CIDToGIDMap=pdf.make_stream(b"\x00\x01" * 65536),
        )
    )

    # Type0 font (top-level)
    type0 = Dictionary(
        BaseFont=font_name,
        DescendantFonts=[cid_font],
        Encoding=Name("/Identity-H"),
        Subtype=Name.Type0,
        ToUnicode=pdf.make_stream(_TUNICODE_CMAP),
        Type=Name.Font,
    )
    type0_ref = pdf.make_indirect(type0)

    return type0_ref, font_name


def _text_content_stream(
    lines: list[LayoutLine],
    scale_x: float,
    scale_y: float,
    page_h_pt: float,
) -> bytes:
    """Build PDF content stream with invisible text at per-word bbox positions."""
    import math

    ops: list[str] = []
    ops.append("BT")
    ops.append("3 Tr")  # Text rendering mode 3 = invisible

    for line in lines:
        # Merge adjacent narrow words on the same line into wider words.
        # Tesseract produces per-character word bboxes for CJK, which
        # yields character-level output when placed individually.
        # Merging them creates line-level text spans.
        merged_words: list[LayoutWord] = []
        for word in line.words:
            if not word.text or not word.text.strip():
                continue
            if merged_words and (word.bbox.left - merged_words[-1].bbox.right) < 5.0:
                # Extend previous word
                prev = merged_words[-1]
                prev.bbox.right = max(prev.bbox.right, word.bbox.right)
                prev.bbox.bottom = max(prev.bbox.bottom, word.bbox.bottom)
                prev.text += word.text
            else:
                merged_words.append(LayoutWord(
                    bbox=BoundingBox(
                        word.bbox.left, word.bbox.top,
                        word.bbox.right, word.bbox.bottom,
                    ),
                    text=word.text,
                ))
        
        for word in merged_words:
            if not word.text or not word.text.strip():
                continue
            # Convert pixel bbox to PDF points
            x_pt = word.bbox.left * scale_x
            # PDF y=0 is bottom, image y=0 is top.
            # Text baseline goes at the BOTTOM of the word bbox (image coords).
            y_pt = page_h_pt - word.bbox.bottom * scale_y
            w_pt = (word.bbox.right - word.bbox.left) * scale_x
            h_pt = (word.bbox.bottom - word.bbox.top) * scale_y

            if w_pt <= 0 or h_pt <= 0:
                continue

            fs = max(h_pt * 0.8, 4.0)

            # Horizontal stretch so text fills the word bbox width
            n_chars = len(word.text)
            if n_chars > 0:
                h_stretch = 100.0 * w_pt / n_chars / fs * CHAR_ASPECT
                h_stretch = max(h_stretch, 10.0)
                h_stretch = min(h_stretch, 500.0)
            else:
                h_stretch = 100.0

            # Encode text as UTF-16BE for CID font
            text_bytes = word.text.encode("utf-16be")

            # Use Tm (text matrix) for absolute positioning within BT/ET block
            ops.append(f"/f-0-0 {fs:.1f} Tf")
            ops.append(f"{h_stretch:.1f} Tz")
            ops.append(f"1 0 0 1 {x_pt:.2f} {y_pt:.2f} Tm")
            ops.append(f"<{text_bytes.hex()}> Tj")

    ops.append("ET")
    return "\n".join(ops).encode("latin-1")


def create_text_pdf(
    output_pdf: Path,
    image_path: Path,
    lines: list[LayoutLine],
) -> None:
    """Create a text-only PDF with invisible text at word bbox positions.

    The PDF is sized to match the image dimensions. Text is positioned
    using per-word bounding boxes from Tesseract layout analysis.
    """
    # Get image dimensions and DPI
    with Image.open(image_path) as img:
        img_w, img_h = img.size
        dpi_info = img.info.get("dpi", (72, 72))
        dpi_x = float(dpi_info[0]) if isinstance(dpi_info, (list, tuple)) else float(dpi_info)
        dpi_y = float(dpi_info[1]) if isinstance(dpi_info, (list, tuple)) else float(dpi_info)

    if dpi_x <= 0:
        dpi_x = 72
    if dpi_y <= 0:
        dpi_y = 72

    # Page dimensions in points
    page_w_pt = img_w / dpi_x * 72.0
    page_h_pt = img_h / dpi_y * 72.0
    scale_x = 72.0 / dpi_x
    scale_y = 72.0 / dpi_y

    with Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(page_w_pt, page_h_pt))

        # Register glyphless font
        font_ref, _ = _build_glyphless_font(pdf)
        pdf.pages[0].Resources = Dictionary({
            "/Font": Dictionary({"/f-0-0": font_ref}),
        })

        # Build content stream
        cs_data = _text_content_stream(lines, scale_x, scale_y, page_h_pt)
        pdf.pages[0].Contents = pdf.make_stream(cs_data)
        pdf.save(output_pdf)


def write_empty_pdf(output_pdf: Path) -> None:
    """Create an empty single-page PDF."""
    with Pdf.new() as pdf:
        pdf.add_blank_page(page_size=(72, 72))
        pdf.save(output_pdf)
