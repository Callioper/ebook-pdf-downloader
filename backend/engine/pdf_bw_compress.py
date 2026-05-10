# -*- coding: utf-8 -*-
"""PDF 黑白二值化压缩工具 —— 将扫描版 PDF 图片转为 1-bit BW + FlateDecode"""

import io
import os
import zlib

import pikepdf
from PIL import Image


def bw_compress_pdf_blocking(
    input_path: str,
    output_path: str,
    half_res: bool = False,
    threshold: int = 128,
    progress_callback=None,
) -> tuple[int, int]:
    """
    将 PDF 内嵌图片转为 1-bit 黑白并用 FlateDecode 重新压缩。
    完整保留 OCR 文字层（只替换 Resources.XObject，不动 Contents）。

    Args:
        input_path:  输入 PDF 路径
        output_path: 输出 PDF 路径
        half_res:    True=半分辨率(~150DPI), False=全分辨率(~300DPI)
        threshold:   二值化阈值 (0-255)，默认 128
        progress_callback:  可选 callback(page, total) 报告进度

    Returns:
        (原始大小字节数, 压缩后大小字节数)
    """
    pdf = pikepdf.open(input_path)
    total = len(pdf.pages)

    for i, page in enumerate(pdf.pages):
        xobjects = page.Resources.get(
            pikepdf.Name.XObject, pikepdf.Dictionary()
        )
        img_name = None
        img_obj = None
        for name, obj in xobjects.items():
            if obj.get(pikepdf.Name.Subtype) == pikepdf.Name.Image:
                img_name = str(name)
                img_obj = obj
                break

        if img_obj is None:
            continue

        raw = img_obj.read_raw_bytes()
        img = Image.open(io.BytesIO(raw))

        if half_res:
            target_w = img.width // 2
            target_h = img.height // 2
            img = img.resize((target_w, target_h), Image.LANCZOS)

        gray = img.convert("L")
        bw = gray.point(lambda x: 0 if x < threshold else 255, "1")

        raw_bits = bw.tobytes()
        compressed = zlib.compress(raw_bits, 9)

        new_stream = pdf.make_stream(compressed)
        new_stream.Type = pikepdf.Name.XObject
        new_stream.Subtype = pikepdf.Name.Image
        new_stream.Width = pikepdf.Integer(bw.width)
        new_stream.Height = pikepdf.Integer(bw.height)
        new_stream.ColorSpace = pikepdf.Name.DeviceGray
        new_stream.BitsPerComponent = pikepdf.Integer(1)
        new_stream.Filter = pikepdf.Name.FlateDecode

        page.Resources.XObject[pikepdf.Name(img_name)] = new_stream

        if (i + 1) % 20 == 0 and progress_callback:
            progress_callback(i + 1, total)

    pdf.save(output_path, compress_streams=True)
    pdf.close()

    before = os.path.getsize(input_path)
    after = os.path.getsize(output_path)

    if progress_callback:
        progress_callback(total, total)

    return before, after
