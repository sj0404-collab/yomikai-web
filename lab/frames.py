"""Нарезка страницы по рамкам панелей (чёрные линии), а не по расположению текста.

Текстовые боксы не знают, где кончается панель: две панели рядом могут иметь
надписи на разной высоте, и «сортировка по верхнему краю» путает порядок. Рамки
панелей на странице видны — ищем длинные тёмные полосы, делим по ним.
"""
from __future__ import annotations

import numpy as np
from PIL import Image


def page_array(path) -> np.ndarray:
    img = Image.open(path).convert('L')
    return np.array(img, dtype=np.float32) / 255.0


def _dark_rows(arr, x0, x1, y0, y1, share=0.5):
    band = arr[y0:y1, x0:x1] < 0.35
    frac = band.mean(1)
    return np.where(frac > share)[0] + y0


def _dark_cols(arr, x0, x1, y0, y1, share=0.5):
    band = arr[y0:y1, x0:x1] < 0.35
    frac = band.mean(0)
    return np.where(frac > share)[0] + x0


def _runs(idx):
    if len(idx) == 0:
        return []
    out, start, prev = [], idx[0], idx[0]
    for v in idx[1:]:
        if v - prev > 2:
            out.append((start, prev))
            start = v
        prev = v
    out.append((start, prev))
    return out


def panels(arr, x0, y0, x1, y1, depth=0):
    """Список прямоугольников-панелей в порядке чтения (справа налево)."""
    if depth > 8 or (x1 - x0) < 40 or (y1 - y0) < 40:
        return [(x0, y0, x1, y1)]
    rows = [r for r in _runs(_dark_rows(arr, x0, x1, y0, y1)) if r[1] - r[0] <= 25]
    if rows:
        boxes, top = [], y0
        for a, b in rows:
            if a - top > 40:
                boxes.append((x0, top, x1, a))
            top = b
        if y1 - top > 40:
            boxes.append((x0, top, x1, y1))
        if len(boxes) > 1:
            return [p for box in boxes for p in panels(arr, *box, depth=depth + 1)]
    cols = [c for c in _runs(_dark_cols(arr, x0, x1, y0, y1)) if c[1] - c[0] <= 25]
    if cols:
        boxes, left = [], x0
        for a, b in cols:
            if a - left > 40:
                boxes.append((left, y0, a, y1))
            left = b
        if x1 - left > 40:
            boxes.append((left, y0, x1, y1))
        if len(boxes) > 1:
            boxes.reverse()  # справа налево
            return [p for box in boxes for p in panels(arr, *box, depth=depth + 1)]
    return [(x0, y0, x1, y1)]


def order_regions(regions, panel_boxes, w, h):
    """Раскладывает найденные строки по панелям в порядке чтения."""
    def inside(r, box):
        cx = (r.left + r.right) / 2 * w
        cy = (r.top + r.bottom) / 2 * h
        return box[0] <= cx <= box[2] and box[1] <= cy <= box[3]

    out = []
    for box in panel_boxes:
        part = [r for r in regions if inside(r, box)]
        part.sort(key=lambda r: (r.top, -r.left))
        out.append(part)
    return [p for p in out if p]
