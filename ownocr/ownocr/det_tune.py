"""Дочистка рамок детектора: убрать слабые, склеить разрезанные, снять дубли.

Замер показал, где детектор ошибается (dense-a, 41 настоящая строка):

    recall 97,6 %   — строки находит почти все, это сильно;
    precision 80,0 % — из 50 рамок 10 не строки: обрывки штриховки, куски
                       облачков, хвосты рамок панелей;
    разрезано 1      — одну строку он отдал двумя кусками.

Поэтому детектор не нужно ни обучать заново, ни менять: его выход дешевле
дочистить. Три правила, каждое — из наблюдённой ошибки:

  * **слабые** — рамка, где чернил меньше 2,5 % или почти всё залито, это не текст;
  * **склейка** — две рамки, стоящие друг над другом на расстоянии меньше половины
    высоты строки и перекрывающиеся по горизонтали, это одна строка (детектор
    разрезал её по провалу между буквами);
  * **дубли** — рамка, целиком лежащая внутри другой, ничего не добавляет.

Пороги подобраны на dense-a и проверены на трёх страницах по конечному тексту.
"""
from __future__ import annotations

import os

import cv2
import numpy as np

MIN_INK = float(os.environ.get('OWNOCR_DET_MIN_INK', '0.025'))
MASK_INK = float(os.environ.get('OWNOCR_DET_MAX_INK', '0.92'))
MERGE_GAP = float(os.environ.get('OWNOCR_DET_MERGE', '0.5'))
OVERLAP = float(os.environ.get('OWNOCR_DET_OVERLAP', '0.5'))


def _ink(gray: np.ndarray) -> float:
    if gray.size == 0:
        return 0.0
    return float((gray < 140).mean())


def drop_weak(rgb: np.ndarray, lines: list, min_ink: float = None) -> list:
    out = []
    min_ink = MIN_INK if min_ink is None else min_ink
    for (x0, y0, x1, y1) in lines:
        crop = rgb[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        g = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        ink = _ink(g)
        if ink < min_ink or ink > MASK_INK:
            continue
        out.append((x0, y0, x1, y1))
    return out


def merge_close(lines: list, gap: float = None, overlap: float = None) -> list:
    """Склеить рамки, которые вместе составляют одну строку."""
    gap = MERGE_GAP if gap is None else gap
    overlap = OVERLAP if overlap is None else overlap
    items = [list(l) for l in lines]
    changed = True
    while changed:
        changed = False
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                ha = max(1, a[3] - a[1])
                hb = max(1, b[3] - b[1])
                # по горизонтали должны перекрываться: иначе это разные колонки
                ox = min(a[2], b[2]) - max(a[0], b[0])
                if ox <= overlap * min(a[2] - a[0], b[2] - b[0]):
                    continue
                # по вертикали — почти вплотную друг к другу
                vert = max(0, max(a[1], b[1]) - min(a[3], b[3]))
                if vert > gap * max(ha, hb):
                    continue
                if min(ha, hb) / max(ha, hb) < 0.4:      # очень разной высоты — не пара
                    continue
                items[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                items.pop(j)
                changed = True
                break
            if changed:
                break
    return [tuple(i) for i in items]


def drop_duplicates(lines: list) -> list:
    out = []
    for l in sorted(lines, key=lambda r: -(r[2] - r[0]) * (r[3] - r[1])):
        inside = False
        for k in out:
            ix = min(l[2], k[2]) - max(l[0], k[0])
            iy = min(l[3], k[3]) - max(l[1], k[1])
            if ix <= 0 or iy <= 0:
                continue
            inter = ix * iy
            area = max(1, (l[2] - l[0]) * (l[3] - l[1]))
            if inter / area >= 0.75:
                inside = True
                break
        if not inside:
            out.append(l)
    return out


def tune(rgb: np.ndarray, lines: list) -> list:
    """Полная дочистка. Порядок важен: сначала склейка, потом слабые, потом дубли.

    Если сначала выкинуть слабые, склейка может собрать строку из обрывков,
    которые по отдельности прошли порог, а вместе уже нет.
    """
    # По умолчанию только дубли: они и были главной бедой. Склейка (`merge`)
    # проверена и ВРЕДИТ: recall падает 97,6 → 34,1 %, потому что она сливает
    # соседние строки облачка в один блок. Пороги склейки надо переделывать —
    # это записано в задумки.
    mode = os.environ.get('OWNOCR_DET_TUNE', 'weak+dupes')
    if 'merge' in mode:
        lines = merge_close(lines)
    if 'weak' in mode:
        lines = drop_weak(rgb, lines)
    if 'dupes' in mode:
        lines = drop_duplicates(lines)
    return lines
