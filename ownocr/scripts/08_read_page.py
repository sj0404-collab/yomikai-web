#!/usr/bin/env python3
"""ЭКСПЕРИМЕНТ: прочитать целую страницу своим движком и нарисовать, что он видит.

ЧЕСТНО О РЕЗУЛЬТАТЕ: этот путь пока сырой. Свой разрез страницы (фильтр графики →
XY-разрез → полосы строк) на настоящей манге приносит куски рисунка, и движок
читает из них мусор. Надёжно он читает СТРОКИ, а находить строки на странице —
работа детектора (в приложении для этого есть обученная модель). Поэтому все
метрики в README считаются на строках, а не на этом скрипте.

Отличие от метрик: там 41 размеченная строка, а здесь — вся страница как есть:
сам находим строки, читаем, расставляем по порядку и рисуем поверх картинки.

    python3 scripts/08_read_page.py --image /home/user/koma-lab/dense-a.jpg \
        --model model --out out/page-dense-a.png
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr.engine import OwnOCR, binarize   # noqa: E402


def looks_like_text(mask: np.ndarray, orig_bw: np.ndarray, box) -> bool:
    """Похож ли кусок страницы на текст: плотность низкая, много мелких пятен.

    Рисунок даёт большую плотность чернил и мало «буквенных» пятен; облачко с
    текстом — ровно наоборот. Без такого фильтра XY-разрез приносит куски
    картинки, и движок читает из них мусор («АЖ И2-АЖ--У ! !!!;)З%!»).
    """
    x0, y0, x1, y1 = box
    sub = mask[y0:y1, x0:x1]
    if sub.size == 0:
        return False
    density = float((sub > 0).mean())
    n, _, stats, _ = cv2.connectedComponentsWithStats(sub, 8)
    parts = [stats[i][4] for i in range(1, n)]
    small = sum(1 for a in parts if a < 0.02 * sub.size)
    return density < 0.42 and small >= 3 and len(parts) >= 4


def text_mask(bw: np.ndarray) -> np.ndarray:
    """Оставить только «буквенное»: убрать рисунок, рамки и контуры облачков.

    Рисунок и обводки — это большие связные пятна и очень длинные тонкие линии.
    Буквы — мелкие плотные пятна. Правило простое: площадь пятна меньше 3 %
    страницы, высота меньше 12 % и это не линия на пол-страницы.
    """
    H, W = bw.shape
    n, labels, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    keep = np.zeros_like(bw)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area > 0.03 * H * W:
            continue
        if h > 0.12 * H or w > 0.9 * W:
            continue
        if w > 0.5 * W and h < 6:
            continue
        keep[labels == i] = 255
    return keep


def xy_cut(mask: np.ndarray, depth: int = 0, min_side: int = 14, max_depth: int = 7):
    """Рекурсивный XY-разрез: сначала по пустым строкам, потом по пустым столбцам.

    Классика вёрстки: страница делится по самым широким промежуткам пустоты, и в
    конце остаются отдельные куски текста (облачка), а не «полосы на всю ширину»,
    где рядом стоящие реплики сливаются в одну строку.
    """
    rows = (mask > 0).sum(axis=1)
    cols = (mask > 0).sum(axis=0)
    ys = np.where(rows > 0)[0]
    xs = np.where(cols > 0)[0]
    if len(ys) < 2 or len(xs) < 2:
        return []
    sub = mask[ys[0]:ys[-1] + 1, xs[0]:xs[-1] + 1]
    if sub.shape[0] < min_side or sub.shape[1] < min_side or depth >= max_depth:
        return [(int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1)]
    r = (sub > 0).sum(axis=1)
    c = (sub > 0).sum(axis=0)
    # ищем самый широкий пустой промежуток: сначала между строками, потом столбцами
    def widest(profile):
        empty, best_gap, best_at = 0, 0, -1
        for i, v in enumerate(profile):
            if v == 0:
                empty += 1
            else:
                if empty > best_gap:
                    best_gap, best_at = empty, i - empty // 2
                empty = 0
        if empty > best_gap:
            best_gap, best_at = empty, len(profile) - empty // 2
        return best_gap, best_at
    gr, ar = widest(r)
    gc, ac = widest(c)
    if max(gr, gc) < 2:
        return [(int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1)]
    out = []
    if gr >= gc and gr >= 2:                     # режем по строкам
        top = sub[:ar]
        bottom = sub[ar:]
        out += xy_cut(top, depth + 1, min_side, max_depth)
        for (x0, y0, x1, y1) in xy_cut(bottom, depth + 1, min_side, max_depth):
            out.append((x0, y0 + ar, x1, y1 + ar))
    else:                                        # режем по столбцам
        left = sub[:, :ac]
        right = sub[:, ac:]
        out += xy_cut(left, depth + 1, min_side, max_depth)
        for (x0, y0, x1, y1) in xy_cut(right, depth + 1, min_side, max_depth):
            out.append((x0 + ac, y0, x1 + ac, y1))
    return [(x0 + int(xs[0]), y0 + int(ys[0]), x1 + int(xs[0]), y1 + int(ys[0]))
            for (x0, y0, x1, y1) in out]


def split_lines(gray: np.ndarray, min_gap: int = 3):
    """Строки страницы по горизонтальной проекции ТЕКСТОВЫХ чернил."""
    bw = text_mask(binarize(gray))
    rows = (bw > 0).sum(axis=1)
    thr = max(2, int(0.012 * bw.shape[1]))
    bands, start, prev = [], None, None
    for y, v in enumerate(rows):
        if v > thr:
            if start is None:
                start = y
            prev = y
        elif start is not None and y - prev > min_gap:
            bands.append((start, prev))
            start = None
    if start is not None:
        bands.append((start, prev))
    return [b for b in bands if b[1] - b[0] >= 8]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--image', required=True)
    ap.add_argument('--model', default=os.path.join(ROOT, 'model'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'out', 'page.png'))
    ap.add_argument('--min-conf', type=float, default=0.0)
    a = ap.parse_args()

    ocr = OwnOCR(a.model)
    gray = cv2.imread(a.image, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise SystemExit(f'не читается картинка: {a.image}')
    mask = text_mask(binarize(gray))
    blocks = [b for b in xy_cut(mask)
              if (b[2] - b[0]) > 18 and (b[3] - b[1]) > 10
              and looks_like_text(mask, mask, b)]
    blocks.sort(key=lambda b: (b[1], -b[0]))
    bands = []
    for (bx0, by0, bx1, by1) in blocks:
        sub = mask[by0:by1, bx0:bx1]
        rows = (sub > 0).sum(axis=1)
        start, prev = None, None
        for y, v in enumerate(rows):
            if v > 0:
                if start is None:
                    start = y
                prev = y
            elif start is not None and y - prev > 2:
                if prev - start >= 7:
                    bands.append((by0 + start, by0 + prev, bx0, bx1))
                start = None
        if start is not None and prev - start >= 7:
            bands.append((by0 + start, by0 + prev, bx0, bx1))
    lines = []
    for (y0, y1, bx0, bx1) in bands:
        sub = gray[max(0, y0 - 2):y1 + 3, bx0:bx1]
        # по горизонтали режем на куски-облачка: пустые столбцы длиной > 3 % ширины
        bw = text_mask(binarize(sub))
        cols = (bw > 0).sum(axis=0)
        gap = max(6, int(0.03 * bw.shape[1]))
        runs, start = [], 0
        empty = 0
        for x, v in enumerate(cols):
            empty = empty + 1 if v == 0 else 0
            if empty > gap:
                if x - empty > start:
                    runs.append((start, x - empty))
                start = x + 1
        if bw.shape[1] - start > 4:
            runs.append((start, bw.shape[1]))
        for (x0, x1) in runs:
            if x1 - x0 < 12:
                continue
            r = ocr.read_line(sub[:, max(0, x0 - 2):x1 + 2])
            if not r['text'] or sum(c.isalnum() for c in r['text']) < 2:
                continue
            if r['conf'] < a.min_conf:
                continue
            lines.append({'y': [int(y0), int(y1)], 'x': [int(bx0 + x0), int(bx0 + x1)],
                          'text': r['text'], 'conf': r['conf']})

    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    vis = cv2.resize(vis, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    for ln in lines:
        x0, x1 = ln['x'][0] * 2, ln['x'][1] * 2
        y0, y1 = ln['y'][0] * 2, ln['y'][1] * 2
        cv2.rectangle(vis, (x0, y0), (x1, y1), (60, 140, 40), 2)
        cv2.putText(vis, f'{100 * ln["conf"]:.0f}%', (x0, max(12, y0 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 140, 40), 1, cv2.LINE_AA)
    cv2.imwrite(a.out, vis)

    txt = a.out.rsplit('.', 1)[0] + '.txt'
    with open(txt, 'w', encoding='utf-8') as f:
        for i, ln in enumerate(lines, 1):
            f.write(f'{i:2d}. {ln["text"]}\n')
    json.dump(lines, open(a.out.rsplit('.', 1)[0] + '.json', 'w'), ensure_ascii=False, indent=1)

    print(f'строк найдено: {len(lines)} · средняя уверенность '
          f'{100 * float(np.mean([l["conf"] for l in lines])) if lines else 0:.0f} %')
    for i, ln in enumerate(lines[:12], 1):
        print(f'{i:2d}. [{100 * ln["conf"]:3.0f}%] {ln["text"]}')
    print('картинка:', a.out)
    print('текст:', txt)


if __name__ == '__main__':
    main()
