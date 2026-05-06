"""Create a text-only PDF with invisible text layer positioned by estimated line heights."""

import os
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import TextMode
from PIL import Image


def _find_cjk_font() -> str:
    """Find a CJK-capable TTF/OTC font on the system. Returns path or empty string."""
    candidates = [
        # Windows — prefer .ttf over .ttc (fpdf2 has subsetting issues with .ttc)
        r'C:\Windows\Fonts\simhei.ttf',
        r'C:\Windows\Fonts\simkai.ttf',
        r'C:\Windows\Fonts\simfang.ttf',
        r'C:\Windows\Fonts\STSONG.TTF',
        r'C:\Windows\Fonts\STKAITI.TTF',
        r'C:\Windows\Fonts\msyh.ttc',
        r'C:\Windows\Fonts\msyh.ttf',
        r'C:\Windows\Fonts\simsun.ttc',
        # Linux
        '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        # macOS
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/STHeiti Light.ttc',
        '/Library/Fonts/Arial Unicode.ttf',
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    # Try fontconfig on Linux
    try:
        import subprocess
        r = subprocess.run(['fc-list', ':lang=zh', 'file'], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            first = r.stdout.strip().split('\n')[0]
            path = first.split(':')[0].strip()
            if os.path.exists(path):
                return path
    except Exception:
        pass
    return ''


def create_text_only_pdf(
    output_pdf: Path,
    page_text: str,
    image_path: Path,
) -> None:
    """
    Create a single-page PDF with invisible text at estimated positions.
    The text is placed in evenly-spaced lines from top to bottom.
    This PDF is later grafted onto the original page image by ocrmypdf's
    sandwich renderer, giving each text line approximate position matching.

    Uses fpdf2 with system CJK font for Unicode text embedding.
    """
    if not page_text or not page_text.strip():
        _write_empty_pdf(output_pdf)
        return

    lines = page_text.splitlines()
    lines = [l for l in lines if l.strip()]
    if not lines:
        _write_empty_pdf(output_pdf)
        return

    with Image.open(image_path) as img:
        img_width, img_height = img.size
        dpi_x = float(img.info.get('dpi', (72, 72))[0])
        dpi_y = float(img.info.get('dpi', (72, 72))[1])

    page_w_pt = img_width / dpi_x * 72.0
    page_h_pt = img_height / dpi_y * 72.0

    margin_pt = page_h_pt * 0.05
    usable_h = page_h_pt - 2 * margin_pt
    line_h_pt = usable_h / max(len(lines), 1)
    # Invisible text — use a small fixed font size so CJK text fits in page width
    font_size = min(12.0, line_h_pt * 0.7)

    pdf = FPDF(unit='pt', format=(page_w_pt, page_h_pt))
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    font_path = _find_cjk_font()
    if font_path:
        pdf.add_font('CJK', '', font_path)
        pdf.set_font('CJK', '', font_size)
    else:
        # Fallback: use core font (no CJK glyphs but text is selectable via Unicode)
        pdf.set_font('Courier', '', font_size)

    pdf.set_text_color(0, 0, 0)
    pdf.text_mode = TextMode.INVISIBLE

    for i, line_text in enumerate(lines):
        y_pt = margin_pt + i * line_h_pt
        x_pt = margin_pt * 0.5
        pdf.set_xy(x_pt, y_pt)
        pdf.cell(w=page_w_pt - margin_pt, h=line_h_pt, text=line_text)

    pdf.output(str(output_pdf))


def _write_empty_pdf(output_pdf: Path) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.output(str(output_pdf))
