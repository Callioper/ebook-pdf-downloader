"""Inject hierarchical bookmarks into PDF via PyMuPDF."""
import json
import os
import shutil
import subprocess as _sp
import sys
import tempfile


def inject_bookmarks(
    pdf_path: str,
    bookmark_text: str,
    output_path: str,
    offset: int = 0,
) -> str:
    """
    Inject bookmarks into PDF.

    Args:
        pdf_path: Input PDF path.
        bookmark_text: raw bookmark text.
        output_path: Output PDF path.
        offset: Page offset (shukui_page + offset = PDF_viewer_page).

    Returns:
        Output file path.
    """
    from addbookmark.bookmark_parser import parse_bookmark_hierarchy

    outlines = parse_bookmark_hierarchy(bookmark_text)
    if not outlines:
        return output_path

    try:
        import fitz as _f

        doc = _f.open(pdf_path)
        total = len(doc)

        from addbookmark.bookmark_offset import find_toc_page_by_label
        toc_page = find_toc_page_by_label(pdf_path)

        toc_entries = []
        if toc_page >= 0:
            toc_entries.append([1, '目 录', toc_page + 1])

        for title, shukui_page, level in outlines:
            page_num = shukui_page + offset
            page_num = max(1, min(page_num, total))
            toc_entries.append([level, title, page_num])

        doc.set_toc(toc_entries)
        if output_path == pdf_path:
            fd, tmp = tempfile.mkstemp(suffix='.pdf')
            os.close(fd)
            doc.save(tmp)
            doc.close()
            shutil.move(tmp, output_path)
        else:
            doc.save(output_path)
            doc.close()
        return output_path

    except ImportError:
        pass

    python_cmd = _find_system_python()
    if not python_cmd:
        raise RuntimeError("bookmark_injector: no system Python available for fitz subprocess")

    items = [[title, shukui_page, level] for title, shukui_page, level in outlines]

    in_place = (output_path == pdf_path)

    script = (
        "import json,sys,os,tempfile,shutil\n"
        "data=json.loads(sys.stdin.buffer)\n"
        "import fitz\n"
        "doc=fitz.open(data['pdf'])\n"
        "total=len(doc)\n"
        "toc_page=-1\n"
        "for i in range(min(30,total)):\n"
        " if doc[i].get_label()=='!00001.jpg':\n"
        "  toc_page=i;break\n"
        "entries=[]\n"
        "if toc_page>=0:\n"
        " entries.append([1,chr(0x76ee)+' '+chr(0x5f55),toc_page+1])\n"
        "for t,p,l in data['items']:\n"
        " pn=max(1,min(p+data['offset'],total))\n"
        " entries.append([l,t,pn])\n"
        "doc.set_toc(entries)\n" +
        (
            "fd,tmp=tempfile.mkstemp(suffix='.pdf')\n"
            "os.close(fd)\n"
            "doc.save(tmp)\n"
            "doc.close()\n"
            "shutil.move(tmp,data['out'])\n"
            if in_place else
            "doc.save(data['out'])\n"
            "doc.close()\n"
        ) +
        "print('OK')\n"
    )
    r = _sp.run(
        [python_cmd],
        input=json.dumps({
            "pdf": pdf_path, "items": items,
            "offset": offset, "out": output_path,
        }).encode('utf-8'),
        capture_output=True, timeout=60,
    )
    if r.returncode != 0:
        stderr = r.stderr.decode('utf-8', errors='replace') if r.stderr else ''
        raise RuntimeError(f"bookmark inject subprocess failed (rc={r.returncode}): {stderr[:300]}")
    return output_path


def _find_system_python():
    """Find system Python executable (skip frozen exe)."""
    if getattr(sys, 'frozen', False):
        exe = sys.executable
        import shutil as _sh
        for cmd in ["python", "python3", "py"]:
            found = _sh.which(cmd)
            if found and os.path.abspath(found) != os.path.abspath(exe):
                return found
        return None
    return sys.executable
