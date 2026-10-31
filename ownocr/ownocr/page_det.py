"""Детектор страницы + порядок чтения: взято из проекта KOMA/приложения.

Здесь нет обучения — только перенос уже проверенной части приложения, чтобы
свой распознаватель (курс `curriculum.py` + урок 7) мог работать **в паре** с
детектором, а не вместо него:

    страница → детектор (koma_det.onnx) → карта вероятностей текста
            → компоненты связности → боксы облачков/фрагментов
            → резка бокса на строки по проекции чернил
            → [дальше уже свой распознаватель читает каждую строку]
            → сборка реплик и порядок чтения (справа налево, сверху вниз)

Логика детектора и порядка чтения повторяет `kw2/lab/pipeline.py` (эталон
приложения v2.9.7): порог карты 0.3, отбраковка компонент < 6 px, расширение
бокса, плитки 1800 px с перекрытием 160 px, разрешение детектора 960 px.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

BUBBLE_SHIFT = 0.8


# ── детектор ─────────────────────────────────────────────────────────────────

class PageDetector:
    """Карта вероятностей текста → боксы строк. Модель читается onnxruntime."""

    def __init__(self, model_path: str, threads: int = 4):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(model_path, sess_options=opts,
                                         providers=['CPUExecutionProvider'])
        self.input_name = self.sess.get_inputs()[0].name

    def prob_map(self, rgb: np.ndarray) -> np.ndarray:
        x = rgb.astype(np.float32) / 255.0
        x = np.transpose(x, (2, 0, 1))[None]
        return self.sess.run(None, {self.input_name: x})[0][0, 0]

    def detect_page(self, rgb: np.ndarray) -> list[tuple[int, int, int, int]]:
        h_page, w_page = rgb.shape[:2]
        tile_h = 1800 if h_page > 2800 else h_page
        boxes, y = [], 0
        while True:
            h = min(tile_h, h_page - y)
            for x1, y1, x2, y2 in self._detect_tile(rgb[y:y + h]):
                boxes.append((x1, y1 + y, x2, y2 + y))
            if y + h >= h_page:
                break
            y += tile_h - 160
        return boxes

    def _detect_tile(self, tile: np.ndarray) -> list[tuple[int, int, int, int]]:
        th, tw = tile.shape[:2]
        ratio = min(1.0, 960.0 / max(tw, th))
        w = max(32, round(tw * ratio / 32) * 32)
        h = max(32, round(th * ratio / 32) * 32)
        scaled = np.array(Image.fromarray(tile).resize((w, h), Image.BILINEAR))
        prob = self.prob_map(scaled)
        ph, pw = prob.shape
        out = []
        for x1, y1, x2, y2 in _components(prob):
            out.append((int(x1 / pw * tw), int(y1 / ph * th),
                        int(x2 / pw * tw), int(y2 / ph * th)))
        return out


def _components(prob: np.ndarray, thr: float = 0.3) -> list[tuple[int, int, int, int]]:
    """Связные области карты (4 соседства) с отбраковкой мелкого шума."""
    h, w = prob.shape
    seen = np.zeros((h, w), dtype=bool)
    boxes = []
    ys, xs = np.where(prob >= thr)
    for sy, sx in zip(ys, xs):
        if seen[sy, sx]:
            continue
        stack = [(sy, sx)]
        seen[sy, sx] = True
        minx = maxx = sx
        miny = maxy = sy
        n, score = 0, 0.0
        while stack:
            y, x = stack.pop()
            n += 1
            score += prob[y, x]
            minx, maxx = min(minx, x), max(maxx, x)
            miny, maxy = min(miny, y), max(maxy, y)
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx] and prob[ny, nx] >= thr:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if n < 6 or score / n < 0.5 or maxx - minx < 2 or maxy - miny < 2:
            continue
        expand = max(2, round((maxx - minx) * (maxy - miny) * 1.5
                              / (2 * ((maxx - minx) + (maxy - miny)))))
        boxes.append((max(0, minx - expand), max(0, miny - expand),
                      min(w, maxx + expand + 1), min(h, maxy + expand + 1)))
    return sorted(boxes, key=lambda b: b[1])


def text_lines(rgb: np.ndarray, box: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
    """Резка бокса детектора на строки по проекции тёмных пикселей."""
    h_page, w_page = rgb.shape[:2]
    x1, y1, x2, y2 = box
    pad = max(2, int((y2 - y1) * 0.12))
    left, right = max(0, x1 - pad), min(w_page, x2 + pad)
    top, bottom = max(0, y1 - pad), min(h_page, y2 + pad)
    if right - left < 4 or bottom - top < 4:
        return []
    scale = min(1.0, 400.0 / (right - left))
    w, h = max(4, round((right - left) * scale)), max(4, round((bottom - top) * scale))
    small = np.array(Image.fromarray(rgb[top:bottom, left:right]).resize((w, h), Image.BILINEAR)).astype(np.float32)
    luma = (299 * small[:, :, 0] + 587 * small[:, :, 1] + 114 * small[:, :, 2]) / 1000

    def row_has_ink(y: int) -> bool:
        return int((luma[y] < 150).sum()) >= max(1, w // 60)

    runs, y = [], 0
    while y < h:
        if not row_has_ink(y):
            y += 1
            continue
        end = y
        while end < h and row_has_ink(end):
            end += 1
        runs.append([y, end])
        y = max(end, y + 1)
    if not runs:
        return [(left, top, right, bottom)]
    median = int(np.median([r[1] - r[0] for r in runs]))
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= max(1, int(median * 0.35)):
            merged[-1][1] = run[1]
        else:
            merged.append(run[:])
    lines = []
    for a, b in merged:
        if b - a < max(2, int(median * 0.4)):
            continue
        cols = np.where((luma[a:b] < 150).any(axis=0))[0]
        if not cols.size:
            continue
        px0 = int(np.clip(left + cols[0] / scale, left, right - 1))
        px1 = int(np.clip(left + (cols[-1] + 1) / scale, px0 + 1, right))
        py0 = int(np.clip(top + a / scale, top, bottom - 1))
        py1 = int(np.clip(top + b / scale, py0 + 1, bottom))
        lines.append((px0, py0, px1, py1))
    return lines or [(left, top, right, bottom)]


# ── порядок чтения ───────────────────────────────────────────────────────────

@dataclass
class Region:
    text: str
    left: float
    top: float
    right: float
    bottom: float
    score: float = 0.0


@dataclass
class Line:
    text: str
    left: float
    top: float
    right: float
    bottom: float


def _join(a: str, b: str) -> str:
    a, b = a.strip(), b.strip()
    if not a:
        return b
    if not b:
        return a
    if a.endswith(('-', '\u2010', '\u2011', '\u2013', '\u2014')):
        return a[:-1] + b
    return a + ' ' + b


def _same_bubble(a: Line, b: Line) -> bool:
    aw, bw = a.right - a.left, b.right - b.left
    ah, bh = a.bottom - a.top, b.bottom - b.top
    if min(aw, bw) <= 0 or min(ah, bh) <= 0:
        return False
    ov = min(a.right, b.right) - max(a.left, b.left)
    if ov <= 0 or ov / min(aw, bw) < 0.30:
        return False
    if abs((a.left + a.right) / 2 - (b.left + b.right) / 2) > max(aw, bw) * BUBBLE_SHIFT:
        return False
    gap = b.top - a.bottom
    if gap < -ah * 0.6 or gap > max(ah, bh) * 1.2:
        return False
    return not (ah > aw * 3 or bh > bw * 3)


def _merge_by_axis(group, by_y: bool, cut: float):
    key = (lambda r: r.top) if by_y else (lambda r: r.left)
    end = (lambda r: r.bottom) if by_y else (lambda r: r.right)
    bands = []
    for region in sorted(group, key=key):
        s, e = key(region), end(region)
        if bands and s - bands[-1][1] <= cut:
            bands[-1][1] = max(bands[-1][1], e)
            bands[-1][2].append(region)
        else:
            bands.append([s, e, [region]])
    return [b[2] for b in bands] if len(bands) > 1 else [group]


def split_panels(group, rtl: bool, depth: int = 0):
    if len(group) <= 1 or depth > 12:
        return [group]
    heights = sorted(r.bottom - r.top for r in group)
    lh = max(0.008, heights[len(heights) // 2])
    y_cut, x_cut = max(0.022, lh * 0.9), max(0.035, lh * 0.9)
    rows = _merge_by_axis(group, True, y_cut)
    if len(rows) > 1:
        return [p for part in rows for p in split_panels(part, rtl, depth + 1)]
    cols = _merge_by_axis(group, False, x_cut)
    if len(cols) > 1:
        if rtl:
            cols = cols[::-1]
        return [p for part in cols for p in split_panels(part, rtl, depth + 1)]
    return [group]


def bubbles_of(group, rtl: bool) -> list[Line]:
    """Склейка фрагментов в реплики: сначала по строкам, потом по облачкам."""
    blocks: list[list[Region]] = []
    for region in sorted(group, key=lambda r: (r.top, r.left)):
        target, best_gap = None, float('inf')
        for block in blocks:
            head = block[-1]
            lh = max(head.bottom - head.top, 0.01)
            if min(head.bottom, region.bottom) - max(head.top, region.top) <= lh * 0.35:
                continue
            bl, br = min(b.left for b in block), max(b.right for b in block)
            if region.left > br:
                gap = region.left - br
            elif region.right < bl:
                gap = region.right - bl
            else:
                gap = 0.0
            if gap > lh * 1.6 or gap < -lh * 0.9:
                continue
            if gap < best_gap:
                best_gap, target = gap, block
        if target is not None:
            target.append(region)
        else:
            blocks.append([region])

    lines: list[Line] = []
    for block in blocks:
        ordered = sorted(block, key=lambda r: -r.left if rtl else r.left)
        text = ''
        for i, part in enumerate(ordered):
            if i:
                prev = ordered[i - 1].text
                if text.endswith(('-', '\u00ad')):
                    text = text[:-1]
                elif len(part.text) <= 2 and prev[-1:].isalpha() and part.text[:1].isalpha():
                    pass
                else:
                    text += ' '
            text += part.text
        lines.append(Line(text, min(p.left for p in ordered), min(p.top for p in ordered),
                          max(p.right for p in ordered), max(p.bottom for p in ordered)))

    result: list[Line] = []
    for line in sorted(lines, key=lambda x: (x.top, x.left)):
        target, best_gap = -1, float('inf')
        for index, bubble in enumerate(result):
            if not _same_bubble(bubble, line):
                continue
            gap = line.top - bubble.bottom
            if gap < best_gap:
                best_gap, target = gap, index
        if target >= 0:
            bubble = result[target]
            result[target] = Line(_join(bubble.text, line.text),
                                  min(bubble.left, line.left), min(bubble.top, line.top),
                                  max(bubble.right, line.right), max(bubble.bottom, line.bottom))
        else:
            result.append(line)
    # Порядок чтения: сначала полосы по высоте, внутри полосы — справа налево.
    # Раньше ключ был (int(top*200), -left): три реплики на одной линии страницы
    # («ОНА ВСЁ ЕЩЁ ШЕПЧЕТ», «ГОТОВО…», «Я РАССЧИТЫВАЮ НА ВАС») попадали в
    # разные полосы из-за разницы в 0,02 высоты и вставали не в том порядке.
    # Теперь полоса — это реплики, чьи вертикальные отрезки перекрываются.
    ordered = sorted(result, key=lambda x: (x.top, x.left))
    bands: list[list[Line]] = []
    for line in ordered:
        if bands and line.top - max(b.bottom for b in bands[-1]) < -0.25 * (line.bottom - line.top):
            bands[-1].append(line)
        else:
            bands.append([line])
    out: list[Line] = []
    for band in bands:
        out += sorted(band, key=lambda x: (-x.left if rtl else x.left, x.top))
    return out


def reading_order(regions: list[Region], rtl: bool = True, min_letters: int = 2) -> list[Line]:
    """Собрать реплики и выстроить их в порядке чтения манги."""
    src = [r for r in regions if sum(c.isalnum() for c in r.text) >= min_letters]
    return [line for panel in split_panels(src, rtl) for line in bubbles_of(panel, rtl)]


def norm_box(box, w: int, h: int) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = box
    return x1 / w, y1 / h, x2 / w, y2 / h
