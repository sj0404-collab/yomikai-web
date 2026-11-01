#!/usr/bin/env python3
"""Замер чтеца (ONNX) на размеченных страницах — по каждой странице отдельно.

Читает тем же CtcLineReader, что и приложение, поэтому числа сопоставимы с
браузерной сборкой. Никакого обучения тут нет: только честный CER.

    python3 scripts/27_eval_pages_ctc.py --model out/eslav-ft.onnx
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ownocr.pair import CtcLineReader, cer, clean       # noqa: E402


def load(dirname, default_page):
    rows = []
    path = os.path.join(ROOT, dirname, 'labels.tsv')
    if not os.path.exists(path):
        return rows
    for line in open(path, encoding='utf-8'):
        parts = line.rstrip('\n').split('\t')
        if len(parts) < 2:
            continue
        img = cv2.imread(os.path.join(ROOT, dirname, parts[0]))
        if img is None:
            continue
        page = parts[2] if len(parts) > 2 else default_page
        rows.append({'page': page, 'text': parts[1], 'img': img})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default=os.path.join(ROOT, 'out', 'eslav-ft.onnx'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'out', 'eval-pages.json'))
    ap.add_argument('--show', type=int, default=0, help='показать N примеров на страницу')
    a = ap.parse_args()

    rows = (load('data-real', 'dense-a') + load('data-pages', 'other')
            + load('data-manhua', 'manhua') + load('data-comic', 'comic'))
    reader = CtcLineReader(a.model)
    per = {}
    for r in rows:
        got = reader.read(r['img'])
        got = got[0] if isinstance(got, (tuple, list)) else got
        c = cer(clean(r['text']), clean(got))
        d = per.setdefault(r['page'], {'cers': [], 'exact': 0, 'n': 0, 'rows': []})
        d['cers'].append(c)
        d['exact'] += int(clean(r['text']) == clean(got))
        d['n'] += 1
        if len(d['rows']) < a.show:
            d['rows'].append({'ref': r['text'], 'got': got})
    out = {}
    allc = []
    for page, d in sorted(per.items()):
        out[page] = {'cer': round(100 * float(np.mean(d['cers'])), 1), 'exact': d['exact'],
                     'n': d['n'], 'rows': d['rows']}
        allc += d['cers']
        print(f'{page:12s} CER {out[page]["cer"]:5.1f} % · дословно {d["exact"]}/{d["n"]}')
        for row in d['rows']:
            print(f'    эталон {row["ref"]!r} · прочтено {row["got"]!r}')
    out['_всего'] = {'cer': round(100 * float(np.mean(allc)), 1), 'n': len(allc)}
    print(f'ВСЕГО        CER {out["_всего"]["cer"]:5.1f} % на {len(allc)} строках · '
          f'модель {os.path.basename(a.model)} {os.path.getsize(a.model) // 1024} КБ')
    json.dump(out, open(a.out, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
