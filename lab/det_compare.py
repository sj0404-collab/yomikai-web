#!/usr/bin/env python3
"""Сверка детекторов строк: наш ONNX-детектор против простого морфологического.

Зачем: перед тем как тащить YOLO, надо понять, ЧТО вообще теряет наш детектор.
Здесь считается одно и то же на одних и тех же ручных рамках
(`data/lines-real/boxes.json` — 41 строка с настоящей страницы манги):

  • recall    — доля размеченных строк, накрытых рамкой детектора (перекрытие ≥ 50 %);
  • precision — доля рамок детектора, которые накрывают размеченную строку;
  • мелочь    — отдельно строки высотой ≤ 12 px (именно они и страдают).

Детекторы:
  our     — рамки, которые отдал детектор приложения (взяты из прогона, файл --ours);
  morph   — OpenCV: порог, горизонтальная дилатация, компоненты (классика для комиксов);
  morph2  — то же с вертикальной склейкой в блоки по 1–3 строки (как облачко).

  python3 lab/det_compare.py --page /home/user/koma-lab/dense-a.jpg --ours boxes.json
"""
import argparse
import json
import os

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_truth(path):
    data = json.load(open(path, encoding='utf-8'))
    return [(d['x0'], d['y0'], d['x1'], d['y1'], d['text']) for d in data]


def inter(a, b):
    x0 = max(a[0], b[0]); y0 = max(a[1], b[1])
    x1 = min(a[2], b[2]); y1 = min(a[3], b[3])
    return max(0, x1 - x0) * max(0, y1 - y0)


def score(truth, boxes, thr=0.5):
    """recall/precision по перекрытию рамок (IoU не нужен: строки тонкие)."""
    hit, lost = 0, []
    for t in truth:
        area = (t[2] - t[0]) * (t[3] - t[1])
        best = 0
        for b in boxes:
            best = max(best, inter(t, b) / max(1, area))
        if best >= thr:
            hit += 1
        else:
            lost.append(t)
    used = 0
    for b in boxes:
        area = (b[2] - b[0]) * (b[3] - b[1])
        best = 0
        for t in truth:
            best = max(best, inter(t, b) / max(1, area))
        if best >= thr:
            used += 1
    return hit / max(1, len(truth)), used / max(1, len(boxes)), lost


def morph_boxes(page, merge_rows=False, dilate=1.6, min_h=6):
    img = cv2.imread(page)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # тёмный текст на светлом фоне и светлый на тёмном — берём оба знака
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if bw.mean() > 127:                       # если фон тёмный, инвертируем
        bw = 255 - bw
    kh = max(3, int(dilate * 6))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kh, 3))
    dil = cv2.dilate(bw, kernel, iterations=2)
    dil = cv2.erode(dil, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(dil, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if h < min_h or w < 8 or area < 40:
            continue
        if w / max(1, h) < 0.8:               # вертикальные полосы — не строки
            continue
        boxes.append((x, y, x + w, y + h))
    if merge_rows:
        boxes.sort(key=lambda b: b[1])
        merged = []
        for b in boxes:
            placed = False
            for i, m in enumerate(merged):
                ow = min(m[2], b[2]) - max(m[0], b[0])
                if ow > 0.5 * min(m[2] - m[0], b[2] - b[0]) and abs(b[1] - m[3]) < (b[3] - b[1]):
                    merged[i] = (min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3]))
                    placed = True
                    break
            if not placed:
                merged.append(b)
        boxes = merged
    return boxes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--page', default='/home/user/koma-lab/dense-a.jpg')
    ap.add_argument('--truth', default=os.path.join(ROOT, 'data', 'lines-real', 'boxes.json'))
    ap.add_argument('--ours', default='', help='JSON с рамками нашего детектора (x0,y0,x1,y1)')
    ap.add_argument('--show-lost', type=int, default=6)
    args = ap.parse_args()

    truth = load_truth(args.truth)
    small = [t for t in truth if (t[3] - t[1]) <= 12]
    print(f'страница: {os.path.basename(args.page)} · размечено строк {len(truth)} '
          f'(из них мелких ≤ 12 px: {len(small)})')

    rows = []
    if args.ours and os.path.exists(args.ours):
        ours = [(d['x0'], d['y0'], d['x1'], d['y1']) for d in json.load(open(args.ours, encoding='utf-8'))]
        rows.append(('наш ONNX-детектор', ours))
    rows.append(('морфология (строки)', morph_boxes(args.page)))
    rows.append(('морфология + склейка', morph_boxes(args.page, merge_rows=True)))

    for name, boxes in rows:
        rec, prec, lost = score(truth, boxes)
        rec_small = score(small, boxes)[0] if small else 0.0
        print(f'{name:22s} рамок {len(boxes):3d} · recall {100 * rec:5.1f} % · '
              f'precision {100 * prec:5.1f} % · мелкие {100 * rec_small:5.1f} %')
        for t in lost[:args.show_lost]:
            print(f'      потеряно: «{t[4]}» ({t[2] - t[0]}×{t[3] - t[1]} px)')


if __name__ == '__main__':
    main()
