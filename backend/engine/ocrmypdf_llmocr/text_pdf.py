"""Create a text-only PDF with invisible text layer positioned by estimated line heights."""

from pathlib import Path

from fpdf import FPDF
from PIL import Image


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

    Uses fpdf2 which supports CJK fonts natively via built-in Unicode font.
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
    font_size = line_h_pt * 0.7

    pdf = FPDF(unit='pt', format=(page_w_pt, page_h_pt))
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()
    # Use built-in Unicode font (supports CJK)
    pdf.add_font('Noto', '', r'C:\Windows\Fonts\msyh.ttc', uni=True)
    pdf.set_font('Noto', '', font_size)
    pdf.set_text_color(0, 0, 0)
    # Invisible text: stored in PDF but not painted on screen
    pdf._out('3 Tr')

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
