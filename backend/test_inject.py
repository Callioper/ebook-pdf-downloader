import sys, os, asyncio, io, shutil
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(__file__))
from addbookmark.ai_vision_toc import generate_toc
from addbookmark.bookmark_injector import inject_bookmarks
import fitz

CONFIG = {
    "ai_vision_enabled": True,
    "ai_vision_endpoint": "http://127.0.0.1:12345/v1",
    "ai_vision_model": "sabafallah/deepseek-ocr",
    "ai_vision_api_key": "lm-studio",
    "ai_vision_provider": "openai_compatible",
    "ai_vision_max_pages": 3,
    "ai_vision_dpi": 150,
}


async def process(pdf_path, label):
    print(f"[{label}] {os.path.basename(pdf_path)}")

    doc = fitz.open(pdf_path)
    total = len(doc)
    doc.close()
    print(f"  Pages: {total}")

    b, src = await generate_toc(pdf_path, CONFIG)
    if b:
        lines = b.split("\n")
        for l in lines[:10]:
            p = l.split("\t")
            if len(p) == 2 and p[1].isdigit():
                print(f"  {p[0][:45]:45s} -> {p[1]:>4}")
            else:
                print(f"  {l}")
        if len(lines) > 10:
            print(f"  ... ({len(lines) - 10} more)")
        print(f"  Total: {len(lines)} entries, Source: {src}")

        # Get work path
        if "_original" in pdf_path:
            work = pdf_path.replace("_original.pdf", ".pdf")
            shutil.copy2(pdf_path, work)
        else:
            work = pdf_path
        inject_bookmarks(work, b, work, offset=0)

        doc = fitz.open(work)
        n = len(doc.get_toc())
        doc.close()
        print(f"  INJECTED: {n} bookmarks\n")
    else:
        print(f"  FAILED\n")


async def main():
    await process(
        r"D:\pdf\BookDownloader\ocr\米歇尔·福柯：一种挣脱自我的哲学尝试 - [日]慎改康之 (2025)_original.pdf",
        "Foucault",
    )
    await process(
        r"D:\pdf\BookDownloader\ocr\测试_original.pdf",
        "What is Female",
    )


asyncio.run(main())
