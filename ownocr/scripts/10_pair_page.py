#!/usr/bin/env python3
"""Коллаборация: детектор приложения + СВОЙ распознаватель на целой странице.

    python3 scripts/10_pair_page.py --page ../koma-lab/dense-a.jpg \
        --det /home/user/koma_models/koma_det.onnx --out out/pair-dense-a.png

Что происходит:

1. детектор находит на странице текст (карта вероятностей → компоненты → боксы);
2. каждый бокс режется на строки по проекции чернил (логика приложения);
3. **каждую строку читает свой ученик** (`ownocr.model`, прошедший курс и урок 7);
4. строки собираются в реплики и выстраиваются в порядке чтения манги
   (справа налево, сверху вниз) — это тоже логика приложения, а не наша.

Для сравнения тем же кодом читает и CTC-распознаватель приложения
(`koma_rec.onnx`), если он есть: один и тот же детектор, одни и те же строки,
разница только в том, кто читает буквы.
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

from ownocr.engine import OwnOCR                     # noqa: E402
from ownocr.page_det import PageDetector  # noqa: E402, F401


def cer(ref: str, hyp: str) -> float:
    """Доля правок (Левенштейн по символам) к длине эталона."""
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(ref) + 1))
    for i, ch in enumerate(hyp, 1):
        cur = [i]
        for j, rc in enumerate(ref, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != ch)))
        prev = cur
    return prev[-1] / len(ref)


from ownocr.pair import (VOCAB, CtcReader, OwnReader, cer, clean,  # noqa: E402
                         is_harsh_page, known_words, normalize_page, read_page)


def draw(page_path: str, out_png: str, boxes, lines):
    """Страница + рамки детектора (серые) + собранные реплики (цветные)."""
    import cv2

    img = cv2.imread(page_path)
    H, W = img.shape[:2]
    for (x1, y1, x2, y2) in boxes:
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (150, 150, 150), 1)
    for i, line in enumerate(lines, 1):
        p1 = (int(line.left * W), int(line.top * H))
        p2 = (int(line.right * W), int(line.bottom * H))
        cv2.rectangle(img, p1, p2, (60, 200, 90), 2)
        cv2.putText(img, str(i), (p1[0] + 3, max(14, p1[1] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (60, 200, 90), 2)
    cv2.imwrite(out_png, img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--page', default=os.path.join(ROOT, '..', 'koma-lab', 'dense-a.jpg'))
    ap.add_argument('--det', default='/home/user/koma_models/koma_det.onnx')
    ap.add_argument('--ctc', default='/home/user/koma_models/koma_rec.onnx')
    ap.add_argument('--dict', default='/home/user/koma_models/koma_dict.txt')
    ap.add_argument('--model', default=os.path.join(ROOT, 'model'))
    ap.add_argument('--expected', default='')
    ap.add_argument('--out', default=os.path.join(ROOT, 'out', 'pair-page.png'))
    ap.add_argument('--json', default='')
    ap.add_argument('--minconf', type=float, default=0.8,
                    help='порог уверенности своего ученика (CTC проверяется своим, 0.25)')
    a = ap.parse_args()

    rgb = np.array(Image.open(a.page).convert('RGB'))
    det = PageDetector(a.det)
    mine = read_page(det, OwnReader(a.model), rgb, minconf=a.minconf)
    res = {'page': os.path.basename(a.page), 'size': list(rgb.shape[:2]),
           'own': {'replies': [l.text for l in mine['replies']],
                   'dropped': mine['dropped'], 'boxes': mine['boxes'],
                   'lines': mine['lines'], 'seconds': round(mine['seconds'], 2)}}

    print(f'страница {os.path.basename(a.page)} {rgb.shape[1]}×{rgb.shape[0]}')
    print(f'детектор: {mine["boxes"]} боксов → {mine["lines"]} строк · '
          f'свой ученик прочитал за {mine["seconds"]:.1f} с')

    if os.path.exists(a.ctc) and os.path.exists(a.dict):
        ctc = read_page(det, CtcReader(a.ctc, a.dict), rgb, minconf=0.25)
        res['ctc'] = {'replies': [l.text for l in ctc['replies']],
                      'dropped': ctc['dropped'], 'boxes': ctc['boxes'],
                      'lines': ctc['lines'], 'seconds': round(ctc['seconds'], 2)}

    exp = []
    if a.expected and os.path.exists(a.expected):
        exp = json.load(open(a.expected, encoding='utf-8'))
    if exp:
        print(f'\nэталон: {len(exp)} реплик')
        for name in ('own', 'ctc'):
            if name not in res:
                continue
            got = res[name]['replies']
            n = min(len(exp), len(got))
            cers = [cer(clean(exp[i]), clean(got[i])) for i in range(n)]
            cers += [1.0] * abs(len(exp) - len(got))
            exact = sum(1 for i in range(n) if clean(exp[i]) == clean(got[i]))
            res[name].update({'cer': round(float(np.mean(cers)), 4),
                              'exact': exact, 'n_expected': len(exp), 'n_got': len(got)})
            print(f'  {name:4s}: реплик {len(got)} из {len(exp)} · '
                  f'CER {100 * np.mean(cers):.1f} % · целиком верных {exact}/{len(exp)}')

    print('\nчто прочитал свой ученик (в порядке чтения):')
    for i, line in enumerate(mine['replies'], 1):
        print(f'  {i:2d}. {line.text}')
        res['own'].setdefault('order', []).append(line.text)

    if a.json:
        os.makedirs(os.path.dirname(a.json) or '.', exist_ok=True)
        json.dump(res, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('\njson:', a.json)

    boxes = det.detect_page(rgb)
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    draw(a.page, a.out, boxes, mine['replies'])
    print('картинка:', a.out)


if __name__ == '__main__':
    main()
