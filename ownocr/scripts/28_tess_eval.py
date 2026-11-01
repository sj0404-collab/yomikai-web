#!/usr/bin/env python3
"""Замер: тесеракт против нашего чтеца и эслава, по страницам и по жанрам.

    sudo apt-get install -y tesseract-ocr tesseract-ocr-rus
    pip install pytesseract
    python3 scripts/28_tess_eval.py

Считает CER каждого чтеца отдельно и склейки «по штрафу за мусор» (из двух
прочтений берётся то, где меньше слов вне словаря; при равенстве — первое).
"""
import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ownocr.pair import CtcLineReader, CtcReader, cer, clean   # noqa: E402
from ownocr.tess import TesseractReader                        # noqa: E402

DOMAIN = {'dense-a': 'манга', 'kuro-p1': 'манга', 'kuro-p2': 'манга',
          'tyrant-p1': 'манхва', 'reader-p1': 'манхва',
          'manhua1': 'маньхуа', 'manhua2': 'маньхуа', 'manhua4': 'маньхуа', 'manhua5': 'маньхуа',
          'comic2': 'комикс', 'comic3': 'комикс', 'comic4': 'комикс'}


def load(rows, dirname, default_page):
    path = os.path.join(ROOT, dirname, 'labels.tsv')
    if not os.path.exists(path):
        return
    for line in open(path, encoding='utf-8'):
        p = line.rstrip('\n').split('\t')
        img = cv2.imread(os.path.join(ROOT, dirname, p[0]))
        if img is not None:
            rows.append({'page': p[2] if len(p) > 2 else default_page,
                         'text': p[1], 'img': img})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--vocab', default=os.path.join(ROOT, 'ownocr', 'vocab-ru.txt'))
    ap.add_argument('--app', default='/home/user/cand/q/koma_rec-fp16.onnx')
    ap.add_argument('--dict', default='/home/user/koma_models/koma_dict.txt')
    ap.add_argument('--eslav', default=os.path.join(ROOT, 'model/eslav/eslav-ft-all.onnx'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'out', 'tess-eval.json'))
    a = ap.parse_args()

    rows = []
    load(rows, 'data-real', 'dense-a')
    load(rows, 'data-pages', 'other')
    load(rows, 'data-manhua', 'manhua?')
    load(rows, 'data-comic', 'comic?')
    vocab = set(w.upper() for w in open(a.vocab, encoding='utf-8').read().split() if len(w) >= 3)
    app = CtcReader(a.app, a.dict)
    esl = CtcLineReader(a.eslav)
    tess = TesseractReader()

    def score(t):
        known = unknown = 0
        for w in clean(t).split():
            k = w.strip('.,!?…—«»"():;%')
            if len(k) >= 3:
                if k in vocab:
                    known += len(k)
                else:
                    unknown += len(k)
        return known - 2 * unknown

    def pick(*texts):
        best, bs = '', None
        for t in texts:
            if not t:
                continue
            s = score(t)
            if bs is None or s > bs:
                bs, best = s, t
        return best

    acc = {k: [] for k in ['приложение', 'эслав', 'тесеракт',
                           'прил+тес', 'эслав+тес', 'прил+эслав+тес']}
    per, times = {}, {'приложение': 0.0, 'эслав': 0.0, 'тесеракт': 0.0}
    for r in rows:
        t0 = time.time()
        ta = app.read(r['img'])[0]
        t1 = time.time()
        te = esl.read(r['img'])[0]
        t2 = time.time()
        tt = tess.read(r['img'])[0]
        t3 = time.time()
        times['приложение'] += t1 - t0
        times['эслав'] += t2 - t1
        times['тесеракт'] += t3 - t2
        vals = {'приложение': ta, 'эслав': te, 'тесеракт': tt,
                'прил+тес': pick(ta, tt), 'эслав+тес': pick(te, tt),
                'прил+эслав+тес': pick(ta, te, tt)}
        d = per.setdefault(r['page'], {k: [] for k in acc})
        for k, v in vals.items():
            c = cer(clean(r['text']), clean(v))
            acc[k].append(c)
            d[k].append(c)

    print(f'строк {len(rows)} · скорость: ' + ' · '.join(
        f'{k} {1000 * v / len(rows):.0f} мс' for k, v in times.items()))
    keys = list(acc)
    print('страница     ' + ''.join(f'{k:>15}' for k in keys))
    for p in sorted(per):
        print(f'{p:12s} ' + ''.join(f'{100 * np.mean(per[p][k]):14.1f}%' for k in keys))
    for dom in ['манга', 'манхва', 'маньхуа', 'комикс']:
        idx = [i for i, r in enumerate(rows) if DOMAIN.get(r['page']) == dom]
        print(f'{dom:12s} ' + ''.join(
            f'{100 * np.mean([acc[k][i] for i in idx]):14.1f}%' for k in keys))
    print(f'{"ВСЕГО":12s} ' + ''.join(f'{100 * np.mean(acc[k]):14.1f}%' for k in keys))
    json.dump({k: [float(x) for x in v] for k, v in acc.items()},
              open(a.out, 'w'), ensure_ascii=False, indent=1)
    print('сохранено:', a.out)


if __name__ == '__main__':
    main()
