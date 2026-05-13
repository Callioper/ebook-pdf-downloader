"""Inject hierarchical bookmarks into PDF via PyMuPDF."""
import json
import os
import shutil
import subprocess as _sp
import sys
import tempfile


def _detect_offset(pdf_path: str, bookmark_text: str) -> int:
    """Auto-detect page offset between shukui pages and PDF physical pages.

    Formula: offset = (label_000001_physical_page + 1) - first_bookmark_page
    """
    try:
        import fitz
        doc = fitz.open(pdf_path)

        anchor_physical = None
        for i in range(len(doc)):
            if doc[i].get_label() == '000001.jpg':
                anchor_physical = i
                break
        doc.close()

        if anchor_physical is None:
            return 0

        lines = bookmark_text.strip().split('\n')
        anchor_shukui = None
        for line in lines:
            parts = line.split('\t')
            if len(parts) >= 2:
                try:
                    anchor_shukui = int(parts[1].strip())
                    break
                except ValueError:
                    continue

        if anchor_shukui is None:
            return 0

        return (anchor_physical + 1) - anchor_shukui
    except ImportError:
        return 0


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
        offset: Page offset, 0 = auto-detect (shukui_page + offset = PDF_viewer_page).

    Returns:
        Output file path.
    """
    from addbookmark.bookmark_parser import parse_bookmark_hierarchy

    outlines = parse_bookmark_hierarchy(bookmark_text)
    if not outlines:
        return output_path

    if offset <= 0 and bookmark_text:
        offset = _detect_offset(pdf_path, bookmark_text)

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
            if level == -1:
                page_num = shukui_page  # absolute page, no offset
                level = 1
            else:
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
        "offset=data['offset']\n"
        "if offset<=0:\n"
        " ap=None\n"
        " for i in range(len(doc)):\n"
        "  if doc[i].get_label()=='000001.jpg':\n"
        "   ap=i;break\n"
        " if ap is not None:\n"
        "  offset=(ap+1)-data['items'][0][1] if data['items'] else 0\n"
        "toc_page=-1\n"
        "for i in range(min(30,total)):\n"
        " if doc[i].get_label()=='!00001.jpg':\n"
        "  toc_page=i;break\n"
        "entries=[]\n"
        "if toc_page>=0:\n"
        " entries.append([1,chr(0x76ee)+' '+chr(0x5f55),toc_page+1])\n"
        "for t,p,l in data['items']:\n"
        " if l==-1:\n"
        "  pn=p;l=1\n"
        " else:\n"
        "  pn=max(1,min(p+offset,total))\n"
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
