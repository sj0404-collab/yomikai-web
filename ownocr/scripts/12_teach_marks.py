#!/usr/bin/env python3
"""Адресный урок по меткам: «Й» не должна читаться как «И», «Ё» — как «Е».

Замер по странице манги показал, что ошибки не случайны:

    Й → И:  42 % всех «Й»     (теряется краткая)
    Ё → Е: 100 % всех «Ё»     (теряются точки)
    О → 2 / 0, Б ↔ Н/Е, Ы ↔ Е (потеря или лишняя перекладина)

То есть ученик не «путает всё подряд», а теряет мелкие надстрочные метки.
Причина в признаках: глиф вписывается в квадрат 24×24 вместе с точками, и
сетка плотности 6×6 (клетка 4 px) размывает метку.

Здесь — лечение без переучивания с нуля: берём глифы этих пар со всего листа,
добавляем упражнения, которые метку НЕ стирают (лёгкий поворот и наклон без
размытия), и учим малым шагом с повтором листа. Приёмка строгая: модель
принимается только если на контрольных настоящих строках стало не хуже, а
число путаниц в этих парах уменьшилось.

    python3 scripts/12_teach_marks.py --model model --out out/marks.json
"""
import argparse
import collections
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr import data as D                     # noqa: E402
from ownocr.engine import OwnOCR                 # noqa: E402
from ownocr.features import features             # noqa: E402
from ownocr.lesson_real import read_rows         # noqa: E402

# пары под наблюдением: (что должно быть, с чем путается)
WATCH = {
    'Й': set('ИЫН'),
    'Ё': set('Е'),
    'О': set('02'),
    'Б': set('НЕВЬ'),
    'Ы': set('ЕЬБ'),
    'Е': set('ЁЫВ'),
}
# кого учим отдельно (и их двойники — чтобы граница была видна)
TEACH = ['Й', 'Ё', 'О', 'Б', 'Ы', 'Е', 'И', 'Н', 'В', '0', '2', 'Ь', 'З']


def align(ref: str, hyp: str):
    n, m = len(ref), len(hyp)
    D_ = np.zeros((n + 1, m + 1), np.int32)
    D_[:, 0] = range(n + 1)
    D_[0, :] = range(m + 1)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D_[i, j] = min(D_[i - 1, j] + 1, D_[i, j - 1] + 1,
                           D_[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]))
    i, j, ops = n, m, []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and D_[i, j] == D_[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append((ref[i - 1], hyp[j - 1]))
            i, j = i - 1, j - 1
        elif i > 0 and D_[i, j] == D_[i - 1, j] + 1:
            ops.append((ref[i - 1], ''))
            i -= 1
        elif j > 0 and D_[i, j] == D_[i, j - 1] + 1:
            ops.append(('', hyp[j - 1]))
            j -= 1
        else:
            break
    return ops[::-1]


def cer(ref: str, hyp: str) -> float:
    if not ref:
        return 0.0 if not hyp else 1.0
    return sum(1 for a, b in align(ref, hyp) if a != b) / len(ref)


def strip(text: str) -> str:
    return ''.join(c for c in text.upper() if c.isalnum() or c == ' ')


def evaluate(ocr: OwnOCR, rows):
    """CER по строкам + сколько именно путаниц в наблюдаемых парах."""
    cers, exact, pairs = [], 0, collections.Counter()
    for path, ref in rows:
        gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        R = strip(ref)
        H = strip(ocr.read_line(gray, lexicon=True)['text'])
        cers.append(cer(R, H))
        exact += int(R == H)
        for a, b in align(R, H):
            if a in WATCH and b and a != b and b in WATCH[a]:
                pairs[(a, b)] += 1
    return float(np.mean(cers)), exact, pairs


def mark_exercises(sheet_png, manifest, chars, variants=10, seed=5):
    """Глифы выбранных букв со всего листа + упражнения, сохраняющие метки."""
    imgs, labs, _, _, _ = D.load_sheet(sheet_png, manifest)
    rng = np.random.default_rng(seed)
    X, Y = [], []
    keep = [i for i, l in enumerate(labs) if l.upper() in chars]
    for v in range(variants):
        for i in keep:
            g = imgs[i]
            if v:
                # поворот/сдвиг/масштаб — без размытия и без сильного шума:
                # точки и краткая должны остаться на месте
                ang = float(rng.uniform(-7, 7))
                h, w = g.shape
                M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
                g2 = cv2.warpAffine(g, M, (w, h), flags=cv2.INTER_LINEAR,
                                    borderValue=255)
                if v % 3 == 0:
                    k = float(rng.uniform(0.85, 1.15))
                    g2 = cv2.resize(g2, None, fx=k, fy=k, interpolation=cv2.INTER_LINEAR)
                g = g2
            f = features(g)
            if f is not None:
                X.append(f)
                Y.append(labs[i].upper())
    return np.stack(X), np.array(Y)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', default=os.path.join(ROOT, 'out', 'sheet.png'))
    ap.add_argument('--manifest', default=os.path.join(ROOT, 'out', 'sheet-manifest.json'))
    ap.add_argument('--labels', default=os.path.join(ROOT, 'data-real', 'labels.tsv'))
    ap.add_argument('--model', default=os.path.join(ROOT, 'model'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'out', 'marks.json'))
    ap.add_argument('--epochs', type=int, default=10)
    ap.add_argument('--lr', type=float, default=6e-4)
    a = ap.parse_args()

    ocr = OwnOCR(a.model)
    base = os.path.dirname(os.path.abspath(a.labels))
    rows = [(os.path.join(base, n), t) for n, t in read_rows(a.labels)]

    cer0, exact0, pairs0 = evaluate(ocr, rows)
    print(f'ДО: CER строк {100 * cer0:.1f} % · целиком верных {exact0}/{len(rows)} · '
          f'путаниц в наблюдаемых парах {sum(pairs0.values())}')
    for (x, y), n in pairs0.most_common(8):
        print(f'   {x} → {y}: {n}')

    Xm, Ym = mark_exercises(a.sheet, a.manifest, set(TEACH))
    print(f'упражнений по меткам: {len(Ym)} · буквы {sorted(set(Ym))}')
    ym = np.array([ocr.classes.index(l) for l in Ym if l in ocr.classes], np.int32)
    keep = np.array([l in ocr.classes for l in Ym])
    Xm = Xm[keep]

    # повтор листа, чтобы не забыть остальные буквы
    imgs, labs, _, _, _ = D.load_sheet(a.sheet, a.manifest)
    rng = np.random.default_rng(11)
    pick = rng.choice(len(imgs), size=min(6000, len(imgs)), replace=False)
    Xr, Yr = [], []
    for i in pick:
        f = features(D.augment(imgs[i], rng, 'easy'))
        if f is not None:
            Xr.append(f)
            Yr.append(labs[i].upper())
    Xr = np.stack(Xr)
    yr = np.array([ocr.classes.index(l) for l in Yr if l in ocr.classes], np.int32)

    X = np.vstack([Xm, Xr])
    y = np.concatenate([ym, yr])
    w = np.concatenate([np.full(len(ym), 1.6, np.float32), np.ones(len(yr), np.float32)])

    best = {k: v.copy() for k, v in ocr.model._params().items()}
    best_cer, best_pairs = cer0, sum(pairs0.values())
    for ep in range(a.epochs):
        ocr.model.fit(X, y, epochs=1, batch=128, lr=a.lr, seed=ep + 1,
                      sample_weight=w, log=None)
        cur, _ex, pr = evaluate(ocr, rows)
        print(f'   эпоха {ep + 1:2d}/{a.epochs}: CER строк {100 * cur:.1f} % · '
              f'путаниц {sum(pr.values())}')
        if cur <= best_cer + 1e-4 and sum(pr.values()) < best_pairs:
            best_cer, best_pairs = cur, sum(pr.values())
            best = {k: v.copy() for k, v in ocr.model._params().items()}

    for k, v in best.items():
        ocr.model._params()[k][...] = v
    cer1, exact1, pairs1 = evaluate(ocr, rows)
    accepted = (cer1 <= cer0 + 1e-4) and (sum(pairs1.values()) < sum(pairs0.values()))
    print(f'ПРИЁМКА: {"принято" if accepted else "откат"} · '
          f'CER строк {100 * cer0:.1f} → {100 * cer1:.1f} % · '
          f'путаниц {sum(pairs0.values())} → {sum(pairs1.values())}')
    if accepted:
        ocr.model.save(os.path.join(a.model, 'ownocr-latest.npz'))
        print('   модель сохранена:', os.path.join(a.model, 'ownocr-latest.npz'))

    json.dump({'before': {'cer': cer0, 'exact': exact0,
                          'pairs': {f'{x}->{y}': n for (x, y), n in pairs0.items()}},
               'after': {'cer': cer1, 'exact': exact1,
                         'pairs': {f'{x}->{y}': n for (x, y), n in pairs1.items()}},
               'accepted': bool(accepted), 'epochs': a.epochs, 'lr': a.lr,
               'n_mark_exercises': int(len(ym))},
              open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('отчёт:', a.out)


if __name__ == '__main__':
    main()
