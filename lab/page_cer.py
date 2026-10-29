#!/usr/bin/env python3
"""CER всей страницы: распознанные строки против ручной разметки рамок.

Нужен, чтобы «стало лучше» было числом, а не впечатлением. На вход — JSON
строк, снятый из приложения (текст + координаты, в долях страницы), и
`data/lines-real/boxes.json` (ручные рамки с эталоном).

  python3 lab/page_cer.py --lines /tmp/dense-lines.json --size 720x1118
"""
import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOOKALIKE = {'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К', 'O': 'О',
             'P': 'Р', 'T': 'Т', 'X': 'Х', 'Y': 'У', 'a': 'а', 'c': 'с', 'e': 'е',
             'o': 'о', 'p': 'р', 'x': 'х', 'y': 'у', 'b': 'ь', 'Δ': 'Д', 'Ο': 'О',
             'Τ': 'Т', 'Β': 'В', 'Α': 'А'}


def norm(s):
    out = []
    for ch in str(s or '').upper():
        ch = LOOKALIKE.get(ch, ch)
        if ch.isalnum():
            out.append(ch)
    return ''.join(out)


def cer(ref, hyp):
    r, h = list(ref), list(hyp)
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        cur = [i] + [0] * len(h)
        for j in range(1, len(h) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r[i - 1] != h[j - 1]))
        prev = cur
    return prev[len(h)] / len(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lines', required=True)
    ap.add_argument('--truth', default=os.path.join(ROOT, 'data', 'lines-real', 'boxes.json'))
    ap.add_argument('--size', default='720x1118')
    ap.add_argument('--show', type=int, default=6)
    args = ap.parse_args()
    W, H = (int(x) for x in args.size.split('x'))

    truth = json.load(open(args.truth, encoding='utf-8'))
    lines = json.load(open(args.lines, encoding='utf-8'))

    rows, used = [], set()
    for t in truth:
        best, bi = 0, -1
        for i, ln in enumerate(lines):
            if i in used:
                continue
            x0, y0 = ln['l'] * W, ln['t2'] * H
            x1, y1 = ln['r'] * W, ln['b'] * H
            ox = max(0, min(x1, t['x1']) - max(x0, t['x0']))
            oy = max(0, min(y1, t['y1']) - max(y0, t['y0']))
            area = max(1, (t['x1'] - t['x0']) * (t['y1'] - t['y0']))
            k = ox * oy / area
            if k > best:
                best, bi = k, i
        if bi >= 0 and best >= 0.5:
            used.add(bi)
            rows.append((cer(norm(t['text']), norm(lines[bi]['t'])), t['text'], lines[bi]['t']))
        else:
            rows.append((1.0, t['text'], '(не найдено)'))
    cers = [r[0] for r in rows]
    exact = sum(1 for c in cers if c == 0)
    print(f'строк в разметке {len(rows)}, сопоставлено {len(used)} · '
          f'CER {100 * sum(cers) / len(cers):.1f} % · целиком верных {exact}/{len(rows)}')
    rows.sort(reverse=True)
    for c, ref, hyp in rows[:args.show]:
        print(f'   {100 * c:5.1f} %  эталон: {ref}')
        print(f'            читалка: {hyp}')


if __name__ == '__main__':
    main()
