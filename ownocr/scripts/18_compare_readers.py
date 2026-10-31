#!/usr/bin/env python3
"""Кто точнее на одних и тех же строках: ученик, «эслав» и бригада.

Строки с известным текстом (data-real). Отдельно показываем отложенные строки —
те, которых не было в дообучении: только по ним видно настоящий выигрыш.
"""
import argparse, json, os, sys
import numpy as np, cv2
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ownocr.pair as pr
from ownocr.pair import cer, clean


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default=os.path.join(ROOT, 'model'))
    ap.add_argument('--eslav', default=os.path.join(ROOT, 'out', 'eslav-ft.onnx'))
    ap.add_argument('--holdout', type=int, default=7)
    a = ap.parse_args()

    rows = []
    for line in open(os.path.join(ROOT, 'data-real', 'labels.tsv'), encoding='utf-8'):
        name, text = line.rstrip('\n').split('\t')
        g = cv2.imread(os.path.join(ROOT, 'data-real', name), cv2.IMREAD_GRAYSCALE)
        if g is not None:
            rows.append((name, g, text))

    reader = pr.OwnReader(a.model)
    own_reader_only = pr.OwnReader(a.model)
    own_reader_only.eslav = None
    eslav = pr.CtcLineReader(a.eslav) if os.path.exists(a.eslav) else None

    res = {'ученик': [], 'эслав': [], 'бригада': []}
    for name, g, ref in rows:
        res['ученик'].append(cer(clean(ref), clean(own_reader_only.read(g)[0])))
        if eslav:
            res['эслав'].append(cer(clean(ref), clean(eslav.read(g)[0])))
        res['бригада'].append(cer(clean(ref), clean(reader.read(g)[0])))
    for who, cers in res.items():
        hold = cers[:a.holdout]
        print(f'{who:8s}: все {len(cers)} строк CER {100*np.mean(cers):5.1f} % · '
              f'отложенные {len(hold)} строк CER {100*np.mean(hold) if hold else 0:5.1f} %')
    if eslav:
        print('\nпо строкам (отложенные):')
        for name, g, ref in rows[:a.holdout]:
            print(f'  {ref!r}')
            print(f'    ученик {own_reader_only.read(g)[0]!r}')
            print(f'    эслав  {eslav.read(g)[0]!r}')
            print(f'    бригада {reader.read(g)[0]!r}')


if __name__ == '__main__':
    main()
