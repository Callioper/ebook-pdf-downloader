"""Embed text layer into PDF from online API layout results (MinerU/PaddleOCR).

Uses PyMuPDF page.insert_textbox() for block-level bbox — MinerU provides
paragraph-level text within region-level bboxes. insert_textbox auto-fits
multi-line text within the rect, avoiding manual line-splitting inaccuracies.
"""

from pathlib import Path
from typing import Any, Dict, List

import fitz

PageTextBlocks = Dict[int, List[Dict[str, Any]]]

_SIMSUN_PATH = r"C:\Windows\Fonts\simsun.ttc"


def embed_api_text_layer(
    input_path: str,
    output_path: str,
    layout: PageTextBlocks,
) -> None:
    doc = fitz.open(input_path)
    has_simsun = Path(_SIMSUN_PATH).exists()

    for pg in range(len(doc)):
        page = doc[pg]
        pw = page.rect.width
        ph = page.rect.height
        blocks = layout.get(pg, [])
        if not blocks:
            continue

        if has_simsun:
            try:
                page.insert_font(fontname="F1", fontfile=_SIMSUN_PATH)
            except Exception:
                has_simsun = False

        for block in blocks:
            text = (block.get("text") or "").strip()
            if not text:
                continue
            bbox = block.get("bbox")
            if not bbox or len(bbox) != 4:
                continue

            rect = fitz.Rect(
                bbox[0] * pw,
                bbox[1] * ph,
                bbox[2] * pw,
                bbox[3] * ph,
            )
            if rect.width < 2 or rect.height < 2:
                continue

            # Auto-size font: 9pt minimum, 14pt maximum
            fs = max(9.0, min(14.0, rect.height / 12.0))

            try:
                page.insert_textbox(
                    rect,
                    text,
                    fontname="F1" if has_simsun else "helv",
                    fontsize=fs,
                    render_mode=3,
                    align=0,
                )
            except Exception:
                pass

    doc.save(output_path, garbage=3, deflate=True)
    doc.close()


def embed_with_surya_boxes(
    input_path: str,
    output_path: str,
    surya_boxes: Dict[int, List[List[float]]],
    page_texts: Dict[int, List[str]],
) -> None:
    """Embed text at Surya's precise line-level bbox positions (LLM OCR pipeline approach).

    Surya bboxes are tight around individual text lines, so insert_text + morph
    scaling works correctly (unlike MinerU's block-level bboxes).

    Args:
        input_path: Source PDF path
        output_path: Output PDF path with text layer
        surya_boxes: {page_idx: [[x0,y0,x1,y1], ...]} — normalized [0..1] Surya bboxes
        page_texts: {page_idx: ["line1 text", "line2 text", ...]} — text per line
    """
    doc = fitz.open(input_path)
    has_sim = Path(_SIMSUN_PATH).exists()

    for pg in range(len(doc)):
        page = doc[pg]
        pw = page.rect.width
        ph = page.rect.height
        boxes = surya_boxes.get(pg, [])
        texts = page_texts.get(pg, [])
        if not boxes or not texts:
            continue

        if has_sim:
            try:
                page.insert_font(fontname="F1", fontfile=_SIMSUN_PATH)
            except Exception:
                has_sim = False

        font = fitz.Font(fontfile=_SIMSUN_PATH) if has_sim else fitz.Font("helv")
        fontname = "F1" if has_sim else "helv"

        # Pair boxes with texts in reading order (both sorted)
        for i, bbox in enumerate(boxes):
            text = texts[i].strip() if i < len(texts) else ""
            if not text:
                continue

            pdf_rect = fitz.Rect(
                bbox[0] * pw, bbox[1] * ph,
                bbox[2] * pw, bbox[3] * ph,
            )
            box_w = pdf_rect.width
            box_h = pdf_rect.height
            if box_w <= 1 or box_h <= 1:
                continue

            # LLM OCR pipeline's font sizing + morph scaling for tight single-line bboxes
            ascender = getattr(font, "ascender", 1.075)
            descender = getattr(font, "descender", -0.299)
            extent_em = max(0.01, ascender - descender)
            fs = max(3.0, min(72.0, box_h / extent_em))

            baseline = fitz.Point(pdf_rect.x0, pdf_rect.y1 + descender * fs)
            natural_width = font.text_length(text, fontsize=fs)
            if natural_width <= 0:
                continue

            target_width = max(1.0, box_w * 0.98)
            scale_x = target_width / natural_width
            morph = (baseline, fitz.Matrix(scale_x, 1.0))

            try:
                page.insert_text(baseline, text, fontname=fontname, fontsize=fs, render_mode=3, morph=morph)
            except Exception:
                pass

    doc.save(output_path, garbage=3, deflate=True)
    doc.close()


def allocate_text_to_surya_boxes(
    surya_boxes: Dict[int, List[List[float]]],
    mineru_blocks: PageTextBlocks,
) -> Dict[int, List[str]]:
    """Distribute MinerU block-level text to Surya line-level bboxes.

    For each MinerU block on a page, finds all Surya boxes whose center
    falls within the block's region. Splits the block text into equal
    character chunks based on estimated line count from block height,
    allocating one chunk per matching Surya box.

    Surya boxes with no matching MinerU block get empty strings.
    MinerU blocks with no matching Surya boxes are silently dropped.

    Args:
        surya_boxes: {page_idx: [[x0,y0,x1,y1], ...]} normalized [0..1]
        mineru_blocks: {page_idx: [{"text": ..., "bbox": [x0,y0,x1,y1]}, ...]}

    Returns:
        {page_idx: ["line1 text", "line2 text", ...]} — one string per Surya box
    """
    page_texts: Dict[int, List[str]] = {}

    for pg in sorted(surya_boxes.keys()):
        boxes = surya_boxes[pg]
        blocks = mineru_blocks.get(pg, [])

        # Initialize all boxes with empty text
        texts = [""] * len(boxes)

        for block in blocks:
            block_text = (block.get("text") or "").strip()
            block_bbox = block.get("bbox")
            if not block_text or not block_bbox or len(block_bbox) != 4:
                continue

            bx0, by0, bx1, by1 = float(block_bbox[0]), float(block_bbox[1]), float(block_bbox[2]), float(block_bbox[3])

            # Find Surya boxes whose center falls within this MinerU block
            matching: list[tuple[int, float]] = []  # [(box_index, box_width)]
            for i, bbox in enumerate(boxes):
                if len(bbox) < 4:
                    continue
                sx0, sy0, sx1, sy1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                cx = (sx0 + sx1) / 2.0
                cy = (sy0 + sy1) / 2.0
                if bx0 <= cx <= bx1 and by0 <= cy <= by1:
                    box_w = max(0.001, sx1 - sx0)
                    matching.append((i, box_w))

            if not matching:
                continue

            # Width-proportional split: wider boxes get proportionally more characters
            total_w = sum(w for _, w in matching)
            text_len = len(block_text)

            # Compute proportional allocations
            alloc: list[tuple[int, int]] = []
            for j, (idx, box_w) in enumerate(matching):
                ratio = box_w / total_w
                chars = round(text_len * ratio)
                alloc.append((idx, chars))

            # Redistribute rounding loss to last box
            cursor = 0
            for j, (idx, chars) in enumerate(alloc):
                end = cursor + chars
                if j == len(alloc) - 1:
                    end = text_len
                chunk = block_text[cursor:end]
                if chunk:
                    if texts[idx]:
                        texts[idx] = texts[idx] + " " + chunk
                    else:
                        texts[idx] = chunk
                cursor = end

        page_texts[pg] = texts

    # ── Deduplicate overlapping text between adjacent lines ──
    for pg in sorted(page_texts.keys()):
        texts = page_texts[pg]
        for i in range(len(texts) - 1):
            cur = texts[i]
            nxt = texts[i + 1]
            if not cur or not nxt or len(cur) < 3 or len(nxt) < 3:
                continue
            for k in range(min(4, len(cur), len(nxt)), 1, -1):
                if cur[-k:] == nxt[:k]:
                    texts[i] = cur[:-k].rstrip()
                    break

    return page_texts


def embed_with_perbox_paddleocr(
    input_path: str,
    surya_boxes: Dict[int, List[List[float]]],
    paddle_token: str,
    dpi: int = 200,
    max_concurrency: int = 5,
    api_layout: PageTextBlocks | None = None,
) -> Dict[int, List[str]]:
    """Per-box crop OCR pipeline using PaddleOCR-VL-1.5 API.

    If api_layout is provided, skips body-text boxes (full-width lines
    already covered by spatial allocation) and fills them from layout.
    Only edge boxes (narrow, headers, partial lines) run per-box OCR.  """
    import asyncio
    import io
    import json
    import sys
    from datetime import datetime, timezone

    import fitz
    import httpx
    from PIL import Image

    doc = fitz.open(input_path)

    # ── Phase 0: classify body vs edge boxes (skip body if api_layout provided) ──
    body_boxes: Dict[int, set] = {}
    body_texts: Dict[int, List[str]] = {}
    if api_layout:
        spatial = allocate_text_to_surya_boxes(surya_boxes, api_layout)
        for pg in sorted(surya_boxes.keys()):
            boxes = surya_boxes[pg]
            sp = spatial.get(pg, [""] * len(boxes))
            body_boxes[pg] = set()
            body_texts[pg] = [""] * len(boxes)
            for i, bbox in enumerate(boxes):
                if len(bbox) < 4: continue
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
                if w > 0.5 and 0.01 < h < 0.05 and i < len(sp) and sp[i]:
                    body_boxes[pg].add(i)
                    body_texts[pg][i] = sp[i]
        total_body = sum(len(s) for s in body_boxes.values())
        if total_body:
            print(f"  [perbox] {total_body} body-text boxes -> spatial allocation (skip OCR)", flush=True)

    # ── Phase 1: prepare all crops across all pages ──
    # crop_list: [(page_idx, box_idx, png_bytes)]
    crop_list: list[tuple[int, int, bytes]] = []
    box_counts: Dict[int, int] = {}  # page_idx -> total boxes (for text array init)
    total_prepared = 0
    total_skipped = 0

    for pg in sorted(surya_boxes.keys()):
        page = doc[pg]
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        pw, ph = pix.width, pix.height
        boxes = surya_boxes[pg]
        box_counts[pg] = len(boxes)

        for i, bbox in enumerate(boxes):
            if len(bbox) < 4:
                continue
            x0 = int(max(0, bbox[0] * pw - 3))
            y0 = int(max(0, bbox[1] * ph - 3))
            x1 = int(min(pw, bbox[2] * pw + 3))
            y1 = int(min(ph, bbox[3] * ph + 3))
            if x1 <= x0 or y1 <= y0:
                continue

            # Skip body-text boxes — filled from spatial allocation
            if api_layout and pg in body_boxes and i in body_boxes[pg]:
                continue

            bw = x1 - x0
            bh = y1 - y0
            aspect = max(bw, bh) / max(1, min(bw, bh))
            if aspect > 100:
                total_skipped += 1
                continue
            min_area = max(80, int(150 * dpi * dpi / 90000))
            if bw * bh < min_area:
                total_skipped += 1
                continue
            crop = img.crop((x0, y0, x1, y1))
            if bh < 40:
                scale = 48.0 / bh
                new_w = max(8, int(bw * scale))
                crop = crop.resize((new_w, 48), Image.LANCZOS)
            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            crop_list.append((pg, i, buf.getvalue()))
            total_prepared += 1

    doc.close()

    print(f"  [perbox] {total_prepared} crops prepared ({total_skipped} skipped), starting global OCR...", flush=True)

    if not crop_list:
        return {pg: [""] * box_counts.get(pg, 0) for pg in sorted(surya_boxes.keys())}

    # ── Phase 2: global parallel OCR ──
    async def _run_global():
        sem = asyncio.Semaphore(max_concurrency)
        done_count = [0]
        total = len(crop_list)

        async def _ocr_one(client, pg, box_idx, crop_bytes):
            async with sem:
                files = {"file": (f"p{pg}_b{box_idx}.png", io.BytesIO(crop_bytes), "image/png")}
                data = {
                    "model": "PaddleOCR-VL-1.5",
                    "optionalPayload": json.dumps({
                        "useDocOrientationClassify": False,
                        "useDocUnwarping": False,
                        "useChartRecognition": False,
                    }),
                }
                try:
                    resp = await client.post(
                        "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs",
                        data=data, files=files,
                    )
                    if resp.status_code != 200:
                        return (pg, box_idx, "")
                    jid = resp.json().get("data", {}).get("jobId", "")
                    if not jid:
                        return (pg, box_idx, "")

                    url = f"https://paddleocr.aistudio-app.com/api/v2/ocr/jobs/{jid}"
                    for _ in range(120):  # 120 × 0.5s = 60s timeout
                        await asyncio.sleep(0.5)
                        r2 = await client.get(url)
                        if r2.status_code != 200:
                            continue
                        j2 = r2.json()
                        state = j2.get("data", {}).get("state", "?")
                        if state == "done":
                            jurl = j2.get("data", {}).get("resultUrl", {}).get("jsonUrl", "")
                            async with httpx.AsyncClient(timeout=30) as bc:
                                r3 = await bc.get(jurl, headers={
                                    "date": datetime.now(timezone.utc).strftime(
                                        "%a, %d %b %Y %H:%M:%S GMT"
                                    )
                                })
                                if r3.status_code != 200:
                                    return (pg, box_idx, "")
                                rec = json.loads(r3.text.strip().split("\n")[0])
                                parsing = (
                                    rec.get("result", {})
                                    .get("layoutParsingResults", [{}])[0]
                                    .get("prunedResult", {})
                                    .get("parsing_res_list", [])
                                )
                                text = (parsing[0].get("block_content") or "").strip() if parsing else ""
                                return (pg, box_idx, text)
                        elif state == "failed":
                            return (pg, box_idx, "")
                    return (pg, box_idx, "")
                except Exception as e:
                    return (pg, box_idx, "")
                finally:
                    done_count[0] += 1
                    if done_count[0] % 50 == 0:
                        print(f"  [perbox] {done_count[0]}/{total} crops processed", flush=True)

        async with httpx.AsyncClient(
            headers={"Authorization": f"bearer {paddle_token}"},
            timeout=180,
        ) as client:
            tasks = [_ocr_one(client, pg, idx, cb) for pg, idx, cb in crop_list]
            results = await asyncio.gather(*tasks)

        print(f"  [perbox] all {total} crops done", flush=True)
        return results

    loop = asyncio.new_event_loop()
    try:
        results = loop.run_until_complete(_run_global())
    finally:
        loop.close()

    # ── Phase 3: map results to pages ──
    page_texts: Dict[int, List[str]] = {}
    for pg in sorted(box_counts.keys()):
        page_texts[pg] = [""] * box_counts[pg]

    matched = 0
    for pg, box_idx, text in results:
        if text and pg in page_texts and box_idx < len(page_texts[pg]):
            page_texts[pg][box_idx] = text
            matched += 1

    total_boxes = sum(box_counts.values())

    # Merge body-text fills from spatial allocation
    if api_layout and body_texts:
        for pg in body_texts:
            if pg not in page_texts:
                page_texts[pg] = body_texts[pg]
                continue
            for i, t in enumerate(body_texts[pg]):
                if t:
                    page_texts[pg][i] = t
                    matched += 1
    print(f"  [perbox] final: {matched}/{total_boxes} ({matched*100//max(1,total_boxes)}%)", flush=True)
    return page_texts


def hybrid_perbox_with_fallback(
    input_path: str,
    surya_boxes: Dict[int, List[List[float]]],
    paddle_token: str,
    api_layout: PageTextBlocks,
    dpi: int = 200,
    max_concurrency: int = 3,
) -> Dict[int, List[str]]:
    """Per-box crop OCR with spatial-allocation fallback for empty boxes.

    For each Surya box: tries per-box PaddleOCR first. If a box gets no text,
    falls back to spatial allocation from the full-document API result.

    This combines exact per-line text (where per-box succeeds) with
    width-proportional split (where it fails), achieving near-100% match
    while keeping exact text for most lines.
    """
    page_texts = embed_with_perbox_paddleocr(
        input_path, surya_boxes, paddle_token, dpi, max_concurrency, api_layout
    )

    # Fill empty boxes AND replace low-quality per-box results with spatial fallback
    for pg in sorted(surya_boxes.keys()):
        texts = page_texts.get(pg, [])
        boxes = surya_boxes.get(pg, [])
        # Gather all boxes that need fixing: empty OR too short for their width
        fix_indices = [i for i, t in enumerate(texts) if not t]
        low_quality = []
        for i, t in enumerate(texts):
            if t and len(t) < 4 and i < len(boxes) and len(boxes[i]) >= 4:
                bw = boxes[i][2] - boxes[i][0]
                if bw > 0.15:  # wide box with tiny text = likely wrong
                    low_quality.append(i)
                    fix_indices.append(i)

        if not fix_indices:
            continue

        pg_blocks = api_layout.get(pg, [])
        if not pg_blocks:
            continue

        spatial = allocate_text_to_surya_boxes(
            {pg: surya_boxes.get(pg, [])}, {pg: pg_blocks}
        )
        spatial_texts = spatial.get(pg, [])

        filled = 0
        for i in fix_indices:
            if i < len(spatial_texts) and spatial_texts[i]:
                old = texts[i]
                texts[i] = spatial_texts[i]
                if old:
                    print(f"  [hybrid] page {pg} box[{i}]: replaced junk {old[:20]!r} with {texts[i][:30]!r}", flush=True)
                else:
                    filled += 1

        if fix_indices:
            total = len(texts)
            matched = sum(1 for t in texts if t)
            print(f"  [hybrid] page {pg}: {matched}/{total} ({len(fix_indices)} fixed from spatial fallback)", flush=True)

        page_texts[pg] = texts

    return page_texts
