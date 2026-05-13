"""TOC API — page rendering + Vision LLM extraction."""
import base64
import io
import os
import time
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/toc", tags=["toc"])

# ── fitz document cache (avoids reopening PDF for every batch) ──
_doc_cache: dict[str, tuple] = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 4
_CACHE_TTL = 30  # seconds


def _get_cached_doc(pdf_path: str):
    import fitz
    now = time.time()
    with _cache_lock:
        # Evict expired
        expired = [k for k, v in _doc_cache.items() if now - v[1] > _CACHE_TTL]
        for k in expired:
            _doc_cache[k][0].close()
            del _doc_cache[k]
        if pdf_path in _doc_cache:
            doc, ts = _doc_cache[pdf_path]
            _doc_cache[pdf_path] = (doc, now)  # refresh timestamp
            return doc
        if len(_doc_cache) >= _CACHE_MAX:
            oldest = min(_doc_cache, key=lambda k: _doc_cache[k][1])
            _doc_cache[oldest][0].close()
            del _doc_cache[oldest]
        # Read into memory to avoid holding a file handle lock on Windows
        with open(pdf_path, 'rb') as f:
            data = f.read()
        doc = fitz.open(stream=data, filetype='pdf')
        _doc_cache[pdf_path] = (doc, now)
        return doc


def close_cached_doc(pdf_path: str):
    """Close and remove a specific PDF from the cache (call before file overwrite)."""
    with _cache_lock:
        if pdf_path in _doc_cache:
            _doc_cache[pdf_path][0].close()
            del _doc_cache[pdf_path]


class RenderRequest(BaseModel):
    pdf_path: str
    start_page: int  # 0-indexed
    end_page: int
    dpi: int = 48


class RenderResponse(BaseModel):
    pages: list[str]  # base64 PNG strings
    count: int


class ExtractRequest(BaseModel):
    pdf_path: str
    start_page: int
    end_page: int
    provider: str = "openai_compatible"
    endpoint: str = ""
    model: str = ""
    api_key: str = ""


class InfoRequest(BaseModel):
    pdf_path: str


@router.post("/info")
def get_pdf_info(req: InfoRequest):
    """Return total page count for a PDF."""
    import fitz
    doc = fitz.open(req.pdf_path)
    pages = len(doc)
    doc.close()
    return {"pages": pages}


@router.post("/render-pages")
def render_pages(req: RenderRequest) -> RenderResponse:
    """Return base64 JPEGs of selected page range (uses cached doc, fast)."""
    if not os.path.exists(req.pdf_path):
        raise HTTPException(404, "PDF not found")
    doc = _get_cached_doc(req.pdf_path)
    pages = []
    for i in range(req.start_page, min(req.end_page + 1, len(doc))):
        pix = doc[i].get_pixmap(dpi=req.dpi)
        buf = io.BytesIO(pix.tobytes("png"))
        pages.append(base64.b64encode(buf.getvalue()).decode())
    return RenderResponse(pages=pages, count=len(pages))


class SinglePageRequest(BaseModel):
    pdf_path: str
    page: int  # 0-indexed
    dpi: int = 48


@router.post("/render-page")
def render_page(req: SinglePageRequest):
    """Return a single page as raw PNG bytes."""
    if not os.path.exists(req.pdf_path):
        raise HTTPException(404, "PDF not found")
    doc = _get_cached_doc(req.pdf_path)
    try:
        if req.page < 0 or req.page >= len(doc):
            raise HTTPException(400, f"Page {req.page} out of range (0-{len(doc)-1})")
        pix = doc[req.page].get_pixmap(dpi=req.dpi)
        from fastapi.responses import Response
        return Response(content=pix.tobytes("png"), media_type="image/png")
    finally:
        pass  # doc is cached, don't close


@router.post("/extract")
async def extract_toc(req: ExtractRequest):
    """Extract TOC from selected pages using Vision LLM."""
    from addbookmark.ai_vision_toc import build_vision_prompt, parse_tocify_response
    from config import get_config

    # Auto-populate from server config if not provided in request
    endpoint = req.endpoint
    model = req.model
    api_key = req.api_key
    provider = req.provider

    if not endpoint or not model or not api_key:
        cfg = get_config()
        ai_cfg = cfg if isinstance(cfg, dict) else {}
        ai_provider = ai_cfg.get("ai_vision_provider", "")
        if not endpoint and ai_cfg.get("ai_vision_endpoint"):
            endpoint = ai_cfg["ai_vision_endpoint"]
        if not model:
            if ai_provider == "doubao":
                model = ai_cfg.get("ai_vision_endpoint_id", "")
            else:
                model = ai_cfg.get("ai_vision_model", "")
        if not api_key:
            if ai_provider == "doubao":
                api_key = ai_cfg.get("ai_vision_doubao_key", "")
            elif ai_provider == "zhipu":
                api_key = ai_cfg.get("ai_vision_zhipu_key", "")
            else:
                api_key = ai_cfg.get("ai_vision_api_key", "")
        if provider == "openai_compatible" and ai_provider:
            provider = ai_provider

    if not endpoint or not model:
        return {"bookmark": "", "error": "Vision LLM not configured"}

    # Map provider aliases
    if provider in ("zhipu", "ollama", "lmstudio"):
        provider = "openai_compatible"
    elif provider in ("doubao",):
        provider = "openai_compatible"

    # Render pages as PNG
    import fitz
    if not os.path.exists(req.pdf_path):
        raise HTTPException(404, "PDF not found")
    doc = fitz.open(req.pdf_path)
    images = []
    for i in range(req.start_page, min(req.end_page + 1, len(doc))):
        pix = doc[i].get_pixmap(dpi=150)
        buf = io.BytesIO(pix.tobytes("png"))
        images.append(base64.b64encode(buf.getvalue()).decode())
    doc.close()

    prompt = build_vision_prompt()

    try:
        response = await _call_vision_llm(
            images=images,
            prompt=prompt,
            provider=provider,
            endpoint=endpoint,
            model=model,
            api_key=api_key,
        )
    except Exception as e:
        return {"bookmark": "", "error": str(e)[:200]}

    bookmark = parse_tocify_response(response) if response else ""
    return {"bookmark": bookmark, "count": len(bookmark.split(chr(10))) if bookmark else 0}


async def _call_vision_llm(
    images: list[str],
    prompt: str,
    provider: str,
    endpoint: str,
    model: str,
    api_key: str,
) -> str:
    """Call a Vision LLM with images + prompt. Supports OpenAI-compatible, Gemini, Anthropic, Doubao."""
    import httpx
    import json as _json

    if provider == "gemini":
        return await _call_gemini(images, prompt, endpoint, model, api_key)
    elif provider == "anthropic":
        return await _call_anthropic(images, prompt, endpoint, model, api_key)
    else:
        return await _call_openai_compatible(images, prompt, endpoint, model, api_key)


async def _call_openai_compatible(images, prompt, endpoint, model, api_key):
    import httpx, json as _json
    content = [{"type": "text", "text": prompt}]
    for img in images:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}})
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            f"{endpoint.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 4096},
        )
        if r.status_code != 200:
            raise RuntimeError(f"Vision LLM HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["choices"][0]["message"]["content"]


async def _call_gemini(images, prompt, endpoint, model, api_key):
    import httpx, json as _json
    parts = [{"text": prompt}]
    for img in images:
        parts.append({"inline_data": {"mime_type": "image/png", "data": img}})
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            f"{endpoint.rstrip('/')}/v1beta/models/{model}:generateContent",
            params={"key": api_key},
            json={"contents": [{"parts": parts}]},
        )
        if r.status_code != 200:
            raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]


async def _call_anthropic(images, prompt, endpoint, model, api_key):
    import httpx, json as _json
    content = [{"type": "text", "text": prompt}]
    for img in images:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}})
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(
            f"{endpoint.rstrip('/')}/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": model, "max_tokens": 4096, "messages": [{"role": "user", "content": content}]},
        )
        if r.status_code != 200:
            raise RuntimeError(f"Anthropic HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["content"][0]["text"]


class ApplyRequest(BaseModel):
    pdf_path: str
    bookmark: str = ""
    offset: int = 0


@router.post("/apply")
async def apply_bookmark(req: ApplyRequest):
    """Inject bookmarks into PDF. If bookmark is provided, use it directly. Otherwise auto-extract."""
    from config import get_config
    cfg = get_config()

    if not os.path.exists(req.pdf_path):
        raise HTTPException(404, "PDF not found")

    bookmark = req.bookmark
    source = ""

    if not bookmark:
        try:
            from addbookmark.ai_vision_toc import generate_toc
            bookmark, source = await generate_toc(req.pdf_path, cfg)
        except Exception as e:
            return {"ok": False, "message": f"TOC extraction failed: {str(e)[:200]}"}

    if not bookmark:
        return {"ok": False, "message": "未能提取到目录内容"}

    try:
        from addbookmark.bookmark_injector import inject_bookmarks
        inject_bookmarks(req.pdf_path, bookmark, req.pdf_path, offset=req.offset)
    except Exception as e:
        return {"ok": False, "message": f"书签注入失败: {str(e)[:200]}"}

    lines = bookmark.strip().split("\n")
    return {"ok": True, "message": f"成功添加 {len(lines)} 条书签", "source": source}


class OpenRequest(BaseModel):
    pdf_path: str


@router.post("/open-pdf")
def open_pdf(req: OpenRequest):
    """Open the PDF with system default viewer."""
    if not os.path.exists(req.pdf_path):
        raise HTTPException(404, "PDF not found")
    os.startfile(req.pdf_path)
    return {"ok": True}


@router.post("/open-folder")
def open_folder(req: OpenRequest):
    """Open the folder containing the PDF."""
    folder = os.path.dirname(os.path.abspath(req.pdf_path))
    if not os.path.exists(folder):
        raise HTTPException(404, "Folder not found")
    os.startfile(folder)
    return {"ok": True}


class NotifyRequest(BaseModel):
    task_id: str


@router.post("/notify-done")
def notify_toc_done(req: NotifyRequest):
    """Called by TOCModal when user confirms bookmark injection, so pipeline can continue."""
    from task_store import task_store
    t = task_store.get(req.task_id)
    if t:
        task_store.update(req.task_id, {"_toc_done": True})
        return {"ok": True}
    return {"ok": False, "message": "task not found"}
