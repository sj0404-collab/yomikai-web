#!/usr/bin/env python3
"""Дообучение узнавателя букв на настоящей странице (с проверкой на отложенном).

Как устроено: берём страницы с эталоном, режем на пятна букв, выравниваем пятна
с эталонным текстом и учим модель на парах «пятно → буква». Учимся НЕ на всех
репликах: реплики 7–9 остаются на проверку, иначе это самообман.

    python3 scripts/15_finetune.py --epochs 6 --lr 0.0006
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr.engine import OwnOCR, binarize, boxes_of          # noqa: E402
from ownocr.features import features                          # noqa: E402
from ownocr.lesson_real import align                          # noqa: E402

LAB = '/home/user/koma-lab'
OUT = os.path.join(ROOT, 'out')


def page_glyphs(ocr, page, boxes_json):
    """Пятна букв со страницы и их верные буквы по эталону."""
    refs = json.load(open(os.path.join(LAB, 'dense-expected.json'), encoding='utf-8'))
    got = json.load(open(boxes_json, encoding='utf-8'))[page]
    rgb = np.array(Image.open(os.path.join(LAB, f'{page}.jpg')).convert('RGB'))
    H, W = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    rows = []
    for ri, rep in enumerate(got):
        b = rep['box']
        x0, y0 = max(0, int(b[0] * W)), max(0, int(b[1] * H))
        x1, y1 = min(W, int(b[2] * W)), min(H, int(b[3] * H))
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        bw = binarize(crop)
        marks = boxes_of(bw)
        feats, keep = [], []
        for m in marks:
            f = features(crop[max(0, m[1]):m[3], max(0, m[0]):m[2]])
            if f is not None:
                feats.append(f)
                keep.append(m)
        if not feats:
            continue
        probs = ocr.model.predict_proba(np.stack(feats))
        text = ''.join(c for c in refs[ri].upper() if c.isalnum())
        pairs = align(keep, text, probs, ocr.classes)
        for bi, ci in pairs:
            if text[ci] in ocr.cls_index:
                rows.append((feats[bi], ocr.cls_index[text[ci]], ri))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default=os.path.join(ROOT, 'model'))
    ap.add_argument('--boxes', default=os.path.join(OUT, 'dump3.json'))
    ap.add_argument('--pages', nargs='+', default=['dense-a', 'dense-b', 'dense-page'])
    ap.add_argument('--holdout', nargs='+', type=int, default=[6, 7, 8],
                    help='индексы реплик (с нуля), которые НЕ идут в обучение')
    ap.add_argument('--epochs', type=int, default=6)
    ap.add_argument('--lr', type=float, default=0.0006)
    ap.add_argument('--out', default=os.path.join(OUT, 'model-ft'))
    a = ap.parse_args()

    ocr = OwnOCR(a.model)
    rows = []
    for page in a.pages:
        rows += page_glyphs(ocr, page, a.boxes)
    X = np.stack([r[0] for r in rows]).astype(np.float32)
    y = np.array([r[1] for r in rows], np.int32)
    rep = np.array([r[2] for r in rows], np.int32)
    hold = np.isin(rep, a.holdout)
    print(f'пятен {len(y)} · в обучение {int((~hold).sum())} · на проверку {int(hold.sum())}')
    before_train = ocr.model.accuracy(X[~hold], y[~hold])
    before_hold = ocr.model.accuracy(X[hold], y[hold])
    print(f'буквы дословно: обучение {100 * before_train:.1f} % · проверка {100 * before_hold:.1f} %')

    n_train = int((~hold).sum())
    batch = int(os.environ.get('BATCH', max(16, min(128, n_train // 4))))
    print(f'батч {batch}')
    ocr.model.fit(X[~hold], y[~hold], epochs=a.epochs, lr=a.lr, batch=batch, seed=0,
                  log=lambda s: print(s, flush=True))
    after_train = ocr.model.accuracy(X[~hold], y[~hold])
    after_hold = ocr.model.accuracy(X[hold], y[hold])
    print(f'после: обучение {100 * after_train:.1f} % · проверка {100 * after_hold:.1f} %')

    if after_hold < before_hold - 0.005:
        print('ОТКАЗ: на отложенных репликах стало хуже — модель не сохраняю')
        return
    os.makedirs(a.out, exist_ok=True)
    weights = sorted(f for f in os.listdir(a.model) if f.endswith('.npz'))
    ocr.model.save(os.path.join(a.out, weights[0] if weights else 'ownocr.npz'))
    print(f'сохранено: {a.out}/{weights[0] if weights else "ownocr.npz"}')


if __name__ == '__main__':
    main()
