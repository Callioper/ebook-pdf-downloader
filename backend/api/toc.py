"""TOC API — page rendering + Vision LLM extraction."""
import base64
import io
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/toc", tags=["toc"])


class RenderRequest(BaseModel):
    pdf_path: str
    start_page: int  # 0-indexed
    end_page: int


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
    """Return base64 PNGs of selected page range."""
    import fitz
    if not os.path.exists(req.pdf_path):
        raise HTTPException(404, "PDF not found")
    doc = fitz.open(req.pdf_path)
    pages = []
    for i in range(req.start_page, min(req.end_page + 1, len(doc))):
        pix = doc[i].get_pixmap(dpi=150)
        buf = io.BytesIO(pix.tobytes("png"))
        pages.append(base64.b64encode(buf.getvalue()).decode())
    doc.close()
    return RenderResponse(pages=pages, count=len(pages))


@router.post("/extract")
async def extract_toc(req: ExtractRequest):
    """Extract TOC from selected pages using Vision LLM."""
    from addbookmark.ai_vision_toc import build_vision_prompt, parse_tocify_response

    if not req.endpoint or not req.model:
        return {"bookmark": "", "error": "Vision LLM not configured"}

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
            provider=req.provider,
            endpoint=req.endpoint,
            model=req.model,
            api_key=req.api_key,
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
    """Call a Vision LLM with images + prompt. Supports OpenAI-compatible, Gemini, Anthropic."""
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
            f"{endpoint.rstrip('/')}/v1/chat/completions",
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


@router.post("/apply")
async def apply_bookmark(req: ApplyRequest):
    """Directly run AI Vision TOC extraction and inject into PDF."""
    from config import get_config
    cfg = get_config()

    if not os.path.exists(req.pdf_path):
        raise HTTPException(404, "PDF not found")

    bookmark = ""
    source = ""
    try:
        from addbookmark.ai_vision_toc import generate_toc
        bookmark, source = await generate_toc(req.pdf_path, cfg)
    except Exception as e:
        return {"ok": False, "message": f"TOC extraction failed: {str(e)[:200]}"}

    if not bookmark:
        return {"ok": False, "message": "未能提取到目录内容"}

    try:
        from addbookmark.bookmark_injector import inject_bookmarks
        inject_bookmarks(req.pdf_path, bookmark, req.pdf_path, offset=0)
    except Exception as e:
        return {"ok": False, "message": f"书签注入失败: {str(e)[:200]}"}

    lines = bookmark.strip().split("\n")
    return {"ok": True, "message": f"成功添加 {len(lines)} 条书签", "source": source}
