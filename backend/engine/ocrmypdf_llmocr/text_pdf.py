"""Create a text-only PDF with invisible text layer positioned by estimated line heights."""

from pathlib import Path

import pikepdf
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

    Args:
        output_pdf: Path to write the text-only PDF
        page_text: Recognized text (lines separated by newlines)
        image_path: Original page image (for dimensions and DPI)
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

    pdf = pikepdf.Pdf.new()
    page = pdf.add_blank_page(page_size=(page_w_pt, page_h_pt))

    content = pikepdf.Stream(pdf, b'')
    content.write(b'3 Tr\n')
    content.write(b'BT\n')

    font_size = line_h_pt * 0.7
    content.write(f'{font_size:.2f} Tf\n'.encode('ascii'))

    for i, line_text in enumerate(lines):
        y_pt = page_h_pt - margin_pt - (i + 0.3) * line_h_pt
        x_pt = margin_pt * 0.5
        content.write(f'1 0 0 1 {x_pt:.2f} {y_pt:.2f} Tm\n'.encode('ascii'))
        hex_str = line_text.encode('utf-16-be').hex()
        content.write(f'<{hex_str}> Tj\n'.encode('ascii'))

    content.write(b'ET\n')

    page.contents_add(content)
    font_ref = pikepdf.Name('/F1')
    resources = pikepdf.Dictionary({
        '/Font': pikepdf.Dictionary({
            '/F1': pikepdf.Dictionary({
                '/Type': '/Font',
                '/Subtype': '/Type0',
                '/BaseFont': '/Courier',
                '/Encoding': '/Identity-H',
                '/DescendantFonts': pikepdf.Array([
                    pikepdf.Dictionary({
                        '/Type': '/Font',
                        '/Subtype': '/CIDFontType2',
                        '/BaseFont': '/Courier',
                        '/CIDSystemInfo': pikepdf.Dictionary({
                            '/Registry': '(Adobe)',
                            '/Ordering': '(Identity)',
                            '/Supplement': 0,
                        }),
                        '/DW': int(font_size * 0.6),
                    }),
                ]),
            }),
        }),
    })
    page.Resources = resources

    pdf.save(output_pdf)
    pdf.close()


def _write_empty_pdf(output_pdf: Path) -> None:
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    pdf.save(output_pdf)
    pdf.close()
