import os
from typing import Any, Dict, List, Optional


async def format_ebook(
    input_path: str,
    output_format: str = "pdf",
    output_dir: str = "",
) -> Optional[str]:
    valid_formats = {"pdf", "epub", "mobi", "cbz", "azw3"}
    if output_format not in valid_formats:
        output_format = "pdf"

    if not os.path.exists(input_path):
        return None

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    output_file = os.path.join(output_dir or os.path.dirname(input_path), f"{base_name}.{output_format}")

    if output_format == "pdf":
        if input_path.lower().endswith(".pdf"):
            return input_path
        return await _to_pdf(input_path, output_file)

    elif output_format == "epub":
        return await _to_epub(input_path, output_file)

    elif output_format == "mobi":
        pdf_path = await _to_pdf(input_path, output_file.replace(".mobi", ".pdf"))
        if pdf_path:
            return await _convert_ebook(pdf_path, "mobi", output_file)
        return None

    elif output_format == "cbz":
        return await _to_cbz(input_path, output_file)

    return None


async def _to_pdf(input_path: str, output_file: str) -> Optional[str]:
    try:
        ext = os.path.splitext(input_path)[1].lower()

        if ext in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"):
            import fitz
            doc = fitz.open()
            img = fitz.open(input_path)
            rect = img[0].rect
            page = doc.new_page(width=rect.width, height=rect.height)
            page.insert_image(rect, filename=input_path)
            doc.save(output_file)
            doc.close()
            img.close()
            return output_file

        if ext == ".epub":
            result = await _convert_ebook(input_path, "pdf", output_file)
            return result

        return input_path
    except Exception:
        return None


async def _to_epub(input_path: str, output_file: str) -> Optional[str]:
    if input_path.lower().endswith(".epub"):
        return input_path
    return await _convert_ebook(input_path, "epub", output_file)


async def _to_cbz(input_path: str, output_file: str) -> Optional[str]:
    try:
        import zipfile

        if input_path.lower().endswith(".pdf"):
            import fitz
            doc = fitz.open(input_path)
            with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, page in enumerate(doc):
                    pix = page.get_pixmap(dpi=150)
                    img_data = pix.tobytes("png")
                    zf.writestr(f"page_{i+1:04d}.png", img_data)
            doc.close()
            return output_file

        if os.path.isdir(input_path):
            images = sorted(
                f for f in os.listdir(input_path)
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp"))
            )
            with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, img_name in enumerate(images):
                    zf.write(os.path.join(input_path, img_name), f"page_{i+1:04d}{os.path.splitext(img_name)[1]}")
            return output_file

        return None
    except Exception:
        return None


async def _convert_ebook(input_path: str, target_format: str, output_file: str) -> Optional[str]:
    try:
        import subprocess
        cmd = ["ebook-convert", input_path, output_file]
        proc = await __import__("asyncio").create_subprocess_exec(
            *cmd,
            stdout=__import__("asyncio").subprocess.PIPE,
            stderr=__import__("asyncio").subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if os.path.exists(output_file):
            return output_file
        return None
    except FileNotFoundError:
        pass
    except Exception:
        pass

    return None
