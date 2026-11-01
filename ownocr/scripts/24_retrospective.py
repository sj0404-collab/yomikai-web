#!/usr/bin/env python3
"""Ретроспектива: все чтецы, что у нас были, на ОДНИХ И ТЕХ ЖЕ 41 строке.

Зачем: за месяцы работы числа накапливались в разных прогонах и на разных
данных — «54,7 %», «10,0 %», «2,6 %» относятся к разным наборам, и сравнивать их
напрямую нельзя. Здесь все кандидаты меряются одинаково: 41 настоящая строка
манги из `data-real`, CER по словам-буквам, плюс скорость.

    python3 scripts/24_retrospective.py            # все
    python3 scripts/24_retrospective.py --fast      # без медленного ученика
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
import ownocr.pair as pr                                     # noqa: E402


def rows():
    out = []
    for line in open(os.path.join(ROOT, 'data-real', 'labels.tsv'), encoding='utf-8'):
        name, text = line.rstrip('\n').split('\t')
        g = cv2.imread(os.path.join(ROOT, 'data-real', name), cv2.IMREAD_GRAYSCALE)
        if g is not None:
            out.append((g, text))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fast', action='store_true', help='пропустить медленного ученика')
    ap.add_argument('--json', default=os.path.join(ROOT, 'out', 'retrospective.json'))
    a = ap.parse_args()

    data = rows()
    print(f'строк: {len(data)}')
    results = {}

    def record(name, fn, note=''):
        t0 = time.time()
        cers, exact, txts = [], 0, []
        for g, ref in data:
            try:
                got = fn(g)
            except Exception as exc:
                print(f'  {name}: упал ({exc})')
                return
            txts.append(got)
            c = pr.cer(pr.clean(ref), pr.clean(got))
            cers.append(c)
            exact += int(pr.clean(ref) == pr.clean(got))
        dt = time.time() - t0
        results[name] = {'cer': round(100 * float(np.mean(cers)), 1), 'дословно': f'{exact}/{len(data)}',
                         'мс_на_строку': round(1000 * dt / len(data), 1), 'note': note, 'примеры': txts[:5]}
        print(f'{name:22s} CER {results[name]["cer"]:5.1f} % · дословно {exact:2d}/{len(data)} · '
              f'{results[name]["мс_на_строку"]:7.1f} мс/строка', flush=True)

    # 1) свой ученик (курс + урок 7) — единственный «свой» чтец
    if not a.fast:
        own = pr.OwnReader(os.path.join(ROOT, 'model'))
        own.roles = []
        record('свой ученик', lambda g: own.read(g)[0], 'npz, курс детсад→университет')

    # 2) CTC-модели семейства «эслав» и распознаватель приложения
    cands = [
        ('приложение PP-OCR', '/home/user/koma_models/koma_rec.onnx', 'app'),
        ('эслав дообученный', os.path.join(ROOT, 'model', 'eslav', 'eslav-ft.onnx'), 'eslav'),
        ('эслав базовая', os.path.join(ROOT, 'model', 'eslav', 'base.onnx'), 'eslav'),
    ]
    for label, path, kind in cands:
        if not os.path.exists(path):
            print(f'  {label}: файла нет — пропускаю')
            continue
        if kind == 'app':
            r = pr.CtcReader(path, '/home/user/koma_models/koma_dict.txt')

            def fn(g, r=r):
                rgb = np.repeat(g[:, :, None], 3, axis=2)
                return r.read(rgb)[0]
        else:
            r = pr.CtcLineReader(path)

            def fn(g, r=r):
                return r.read(g)[0]
        record(label, fn)

    with open(a.json, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print('json:', a.json)


if __name__ == '__main__':
    main()
