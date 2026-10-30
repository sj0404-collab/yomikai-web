#!/usr/bin/env python3
"""Прочитать ЦЕЛУЮ страницу своим движком и нарисовать, что он видит.

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
    bands = split_lines(gray)
    lines = []
    for (y0, y1) in bands:
        sub = gray[max(0, y0 - 2):y1 + 3]
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
            lines.append({'y': [int(y0), int(y1)], 'x': [int(x0), int(x1)],
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
