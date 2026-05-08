"""LlmOcrEngine — ocrmypdf OcrEngine using LLM vision model for text recognition.

Uses the sandwich renderer path (generate_pdf): creates a text-only PDF
with per-word positioned invisible text via pikepdf, then ocrmypdf grafts
it onto the original page image.

Text alignment uses Needleman-Wunsch DP (inspired by ahnafnafee/local-llm-pdf-ocr):
LLM output lines are optimally matched to Tesseract layout boxes using
character-count capacity estimation. Both row-major and column-major
reading orders are tried. Degenerate alignments fall back to a full-page
text box.
"""

from __future__ import annotations

import logging
import math
import re
import subprocess
from pathlib import Path

from ocrmypdf.pluginspec import OcrEngine, OrientationConfidence

from llmocr.layout import LayoutAnalyzer, LayoutLine, LayoutWord
from llmocr.llm_client import LlmApiClient

log = logging.getLogger(__name__)

# DP cost constants
_SKIP_LINE_COST = 1.0
_SKIP_BOX_COST = 0.4
_COLUMN_GAP_THRESHOLD = 0.2


class LlmOcrEngine(OcrEngine):

    @staticmethod
    def version() -> str:
        return "1.2.0"

    @staticmethod
    def creator_tag(options) -> str:
        return "LLM-OCR v1.2"

    def __str__(self) -> str:
        return "LLM OCR Engine"

    @staticmethod
    def languages(options) -> set[str]:
        return {"chi_sim", "chi_tra", "eng", "jpn", "kor", "fra", "deu", "spa"}

    @staticmethod
    def get_orientation(input_file: Path, options) -> OrientationConfidence:
        tess = LayoutAnalyzer()._find_tesseract()
        if tess:
            try:
                r = subprocess.run(
                    [tess, str(input_file), "stdout", "--psm", "0"],
                    capture_output=True, text=True, timeout=15,
                )
                out = r.stdout or r.stderr or ""
                for line in out.split("\n"):
                    if "Orientation in degrees:" in line:
                        angle = int(line.split(":")[-1].strip())
                        conf = 0.0
                        if "confidence:" in line:
                            conf = float(line.split("confidence:")[-1].strip()) / 100.0
                        return OrientationConfidence(angle=angle, confidence=conf)
            except Exception:
                pass
        return OrientationConfidence(angle=0, confidence=0.0)

    @staticmethod
    def get_deskew(input_file: Path, options) -> float:
        return 0.0

    @staticmethod
    def generate_hocr(input_file, output_hocr, output_text, options):
        raise NotImplementedError("LLM OCR does not support hOCR output")

    @staticmethod
    def generate_pdf(input_file, output_pdf, output_text, options):
        from llmocr.text_pdf import write_empty_pdf, create_text_pdf

        lang = getattr(options, "llm_ocr_lang", "chi_sim+eng")
        endpoint = getattr(options, "llm_ocr_endpoint", "http://localhost:11434")
        model = getattr(options, "llm_ocr_model", "")
        api_key = getattr(options, "llm_ocr_api_key", "")
        timeout = getattr(options, "llm_ocr_timeout", 300)

        analyzer = LayoutAnalyzer(language=lang)
        layout_lines = analyzer.analyze(input_file)

        llm_text: str | None = None
        if model:
            client = LlmApiClient(
                endpoint=endpoint, model=model, api_key=api_key, timeout=timeout,
            )
            llm_text = client.ocr_image(
                Path(input_file).read_bytes(), lang_hint=_lang_hint(lang)
            )

        # DP-align LLM lines to layout boxes
        if llm_text:
            _dp_align_text(layout_lines, llm_text)

        # Build sidecar & create PDF
        sidecar_text = "\n".join(
            "".join(w.text for w in line.words if w.text)
            for line in layout_lines if line.words
        )
        output_text.write_text(sidecar_text, encoding="utf-8")

        if not any(w.text for line in layout_lines for w in line.words):
            write_empty_pdf(output_pdf)
        else:
            create_text_pdf(output_pdf, input_file, layout_lines)

        log.info(
            "generate_pdf: pages=%d, words=%d, text_len=%d, model=%s",
            len(layout_lines),
            sum(len(l.words) for l in layout_lines),
            len(sidecar_text),
            model or "fallback",
        )
        if sidecar_text:
            log.info("generate_pdf TEXT: %s", sidecar_text[:300].replace("\n", "\\n"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lang_hint(lang: str) -> str:
    return "Chinese and English" if "chi_sim" in lang else "English"


def _normalize_llm_text(llm_text: str) -> list[str]:
    cleaned = re.sub(r"<\|[^>]*\|>", "", llm_text)
    return [s.strip() for s in cleaned.split("\n") if s and s.strip()]


# ---------------------------------------------------------------------------
# Reading-order detection  (row-major vs column-major)
# ---------------------------------------------------------------------------

def _reading_order_indices(
    boxes: list[tuple[float, float, float, float]],
) -> list[int]:
    """Column-major reading order permutation, recursing on column groups."""
    n = len(boxes)
    if n < 4:
        return sorted(range(n), key=lambda i: (boxes[i][1], boxes[i][0]))

    cx = [(boxes[i][0] + boxes[i][2]) / 2 for i in range(n)]
    sorted_idx = sorted(range(n), key=lambda i: cx[i])

    biggest_gap = 0.0
    gap_pos = -1
    for k in range(1, n):
        g = cx[sorted_idx[k]] - cx[sorted_idx[k - 1]]
        if g > biggest_gap:
            biggest_gap = g
            gap_pos = k

    if biggest_gap < _COLUMN_GAP_THRESHOLD or gap_pos < 2 or gap_pos > n - 2:
        return sorted(range(n), key=lambda i: (boxes[i][1], boxes[i][0]))

    left = sorted_idx[:gap_pos]
    right = sorted_idx[gap_pos:]
    left_perm = _reading_order_indices([boxes[i] for i in left])
    right_perm = _reading_order_indices([boxes[i] for i in right])
    return [left[i] for i in left_perm] + [right[i] for i in right_perm]


# ---------------------------------------------------------------------------
# Needleman-Wunsch DP alignment
# ---------------------------------------------------------------------------

def _estimated_capacities(
    boxes: list[tuple[float, float, float, float]],
) -> list[float]:
    areas = [max(1e-6, (b[2] - b[0]) * (b[3] - b[1])) for b in boxes]
    return areas


def _match_cost(line_chars: int, expected_chars: float) -> float:
    expected = max(1.0, expected_chars)
    actual = max(1, line_chars)
    if actual > expected:
        return (actual - expected) / actual
    return (expected - actual) / expected * 0.5


def _dp_align(
    lines: list[str],
    boxes: list[tuple[float, float, float, float]],
) -> tuple[float, dict[int, list[str]]]:
    """Monotonic Needleman-Wunsch alignment of lines → boxes.

    Returns (total_cost, {box_idx: [line_text, ...]}).
    Unmatched lines attach to nearest matched box.
    """
    N, M = len(lines), len(boxes)
    if N == 0 or M == 0:
        return 0.0, {}

    total_chars = max(1, sum(len(l) for l in lines))
    caps = _estimated_capacities(boxes)
    total_cap = sum(caps)
    expected = [c / total_cap * total_chars for c in caps]

    INF = float("inf")
    dp = [[INF] * (M + 1) for _ in range(N + 1)]
    back = [[0] * (M + 1) for _ in range(N + 1)]
    dp[0][0] = 0.0

    for j in range(1, M + 1):
        dp[0][j] = dp[0][j - 1] + _SKIP_BOX_COST
        back[0][j] = 2
    for i in range(1, N + 1):
        dp[i][0] = dp[i - 1][0] + _SKIP_LINE_COST
        back[i][0] = 1

    for i in range(1, N + 1):
        li = lines[i - 1]
        for j in range(1, M + 1):
            mc = dp[i - 1][j - 1] + _match_cost(len(li), expected[j - 1])
            sl = dp[i - 1][j] + _SKIP_LINE_COST
            sb = dp[i][j - 1] + _SKIP_BOX_COST
            best, op = mc, 0
            if sl < best:
                best, op = sl, 1
            if sb < best:
                best, op = sb, 2
            dp[i][j] = best
            back[i][j] = op

    # Backtrack
    mapping: dict[int, list[str]] = {}
    i, j = N, M
    ops: list[tuple[int, int, int]] = []
    while i > 0 or j > 0:
        op = back[i][j]
        if op == 0 and i > 0 and j > 0:
            ops.append((0, i - 1, j - 1))
            i, j = i - 1, j - 1
        elif op == 1 and i > 0:
            ops.append((1, i - 1, j - 1 if j > 0 else -1))
            i -= 1
        elif op == 2 and j > 0:
            ops.append((2, i - 1 if i > 0 else -1, j - 1))
            j -= 1
        else:
            if i > 0:
                i -= 1
            elif j > 0:
                j -= 1
    ops.reverse()

    last_matched = None
    for op, li, bj in ops:
        if op == 0:
            mapping.setdefault(bj, []).append(lines[li])
            last_matched = bj
        elif op == 1 and li >= 0:
            target = last_matched if last_matched is not None else 0
            mapping.setdefault(target, []).append(lines[li])
    return dp[N][M], mapping


# ---------------------------------------------------------------------------
# Main alignment entry point
# ---------------------------------------------------------------------------

def _dp_align_text(layout_lines: list[LayoutLine], llm_text: str) -> None:
    """Replace Tesseract word texts using DP-aligned LLM text.

    1. Normalize LLM output to lines
    2. Extract boxes (normalized bboxes from LayoutLine)
    3. DP-align: try row-major + column-major, pick lowest cost
    4. Degeneracy check: if alignment is broken, use full-page fallback
    5. Distribute matched text across word bboxes within each line
    """
    lines = _normalize_llm_text(llm_text)
    if not lines:
        return

    # Build normalized bboxes from layout lines
    boxes: list[tuple[float, float, float, float]] = []
    for ln in layout_lines:
        if ln.words:
            boxes.append((ln.bbox.left, ln.bbox.top, ln.bbox.right, ln.bbox.bottom))

    if not boxes:
        return

    # Try both orderings
    idx_row = sorted(range(len(boxes)), key=lambda i: (boxes[i][1], boxes[i][0]))
    idx_col = _reading_order_indices(boxes)

    best_cost = float("inf")
    best_mapping: dict[int, list[str]] = {}
    best_perm = idx_row

    for perm in [idx_row, idx_col]:
        ordered = [boxes[i] for i in perm]
        cost, mapping = _dp_align(lines, ordered)
        if cost < best_cost:
            best_cost = cost
            best_mapping = {perm[k]: v for k, v in mapping.items()}
            best_perm = perm

    # Degeneracy check
    matched_box_count = len(best_mapping)
    is_zero_match = matched_box_count == 0 and len(lines) > 1
    is_single_line = len(lines) == 1 and len(boxes) >= 5

    if is_zero_match or is_single_line:
        log.warning(
            "Degenerate DP alignment (lines=%d, boxes=%d, matches=%d). "
            "Using full-page fallback.",
            len(lines), len(boxes), matched_box_count,
        )
        # Put all text into the first layout line's words
        full_text = "\n".join(lines)
        first_line = layout_lines[0]
        if first_line and first_line.words:
            for w in first_line.words:
                w.text = ""
            # Distribute across only the first line's words
            _distribute_across_words(first_line.words, full_text)
        return

    # Distribute matched text across word bboxes per line
    for idx, line in enumerate(layout_lines):
        # Accept words with valid bboxes even if Tesseract text is empty
        # (needed when Surya provides line-level bboxes without text)
        tess_words = [w for w in line.words if (w.bbox.right - w.bbox.left) > 0]
        if not tess_words:
            continue

        if idx in best_mapping:
            line_text = " ".join(best_mapping[idx])
        else:
            line_text = ""

        if not line_text:
            # Keep Tesseract's original text
            line_text = "".join(w.text for w in tess_words)

        _distribute_across_words(tess_words, line_text)


def _distribute_across_words(words: list[LayoutWord], text: str) -> None:
    """Distribute `text` characters across `words` proportionally by bbox width."""
    if not words or not text:
        return
    total_bw = sum(max(w.bbox.right - w.bbox.left, 1) for w in words)
    text_len = len(text)
    offset = 0
    for w in words:
        bw = max(w.bbox.right - w.bbox.left, 1)
        chunk = max(1, round(text_len * bw / total_bw))
        chunk = min(chunk, text_len - offset)
        w.text = text[offset:offset + chunk]
        offset += chunk
    if offset < text_len:
        words[-1].text += text[offset:]
