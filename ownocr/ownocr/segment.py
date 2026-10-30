"""Разрез строки на буквы «по узнаванию» — вместо резки по пятнам.

Почему не пятна: рукописные буквы в манге касаются друг друга, и связная
компонента сразу захватывает две-три буквы («НОШЕНИЯ?» приходит одним пятном).
Проекция по столбцам тоже врёт: у «Ш» и «Н» внутри есть провалы, а между
касающимися буквами провала нет.

Здесь строка режется так, как это делает человек, который узнаёт буквы: пробуем
все разумные разрезы и выбираем тот, при котором **ученик увереннее всего** в
получившихся буквах. Формально — динамическое программирование по позициям:

    стоимость разреза на позиции x   = 0,9 · «сколько там чернил»  (режем по пустому)
    стоимость куска [x, y]          = −log p(лучшая буква) + штраф за странную ширину
    итог                            = минимум суммы по всем разрезам строки

Кусок, внутри которого две буквы, ни одной буквой не объясняется («НШ» не
похожа ни на что), поэтому его цена высокая, и DP сам предпочитает разрезать.
"""
from __future__ import annotations

import numpy as np

from .features import features


def _col_ink(bw: np.ndarray) -> np.ndarray:
    col = (bw > 0).sum(axis=0).astype(np.float32)
    if col.max() > 0:
        col = col / col.max()
    return col


def letter_width(gray: np.ndarray, bw: np.ndarray) -> float:
    """Типичная ширина буквы в этой строке: высота строки × 0,72."""
    ink = (bw > 0)
    ys, xs = np.where(ink)
    if len(ys) < 4:
        return max(8.0, gray.shape[1] / 8.0)
    h = ys.max() - ys.min() + 1
    return float(max(6.0, min(gray.shape[1] / 2.0, 0.72 * h)))


def segment_line(ocr, gray: np.ndarray, bw: np.ndarray, topk: int = 5,
                 step: int = 2, min_k: float = 0.55, max_k: float = 2.15,
                 cut_cost: float = 0.9, width_pen: float = 0.6,
                 space_k: float = 0.6):
    """Вернуть список кусков: (x0, x1, топ-k классы, вероятности).

    ocr — экземпляр OwnOCR (нужен только .model и .classes).
    """
    W, H = bw.shape[1], bw.shape[0]
    if W < 8 or H < 6:
        return []
    med = letter_width(gray, bw)
    lo, hi = max(3, int(round(min_k * med))), max(5, int(round(max_k * med)))
    col = _col_ink(bw)
    col_cost = np.concatenate([[0.0], np.cumsum(col)])        # интеграл «чернильности»

    # Кандидаты на разрез: пустые столбцы (там режем охотно) и редкая сетка
    # между ними (там режем, только если модель уверена). Каждые 2 px — слишком
    # дорого: на широкой полосе это десятки тысяч кусков.
    grid = max(step, max(2, int(round(med / 3.0))))
    blanks = set(int(i) for i in np.where(col < 0.06)[0])
    positions = sorted(blanks | set(range(0, W + 1, grid)))
    if positions[-1] != W:
        positions.append(W)
    pos_set = set(positions)

    # кеш: (x, y) → (цена, топ-k классы, вероятности)
    cache: dict[tuple[int, int], tuple[float, np.ndarray, np.ndarray]] = {}

    def piece(x: int, y: int):
        key = (x, y)
        hit = cache.get(key)
        if hit is not None:
            return hit
        crop = gray[:, x:y]
        f = features(crop)
        if f is None:
            out = (12.0, None, None)
        else:
            p = ocr.model.predict_proba(f[None, :])[0]
            k = int(p.argmax())
            width = (y - x) / med
            # штраф за небуквенную ширину: кусок в две буквы модель иногда
            # «узнаёт» как одну, поэтому широкое режем охотнее
            pen = width_pen * (max(0.0, width - 1.0) ** 2 + 0.5 * max(0.0, 0.7 - width) ** 2)
            out = (-float(np.log(max(p[k], 1e-6))) + pen, None, p)
        cache[key] = out
        return out

    INF = 1e9
    best = np.full(W + 1, INF, np.float32)
    back = np.full(W + 1, -1, np.int32)
    best[0] = 0.0
    for x in positions:
        if best[x] >= INF:
            continue
        for y in range(x + lo, min(W, x + hi) + 1):
            if y != W and y not in pos_set:
                continue
            cost, _, _ = piece(x, y)
            # штраф за разрез по чернилам: режем там, где пусто
            boundary = col_cost[min(W, y)] - col_cost[max(0, y - 1)]
            v = best[x] + cost + cut_cost * float(boundary)
            if v < best[y]:
                best[y] = v
                back[y] = x
    if back[W] < 0:
        return []

    pieces, y = [], W
    while y > 0:
        x = int(back[y])
        if x < 0:
            break
        cost, _, p = piece(x, y)
        pieces.append((x, y, p))
        y = x
    pieces.reverse()

    # Где в куске настоящие чернила (кусок может включать пустые поля по краям):
    # по этому различию между кусками и находятся пробелы.
    ink_cols = (bw > 0).any(axis=0)
    out = []
    start_of_word = True
    prev_right = None
    for x, y, p in pieces:
        if p is None:
            continue
        cols = np.where(ink_cols[x:y])[0]
        if len(cols) == 0:
            prev_right = None
            start_of_word = True
            continue
        left_ink, right_ink = x + int(cols[0]), x + int(cols[-1])
        if prev_right is not None and (left_ink - prev_right) > space_k * med:
            start_of_word = True
        order = np.argsort(-p)[:topk]
        out.append((x, y, order, p[order], bool(start_of_word)))
        start_of_word = False
        prev_right = right_ink
    return out


def pieces_as_boxes(ocr, gray: np.ndarray, bw: np.ndarray, topk: int = 5):
    """Куски разреза как рамки + вероятности — для выравнивания с эталоном.

    Возвращает (boxes, probs[полная матрица классов], offsets) или (None, None, None).
    Рамки обрезаны по настоящим чернилам куска, чтобы кроп не содержал соседа.
    """
    pieces = segment_line(ocr, gray, bw, topk=topk)
    if not pieces:
        return None, None, None
    ink_cols = (bw > 0).any(axis=0)
    ink_rows = (bw > 0).any(axis=1)
    ys = np.where(ink_rows)[0]
    if len(ys) == 0:
        return None, None, None
    boxes, rows = [], []
    for pc in pieces:
        x, y = pc[0], pc[1]
        cols = np.where(ink_cols[x:y])[0]
        if len(cols) == 0:
            continue
        boxes.append([x + int(cols[0]), int(ys[0]), x + int(cols[-1]) + 1, int(ys[-1]) + 1])
        rows.append(pc)
    if not boxes:
        return None, None, None
    probs = np.zeros((len(rows), len(ocr.classes)), np.float32)
    for i, pc in enumerate(rows):
        probs[i, pc[2]] = pc[3]
    return boxes, probs, rows
