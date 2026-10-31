"""Манхва — это не манга. Отдельный путь чтения длинных цветных полос.

Чем отличается и почему одним кодом не выходит:

  * страница — одна полоса высотой 9 000–20 000 px (у манги лист 750×1100);
  * текст лежит не в облачках с обводкой, а просто на рисунке: белые буквы на
    тёмно-синем, чёрные на светлом, цветные подписи в «плашках»;
  * порядок чтения — сверху вниз, без «справа налево»;
  * полностраничный чтец на такой полосе работает минутами (замер: 265 с на
    9 236 px и больше 40 минут на 19 926 px), поэтому полосу надо резать.

Здесь полоса режется на горизонтальные блоки по пустым строкам, в каждом блоке
ищутся светлые и тёмные пятна текста, из них собираются строки, и каждая строка
читается CTC-моделью «эслав» (она обучена на нашем домене) с проверкой по
словарю. Медленный собственный чтец сознательно не зовётся: он не тянет объём.
"""
from __future__ import annotations

import cv2
import numpy as np

MIN_LINE_H = 12          # px по высоте: меньше — это шум и точки


def blocks(gray: np.ndarray, max_block: int = 2200, min_gap: int = 24):
    """Режем полосу на блоки по горизонтальным пробелам.

    Длинные сцены без пробелов режем принудительно — иначе блок будет в полосу
    целиком и смысла в нарезке нет.
    """
    ink = (gray < 200).astype(np.uint8)
    rows = ink.sum(axis=1)
    empty = rows <= max(2, ink.shape[1] // 200)
    out, start, start_empty = [], 0, 0
    for y in range(1, len(empty)):
        if empty[y] and not empty[y - 1]:
            start_empty = y
        elif not empty[y] and empty[y - 1] and y - start_empty >= min_gap:
            if start_empty - start > MIN_LINE_H:
                out.append((start, start_empty))
            start = y
    if len(gray) - start > MIN_LINE_H:
        out.append((start, len(gray)))
    # принудительная нарезка слишком высоких блоков
    fine = []
    for y0, y1 in out:
        while y1 - y0 > max_block:
            fine.append((y0, y0 + max_block))
            y0 += max_block
        fine.append((y0, y1))
    return fine


def text_regions(gray: np.ndarray, min_letter: int = 6, max_letter: int = 70):
    """Пятна текста через MSER: устойчивые к цвету и к инверсии буквы.

    Порог по яркости на манхве не работает: белые буквы на синем, чёрные на
    светлом, курсив на пёстрой заливке. MSER ищет «стабильные» области, которые
    как раз совпадают с буквами, в обеих полярностях.
    """
    mser = cv2.MSER_create(delta=4, min_area=10, max_area=6000)
    _, boxes = mser.detectRegions(gray)
    mask = np.zeros(gray.shape, np.uint8)
    for x, y, w, h in boxes:
        if not (min_letter <= h <= max_letter):
            continue
        if w < 2 or w > h * 8:              # слишком вытянутые — это линии, не буквы
            continue
        cx = x + w // 2
        cy = y + h // 2
        if cx >= mask.shape[1] or cy >= mask.shape[0]:
            continue
        mask[cy, cx] = 255                  # точка в центре буквы
    # склейка букв в строку: по горизонтали широко, по вертикали узко
    line_k = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 3))
    merged = cv2.dilate(mask, line_k, iterations=2)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(merged, 8)
    regions = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if h < 8 or h > 130 or w < h * 0.6:
            continue
        pts = int((mask[y:y + h, x:x + w] > 0).sum())
        if pts < 4:                          # одиночные «буквы» — не строка
            continue
        if w / float(h) < 0.5:
            continue
        regions.append((x, y, w, h))
    return regions


def merge_rows(regions, gap: int = 6):
    """Склеиваем пятна одной строки: по вертикали рядом, по горизонтали цепочкой."""
    if not regions:
        return []
    boxes = sorted(regions, key=lambda r: (r[1], r[0]))
    used = [False] * len(boxes)
    rows = []
    for i, b in enumerate(boxes):
        if used[i]:
            continue
        x0, y0, x1, y1 = b[0], b[1], b[0] + b[2], b[1] + b[3]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j, c in enumerate(boxes):
                if used[j]:
                    continue
                cx0, cy0, cx1, cy1 = c[0], c[1], c[0] + c[2], c[1] + c[3]
                if cy0 < y1 + gap and cy1 > y0 - gap and cx0 < x1 + gap * 8 and cx1 > x0 - gap * 8:
                    x0, y0 = min(x0, cx0), min(y0, cy0)
                    x1, y1 = max(x1, cx1), max(y1, cy1)
                    used[j] = True
                    changed = True
        rows.append((x0, y0, x1 - x0, y1 - y0))
    return rows


def read_page(gray: np.ndarray, reader=None, order: str = 'top-down'):
    """Строки полосы по порядку чтения сверху вниз."""
    if reader is None:
        import os
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from ownocr.pair import CtcLineReader
        reader = CtcLineReader(os.environ.get('OWNOCR_ESLAV_MODEL', ''))
    found = []
    for y0, y1 in blocks(gray):
        part = gray[y0:y1]
        regs = merge_rows(text_regions(part))
        for x, y, w, h in regs:
            pad = max(2, h // 4)
            crop = part[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
            if crop.size == 0:
                continue
            variants = [crop]
            if crop.shape[1] >= 160:            # длинные строки читаем с растяжкой
                variants.append(cv2.resize(crop, (int(crop.shape[1] * 1.1), crop.shape[0]),
                                           interpolation=cv2.INTER_LINEAR))
            best = ('', 0.0)
            for v in variants:
                t, c = reader.read(v)
                if len(t.strip()) > len(best[0].strip()):
                    best = (t, c)
            if best[0].strip():
                found.append({'y': int(y0 + y), 'x': int(x), 'w': int(w), 'h': int(h),
                              'text': best[0].strip(), 'conf': round(float(best[1]), 3),
                              'crop': crop})
    if order == 'top-down':
        found.sort(key=lambda r: (r['y'], r['x']))
    return found
