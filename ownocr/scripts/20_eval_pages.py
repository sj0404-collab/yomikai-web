#!/usr/bin/env python3
"""Замер чтеца на произвольных страницах: сколько реплик нашёл, что прочитал.

Скрипт ничего не «улучшает»: он гоняет ту же бригаду (`pair.OwnReader`), что и
приложение, и складывает три вещи — тексты в порядке чтения, PNG с рамками
найденных мест и полоску из самих кропов. Полоска нужна, чтобы человек мог
сверить прочитанное глазами: видно и кроп, и что из него выжали.

    python3 scripts/20_eval_pages.py --pages ../manhwa-shots/pages/tyrant-p1.png \
        --out out/shot-tyrant

Если рядом со страницей лежит `<имя>.txt` (эталон, по реплике на строку),
считается CER — больше он нигде не берётся.
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
import ownocr.pair as pr                                    # noqa: E402


def strip_of(crops, texts, width=1400, rows=None):
    """Полоска «кроп → прочитанное» в одном PNG для сверки глазами."""
    from PIL import Image, ImageDraw, ImageFont
    rows = rows or len(crops)
    if not rows:
        return None
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
    ims = []
    for (crop, text) in zip(crops[:rows], texts[:rows]):
        h = int(crop.shape[0] * (width / 2) / max(1, crop.shape[1]))
        im = Image.fromarray(crop).convert('RGB').resize((width // 2, max(12, h)))
        ims.append((im, text))
    H = sum(i.height + 34 for i, _ in ims)
    sheet = Image.new('RGB', (width, H), (240, 240, 244))
    d = ImageDraw.Draw(sheet)
    y = 0
    for im, text in ims:
        sheet.paste(im, (0, y))
        d.text((width // 2 + 10, y + 6), text[:70], fill=(20, 20, 26), font=font)
        y += im.height + 34
    return sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pages', nargs='+', required=True)
    ap.add_argument('--out', default=os.path.join(ROOT, 'out', 'eval'))
    ap.add_argument('--eslav', default=os.environ.get('OWNOCR_ESLAV_MODEL', ''))
    a = ap.parse_args()
    if a.eslav:
        os.environ['OWNOCR_ESLAV_MODEL'] = a.eslav
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)

    reader = pr.OwnReader(os.path.join(ROOT, 'model'))
    report = {}
    for path in a.pages:
        g = cv2.imread(path, cv2.IMREAD_GRAYSCALE) if path.lower().endswith('.png') \
            else cv2.imread(path)
        if g is None:
            print(path, 'не читается'); continue
        name = os.path.splitext(os.path.basename(path))[0]
        t0 = time.time()
        text = reader.read(g)[0]
        dt = time.time() - t0
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        rep = {'файл': path, 'размер': f'{g.shape[1]}×{g.shape[0]}',
               'время_с': round(dt, 1), 'реплик': len(lines), 'тексты': lines}
        ref = os.path.splitext(path)[0] + '.txt'
        if os.path.exists(ref):
            want = [l.strip() for l in open(ref, encoding='utf-8') if l.strip()]
            cers = [pr.cer(pr.clean(w), pr.clean(t)) for w, t in zip(want, lines)]
            rep.update({'эталон': want, 'cer': round(100 * float(np.mean(cers)), 1) if cers else None,
                        'пар': len(cers)})
        report[name] = rep
        print(f"{name}: {rep['размер']} · {rep['реплик']} реплик · {rep['время_с']} с"
              + (f" · CER {rep['cer']} % ({rep['пар']} пар)" if rep.get('cer') is not None else ''))
        for i, l in enumerate(lines, 1):
            print(f'   {i}. {l}')
    with open(a.out + '.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print('json:', a.out + '.json')


if __name__ == '__main__':
    main()
