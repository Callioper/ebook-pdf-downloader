"""HybridAligner — Surya DetectionPredictor + Needleman-Wunsch DP alignment.
Matches ahnafnafee/local-llm-pdf-ocr src/pdf_ocr/core/aligner.py."""

import io
import logging
from typing import Optional

from PIL import Image
from surya.detection import DetectionPredictor

log = logging.getLogger(__name__)

BBox = list[float]  # [nx0, ny0, nx1, ny1] normalized 0..1

COLUMN_GAP_THRESHOLD = 0.2
SKIP_LINE_COST = 1.0
SKIP_BOX_COST = 0.4


class HybridAligner:
    """Detection-only aligner: Surya batch detect + DP line-to-box alignment."""

    def __init__(self):
        self._detector: Optional[DetectionPredictor] = None

    def _get_detector(self) -> DetectionPredictor:
        if self._detector is None:
            self._detector = DetectionPredictor()
        return self._detector

    def detect_batch(self, images_bytes: list[bytes]) -> list[list[BBox]]:
        """Batch-detect text lines on all pages in a single Surya call.
        Returns one list of normalized [x0,y0,x1,y1] per page, sorted row-major."""
        if not images_bytes:
            return []
        images = [Image.open(io.BytesIO(b)).convert("RGB") for b in images_bytes]
        sizes = [img.size for img in images]
        predictions = self._get_detector()(images)

        all_boxes: list[list[BBox]] = []
        for (img_w, img_h), pred in zip(sizes, predictions):
            boxes: list[BBox] = []
            for bbox in (pred.bboxes or []):
                x0, y0, x1, y1 = bbox.bbox
                box = [
                    max(0.0, min(1.0, x0 / img_w)),
                    max(0.0, min(1.0, y0 / img_h)),
                    max(0.0, min(1.0, x1 / img_w)),
                    max(0.0, min(1.0, y1 / img_h)),
                ]
                if (box[2] - box[0]) > 0.01 and (box[3] - box[1]) > 0.005:
                    boxes.append(box)
            boxes.sort(key=lambda b: (b[1], b[0]))
            all_boxes.append(boxes)
        return all_boxes

    def align(self, boxes: list[BBox], llm_text: str) -> list[tuple[BBox, str]]:
        """DP-align LLM text lines to Surya boxes.
        Returns [(box, text), ...] in box order, text="" for unmatched."""
        lines = _normalize_lines(llm_text)
        if not boxes and not lines:
            return []
        if not boxes:
            return [([0.0, 0.0, 1.0, 1.0], "\n".join(lines))]
        if not lines:
            return [(box, "") for box in boxes]

        candidates = [
            sorted(range(len(boxes)), key=lambda i: (boxes[i][1], boxes[i][0])),
            _reading_order_indices(boxes),
        ]

        best_cost = float("inf")
        best_perm = candidates[0]
        best_mapping: dict[int, list[str]] = {}
        best_match_count = 0
        for perm in candidates:
            ordered = [boxes[i] for i in perm]
            cost, mapping, match_count = _dp_align(lines, ordered)
            if cost < best_cost:
                best_cost, best_perm, best_mapping, best_match_count = cost, perm, mapping, match_count

        is_zero = best_match_count == 0 and len(lines) > 1
        is_single = len(lines) == 1 and len(boxes) >= 5
        if is_zero or is_single:
            log.warning(f"Degenerate alignment (lines={len(lines)} boxes={len(boxes)} matches={best_match_count})")
            return [([0.0, 0.0, 1.0, 1.0], "\n".join(lines))]

        text_per = ["" for _ in boxes]
        for perm_idx, texts in best_mapping.items():
            text_per[best_perm[perm_idx]] = " ".join(texts).strip()
        log.debug(f"DP: {len(lines)} lines -> {best_match_count}/{len(boxes)} boxes (cost={best_cost:.3f})")
        return [(box, text) for box, text in zip(boxes, text_per)]


def _normalize_lines(text) -> list[str]:
    if not text:
        return []
    if isinstance(text, str):
        raw = text.split("\n")
    else:
        raw = []
        for item in text:
            raw.extend(str(item).split("\n"))
    return [s.strip() for s in raw if s.strip()]


def _reading_order_indices(boxes: list[BBox]) -> list[int]:
    n = len(boxes)
    if n < 4:
        return sorted(range(n), key=lambda i: (boxes[i][1], boxes[i][0]))
    sorted_idx = sorted(range(n), key=lambda i: (boxes[i][0] + boxes[i][2]) / 2)
    centers = [(boxes[i][0] + boxes[i][2]) / 2 for i in sorted_idx]
    biggest_gap = 0.0
    gap_pos = -1
    for k in range(1, len(centers)):
        gap = centers[k] - centers[k - 1]
        if gap > biggest_gap:
            biggest_gap, gap_pos = gap, k
    if biggest_gap < COLUMN_GAP_THRESHOLD or gap_pos < 2 or gap_pos > n - 2:
        return sorted(range(n), key=lambda i: (boxes[i][1], boxes[i][0]))
    left = _reading_order_indices([boxes[i] for i in sorted_idx[:gap_pos]])
    right = _reading_order_indices([boxes[i] for i in sorted_idx[gap_pos:]])
    return [sorted_idx[:gap_pos][i] for i in left] + [sorted_idx[gap_pos:][i] for i in right]


def _estimated_capacities(boxes: list[BBox]) -> list[float]:
    return [max(1e-6, (b[2] - b[0]) * (b[3] - b[1])) for b in boxes]


def _match_cost(line_chars: int, expected_chars: float) -> float:
    expected = max(1.0, expected_chars)
    actual = max(1, line_chars)
    if actual > expected:
        return (actual - expected) / actual
    return (expected - actual) / expected * 0.5


def _dp_align(lines, boxes) -> tuple[float, dict[int, list[str]], int]:
    N, M = len(lines), len(boxes)
    if N == 0 or M == 0:
        return 0.0, {}, 0
    total_chars = max(1, sum(len(l) for l in lines))
    caps = _estimated_capacities(boxes)
    total_cap = sum(caps)
    expected = [c / total_cap * total_chars for c in caps]

    INF = float("inf")
    dp = [[INF] * (M + 1) for _ in range(N + 1)]
    back = [[0] * (M + 1) for _ in range(N + 1)]
    dp[0][0] = 0.0
    for j in range(1, M + 1):
        dp[0][j], back[0][j] = dp[0][j - 1] + SKIP_BOX_COST, 2
    for i in range(1, N + 1):
        dp[i][0], back[i][0] = dp[i - 1][0] + SKIP_LINE_COST, 1

    for i in range(1, N + 1):
        for j in range(1, M + 1):
            mc = dp[i-1][j-1] + _match_cost(len(lines[i-1]), expected[j-1])
            sl = dp[i-1][j] + SKIP_LINE_COST
            sb = dp[i][j-1] + SKIP_BOX_COST
            best, op = mc, 0
            if sl < best: best, op = sl, 1
            if sb < best: best, op = sb, 2
            dp[i][j], back[i][j] = best, op

    mapping: dict[int, list[str]] = {}
    i, j = N, M
    ops: list[tuple[int, int, int]] = []
    while i > 0 or j > 0:
        op = back[i][j]
        if op == 0 and i > 0 and j > 0:
            ops.append((0, i-1, j-1)); i, j = i-1, j-1
        elif op == 1 and i > 0:
            ops.append((1, i-1, j-1 if j>0 else -1)); i -= 1
        elif op == 2 and j > 0:
            ops.append((2, i-1 if i>0 else -1, j-1)); j -= 1
        else:
            if i > 0: i -= 1
            elif j > 0: j -= 1
    ops.reverse()

    last_matched = None
    match_count = 0
    for op, li, bj in ops:
        if op == 0:
            mapping.setdefault(bj, []).append(lines[li])
            last_matched, match_count = bj, match_count + 1
        elif op == 1 and li >= 0:
            target = last_matched if last_matched is not None else 0
            mapping.setdefault(target, []).append(lines[li])
    return dp[N][M], mapping, match_count
