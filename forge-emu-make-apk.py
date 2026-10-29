#!/usr/bin/env python3
"""Положить текущую страницу читалки в копию настоящего АПК — для эмулятора
APKForge Studio.

Студия показывает в своём эмуляторе `assets/webapp/index.html` из АПК побайтово,
поэтому «поставить читалку в эмулятор» = взять собранный АПК и заменить в нём
этот файл на только что собранный `koma-web.html`.

  python3 forge-emu-make-apk.py [--apk koma-reader-v1.9.41.apk] [--out /tmp/koma-probe-forge.apk]
"""
import argparse
import os
import zipfile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--apk', default='', help='исходный АПК (по умолчанию последний в /home/user)')
    ap.add_argument('--page', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'koma-web.html'))
    ap.add_argument('--out', default='/tmp/koma-probe-forge.apk')
    a = ap.parse_args()

    src = a.apk
    if not src:
        cands = [os.path.join('/home/user', f) for f in os.listdir('/home/user')
                 if f.startswith('koma-reader-v') and f.endswith('.apk')]
        if not cands:
            raise SystemExit('нет исходного АПК: укажите --apk')
        src = sorted(cands)[-1]

    html = open(a.page, 'rb').read()
    zin = zipfile.ZipFile(src)
    with zipfile.ZipFile(a.out, 'w', zipfile.ZIP_DEFLATED) as z:
        for it in zin.infolist():
            z.writestr(it, zin.read(it.filename))
        z.writestr('assets/webapp/index.html', html)
    print(f'готово: {a.out} ({os.path.getsize(a.out)} Б), страница {len(html)} Б, из {src}')


if __name__ == '__main__':
    main()
