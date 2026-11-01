#!/usr/bin/env python3
"""Чтение полосы манхвы своим путём (webtoon.py) + полоска для сверки глазами.

    python3 scripts/21_webtoon_read.py --page ../manhwa-shots/pages/tyrant-p1.png \
        --out out/webtoon-tyrant.png --json out/webtoon-tyrant.json
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
import ownocr.ideas.webtoon as W                                   # noqa: E402
from ownocr.pair import CtcLineReader, cer, clean            # noqa: E402


def sheet(rows, path, width=1300):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 18)
    crops = []
    for r in rows:
        c = r['crop']
        k = min(1.0, (width * 0.55) / max(1, c.shape[1]))
        im = Image.fromarray(c).convert('RGB').resize((max(10, int(c.shape[1] * k)),
                                                       max(10, int(c.shape[0] * k))))
        crops.append((im, r))
    if not crops:
        return None
    H = sum(im.height + 30 for im, _ in crops)
    canvas = Image.new('RGB', (width, H), (245, 245, 248))
    d = ImageDraw.Draw(canvas)
    y = 0
    for im, r in crops:
        canvas.paste(im, (0, y))
        d.text((width * 0.57, y + 4), f"{r['text'][:64]}", fill=(20, 20, 26), font=font)
        d.text((width * 0.57, y + 26), f"уверенность {r['conf']}", fill=(120, 126, 140), font=font)
        y += im.height + 30
    canvas.save(path)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--page', required=True)
    ap.add_argument('--eslav', default=os.environ.get('OWNOCR_ESLAV_MODEL', ''))
    ap.add_argument('--out', default='')
    ap.add_argument('--json', default='')
    a = ap.parse_args()

    g = cv2.imread(a.page, cv2.IMREAD_GRAYSCALE)
    if g is None:
        raise SystemExit('страница не читается: ' + a.page)
    t0 = time.time()
    reader = CtcLineReader(a.eslav) if a.eslav else None
    rows = W.read_page(g, reader=reader)
    dt = time.time() - t0
    print(f'{os.path.basename(a.page)}: {g.shape[1]}×{g.shape[0]} · строк {len(rows)} · {dt:.1f} с')
    ref = os.path.splitext(a.page)[0] + '.txt'
    if os.path.exists(ref):
        want = [l.strip() for l in open(ref, encoding='utf-8') if l.strip()]
        got = [r['text'] for r in rows]
        n = min(len(want), len(got))
        if n:
            cers = [cer(clean(want[i]), clean(got[i])) for i in range(n)]
            print(f'  CER по {n} парам: {100 * float(np.mean(cers)):.1f} % '
                  f'(в эталоне {len(want)}, прочитано {len(got)})')
    for i, r in enumerate(rows, 1):
        print(f"  {i:2d}. y={r['y']:5d} {r['text']}")
    if a.out:
        print('полоска:', sheet(rows, a.out))
    if a.json:
        json.dump([{k: v for k, v in r.items() if k != 'crop'} for r in rows],
                  open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('json:', a.json)


if __name__ == '__main__':
    main()
