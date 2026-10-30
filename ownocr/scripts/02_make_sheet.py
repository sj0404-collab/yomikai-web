#!/usr/bin/env python3
"""Нарисовать один лист: все шрифты на одной странице + манифест.

    python3 scripts/02_make_sheet.py --fonts /var/tmp/ownocr/fonts --px 30
"""
import argparse
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr import data as D   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fonts', default='/var/tmp/ownocr/fonts')
    ap.add_argument('--px', type=int, default=30)
    ap.add_argument('--holdout-every', type=int, default=5)
    ap.add_argument('--out', default=os.path.join(ROOT, 'out'))
    a = ap.parse_args()
    paths = sorted(glob.glob(os.path.join(a.fonts, '*.ttf')) + glob.glob(os.path.join(a.fonts, '*.otf')))
    if not paths:
        raise SystemExit(f'нет шрифтов в {a.fonts} — сначала scripts/01_fetch_fonts.py')
    os.makedirs(a.out, exist_ok=True)
    meta = D.render_sheet(paths, os.path.join(a.out, 'sheet.png'),
                          os.path.join(a.out, 'sheet-manifest.json'),
                          px=a.px, holdout_every=a.holdout_every)
    print('лист:', meta)
    print('файлы:', os.path.join(a.out, 'sheet.png'), '·', os.path.join(a.out, 'sheet-manifest.json'))


if __name__ == '__main__':
    main()
