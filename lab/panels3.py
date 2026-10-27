"""Рамки панелей по контурам рисунка — порядок чтения как в манге.

Зачем: две панели рядом могут иметь надписи на почти одинаковой высоте, и по
тексту их не разделить. На странице 16 из-за этого «Я ТОЖЕ.» (середина) читалось
после реплик левой панели, а должно — после них.

Как: страница темнеет-закрывается, берутся ВНЕШНИЕ контуры (RETR_CCOMP, верхний
уровень) площадью не меньше MIN_AREA страницы. Контур рамки панели почти
прямоугольный, поэтому проверяется доля заполнения бокса. Вложенные контуры
(надписи внутри панели, «ТРИ РАЗА» в прямоугольнике) выбрасываются — они уже
внутри панели. Затем панели сортируются как строки: сверху вниз, внутри строки
справа налево.

Если рамок нет (страница без границ), возвращается одна панель — дальше работает
прежняя логика по тексту.
"""
from __future__ import annotations

import cv2
import numpy as np

MIN_AREA = 0.02      # панель меньше 2 % страницы не панель
FILL = 0.75          # контур должен заполнять свой бокс хотя бы на 75 %
EDGE = 0.97          # бокс во всю страницу — это её рамка, не панель
MIN_W, MIN_H = 0.15, 0.10
ROW_TOL = 0.35       # доля меньшей высоты: перекрытие по вертикали = одна строка


def _area(b) -> int:
    return (b[2] - b[0]) * (b[3] - b[1])


def _inside(a, b, share: float = 0.9) -> bool:
    """a лежит внутри b на долю share."""
    ix = min(a[2], b[2]) - max(a[0], b[0])
    iy = min(a[3], b[3]) - max(a[1], b[1])
    if ix <= 0 or iy <= 0:
        return False
    return ix * iy >= share * _area(a)


def panels(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Рамки панелей в порядке чтения манги (пиксельные координаты)."""
    h, w = gray.shape
    dark = (gray < 120).astype(np.uint8) * 255
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, hierarchy = cv2.findContours(dark, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return [(0, 0, w, h)]

    boxes = []
    for i, contour in enumerate(contours):
        if hierarchy[0][i][3] != -1:                 # только внешние контуры
            continue
        area = cv2.contourArea(contour)
        if area < MIN_AREA * w * h:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < MIN_W * w or bh < MIN_H * h:
            continue
        if bw > EDGE * w and bh > EDGE * h:          # рамка страницы
            continue
        if area / float(bw * bh) < FILL:             # не прямоугольная панель
            continue
        boxes.append((x, y, x + bw, y + bh))

    # Вложенные боксы (надпись в рамке внутри панели) убираем: они уже внутри.
    boxes = [b for b in boxes
             if not any(o is not b and _outside_bigger(b, o) for o in boxes)]
    if not boxes:
        return [(0, 0, w, h)]
    return _reading_order(boxes)


def _outside_bigger(inner, outer) -> bool:
    return _area(outer) > _area(inner) * 1.05 and _inside(inner, outer)


def _reading_order(boxes) -> list[tuple[int, int, int, int]]:
    """Строки сверху вниз, внутри строки панели справа налево."""
    boxes = sorted(boxes, key=lambda b: (b[1], -b[0]))
    rows: list[list] = []
    for box in boxes:
        for row in rows:
            # перекрытие по вертикали с любой панелью строки
            if any(min(box[3], o[3]) - max(box[1], o[1]) >
                   ROW_TOL * min(box[3] - box[1], o[3] - o[1]) for o in row):
                row.append(box)
                break
        else:
            rows.append([box])
    ordered = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda b: -b[0]))
    return ordered


def assign(regions, boxes):
    """Раскладывает найденные куски текста по панелям (по центру, иначе ближайшая)."""
    groups: list[list] = [[] for _ in boxes]
    for region in regions:
        cx = (region.left + region.right) / 2
        cy = (region.top + region.bottom) / 2
        best, best_d = 0, float("inf")
        for i, (x1, y1, x2, y2) in enumerate(boxes):
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                best, best_d = i, -1.0
                break
            dx = max(x1 - cx, 0, cx - x2)
            dy = max(y1 - cy, 0, cy - y2)
            d = (dx * dx + dy * dy) ** 0.5
            if d < best_d:
                best, best_d = i, d
        groups[best].append(region)
    return [g for g in groups if g]
