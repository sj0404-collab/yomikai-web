#!/usr/bin/env python3
"""Замер детектора отдельно от распознавателя: нашёл ли он строки.

До сих пор детектор мерился только «по конечному тексту», и было непонятно, где
именно теряется: детектор не нашёл строку, или нашёл, а чтец не прочитал. Здесь
считаются обычные метрики обнаружения:

    recall    — какую долю настоящих строк нашли (IoU ≥ 0.5)
    precision — какая доля найденных рамок действительно строки
    слиплось  — сколько настоящих строк попало в одну рамку
    разрезано — сколько настоящих строк разрезано на две и больше
    лишних    — рамки, не совпавшие ни с одной настоящей строкой

Эталон берётся из `data-real/boxes.json`: там 41 рамка настоящих строк с наших
страниц. К какой странице относится рамка, определяется сравнением пикселей
кропа страницы с самим кропом строки — точно, без догадок.

    python3 scripts/25_det_bench.py
    python3 scripts/25_det_bench.py --det /home/user/koma_models/koma_det.onnx
"""
import argparse
import json
import os
import sys
import time

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ownocr.pair as pr                                      # noqa: E402
from ownocr.page_det import PageDetector                      # noqa: E402

PAGES = ['dense-a', 'dense-b', 'dense-page']
RAW = False


def same_line(det, gt) -> bool:
    """Одна ли это строка. Для узких строк IoU слишком строг: сдвиг на 2 px
    роняет его ниже 0.5. Поэтому смотрим центр и высоту."""
    dx0, dy0, dx1, dy1 = det
    gx0, gy0, gx1, gy1 = gt
    cy, cx = (dy0 + dy1) / 2, (dx0 + dx1) / 2
    if not (gx0 - 3 <= cx <= gx1 + 3 and gy0 - 3 <= cy <= gy1 + 3):
        return False
    hd, hg = max(1, dy1 - dy0), max(1, gy1 - gy0)
    return 0.55 <= hd / hg <= 1.8


def iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua else 0.0


def attach_boxes_simple():
    """Эталонные рамки строк.

    Все 41 рамка из `data-real/boxes.json` относятся к странице dense-a — это
    проверено глазами: рамки нарисованы на странице и каждая стоит на своей
    строке (скрипт `--draw`). Раньше я определял страницу автоматически и
    получал чушь, поэтому теперь эталон задан явно.
    """
    boxes = json.load(open(os.path.join(ROOT, 'data-real', 'boxes.json'), encoding='utf-8'))
    return {'dense-a': [(b['x0'], b['y0'], b['x1'], b['y1'], b['text']) for b in boxes]}


def attach_boxes(score_min: float = 0.75):
    """Какая строка с какой страницы и где именно — поиском по картинке.

    Кропы строк 41 файла; ищем каждый на трёх страницах (совпадение шаблона).
    Найденное место — и есть эталонная рамка строки: оно точнее, чем координаты
    в boxes.json, потому что проверено по пикселям.
    """
    names = [b['file'] for b in json.load(open(os.path.join(ROOT, 'data-real', 'boxes.json'),
                                              encoding='utf-8'))]
    texts = {b['file']: b['text'] for b in json.load(open(os.path.join(ROOT, 'data-real',
                                                                      'boxes.json'), encoding='utf-8'))}
    pages = {}
    for name in PAGES:
        p = os.path.join('/home/user/koma-lab', name + '.jpg')
        if os.path.exists(p):
            pages[name] = np.array(Image.open(p).convert('L'))
    out = {name: [] for name in pages}
    for f in names:
        strip = cv2.imread(os.path.join(ROOT, 'data-real', f), cv2.IMREAD_GRAYSCALE)
        if strip is None or min(strip.shape) < 8:
            continue
        best, best_page, best_loc = score_min, None, None
        for name, page in pages.items():
            if strip.shape[0] > page.shape[0] or strip.shape[1] > page.shape[1]:
                continue
            res = cv2.matchTemplate(page, strip, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if mx > best:
                best, best_page, best_loc = mx, name, loc
        if best_page:
            x0, y0 = best_loc
            out[best_page].append((x0, y0, x0 + strip.shape[1], y0 + strip.shape[0], texts[f]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--det', default='/home/user/koma_models/koma_det.onnx')
    ap.add_argument('--json', default=os.path.join(ROOT, 'out', 'det-bench.json'))
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--raw', action='store_true', help='без дочистки, как есть')
    a = ap.parse_args()

    global RAW
    RAW = a.raw
    gt = attach_boxes_simple()
    for name, rows in gt.items():
        print(f'{name}: настоящих строк {len(rows)}')
    det = PageDetector(a.det)
    report = {}
    tot = {'gt': 0, 'found': 0, 'det': 0, 'merged': 0, 'split': 0}
    for name in PAGES:
        rows = gt.get(name) or []
        if not rows:
            continue
        rgb = pr.normalize_page(np.array(Image.open(f'/home/user/koma-lab/{name}.jpg').convert('RGB')))
        t0 = time.time()
        boxes = det.detect_page(rgb)
        from ownocr.page_det import text_lines
        from ownocr.det_tune import tune
        lines = []
        for box in boxes[:400]:
            lines.extend(text_lines(rgb, box))
        if not RAW:
            lines = tune(rgb, lines)
        dt = time.time() - t0
        # для каждой настоящей строки — лучшая найденная рамка
        hits, merged, split = 0, 0, 0
        for (x0, y0, x1, y1, text) in rows:
            g = (x0, y0, x1, y1)
            hits_l = [same_line(l, g) for l in lines]
            if not any(hits_l):
                continue                      # не нашли вовсе
            hits += 1
            cover = sum(hits_l)
            # сколько найденных рамок легло внутрь настоящей строки — столько частей
            inside = 0
            for l in lines:
                inter_h = min(g[3], l[3]) - max(g[1], l[1])
                inter_w = min(g[2], l[2]) - max(g[0], l[0])
                if inter_h > 0.5 * (g[3] - g[1]) and inter_w > 0.15 * (g[2] - g[0]):
                    inside += 1
            if inside >= 2 and cover >= 2:
                split += 1
        matched = set()
        for (x0, y0, x1, y1, _t) in rows:
            g = (x0, y0, x1, y1)
            for i, l in enumerate(lines):
                if same_line(l, g):
                    matched.add(i)
        extra = len(lines) - len(matched)
        rec = hits / len(rows)
        prec = len(matched) / max(1, len(lines))
        report[name] = {'настоящих': len(rows), 'нашли': hits, 'рамок_всего': len(lines),
                        'recall': round(100 * rec, 1), 'precision': round(100 * prec, 1),
                        'разрезано': split, 'лишних': extra, 'секунд': round(dt, 1)}
        print(f"{name:11s} recall {100 * rec:5.1f} % · precision {100 * prec:5.1f} % · "
              f"рамок {len(lines):3d} (лишних {extra}) · разрезано {split} · {dt:.1f} с")
        tot['gt'] += len(rows)
        tot['found'] += hits
        tot['det'] += len(lines)
        tot['split'] += split
    if tot['gt']:
        print(f"\nИТОГО recall {100 * tot['found'] / tot['gt']:.1f} % · "
              f"precision {100 * (tot['det'] - sum(r['лишних'] for r in report.values())) / max(1, tot['det']):.1f} % · "
              f"разрезано {tot['split']}")
    report['_итого'] = tot
    with open(a.json, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print('json:', a.json)


if __name__ == '__main__':
    main()
