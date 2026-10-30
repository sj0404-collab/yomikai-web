#!/usr/bin/env python3
"""Скачать кириллические шрифты для листа.

Список берётся из метаданных Google Fonts (`subsets` содержит `cyrillic`), сами
файлы — через CSS-запрос: Google отдаёт по нему прямые ссылки на TTF.

    python3 scripts/01_fetch_fonts.py --limit 130 --out /var/tmp/ownocr/fonts
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess


def curl(args):
    return subprocess.run(['curl', '-s', '-m', '60', '-A', 'Mozilla/4.0'] + args,
                          capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=130)
    ap.add_argument('--out', default='/var/tmp/ownocr/fonts')
    ap.add_argument('--layout', default='/var/tmp/ownocr')
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.layout, exist_ok=True)

    meta_path = os.path.join(a.layout, 'meta.json')
    if not os.path.exists(meta_path):
        raw = curl(['-L', 'https://fonts.google.com/metadata/fonts'])
        open(meta_path, 'w', encoding='utf-8').write(raw)
    raw = open(meta_path, encoding='utf-8').read()
    data = json.loads(raw[raw.index('{'):])
    fam = [f for f in data['familyMetadataList'] if 'cyrillic' in (f.get('subsets') or [])]
    names = [f['family'] for f in fam][:a.limit]
    print(f'семейств с кириллицей: {len(fam)} · берём {len(names)}')

    def css(name):
        out = curl([f'https://fonts.googleapis.com/css2?family={name.replace(" ", "+")}'])
        m = re.search(r'url\((https://[^)]+\.ttf)\)', out)
        return name, (m.group(1) if m else None)

    with cf.ThreadPoolExecutor(12) as ex:
        found = {n: u for n, u in ex.map(css, names) if u}

    def fetch(item):
        name, url = item
        fn = os.path.join(a.out, re.sub(r'[^A-Za-z0-9]+', '_', name) + '.ttf')
        if not (os.path.exists(fn) and os.path.getsize(fn) > 20000):
            curl(['-L', '-o', fn, url])
        return fn

    with cf.ThreadPoolExecutor(12) as ex:
        files = [f for f in ex.map(fetch, found.items())
                 if os.path.exists(f) and os.path.getsize(f) > 20000]
    json.dump(sorted(found), open(os.path.join(a.layout, 'families-used.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(f'скачано шрифтов: {len(files)} → {a.out}')


if __name__ == '__main__':
    main()
