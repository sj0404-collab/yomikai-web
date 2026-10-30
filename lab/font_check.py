#!/usr/bin/env python3
"""Как распознаватель читает КОНКРЕТНЫЕ шрифты — проверка шрифтов как материала.

Зачем: в синтетике для обучения сейчас DejaVu/Liberation и три самодельных
(AnimeAceCyr, ComicsCyr, MangaCyr). Рукописные шрифты (Caveat, MarckScript,
Neucha, Kurale, Comfortaa, Oswald) в замерах не участвовали — а именно на них
можно набрать тысячи строк, похожих на мангу.

Здесь один и тот же набор настоящих реплик (data/lines-real/labels.tsv)
рисуется каждым шрифтом в двух размерах (20 и 32 px по высоте строки, как на
странице), слегка размывается — и читается тем же путём, что в приложении:
обрезка до чернил, cubic → 48 px, koma_rec, затем fix_lookalikes.

  python3 lab/font_check.py                       # все шрифты из fonts/
  python3 lab/font_check.py --only MarckScript    # один
  python3 lab/font_check.py --sheet /tmp/f.png    # ещё и контактный лист
"""
import argparse
import csv
import glob
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

import onnxruntime as ort

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIRS = [os.path.join(ROOT, 'fonts', 'probe'), os.path.join(ROOT, 'fonts')]
CHARSET = os.path.join(ROOT, 'apk', 'app', 'src', 'main', 'assets', 'models', 'charset.txt')
if not os.path.exists(CHARSET):
    CHARSET = os.path.join(ROOT, 'charset.txt')
MODEL = os.path.join(ROOT, 'models', 'koma_rec.onnx')
if not os.path.exists(MODEL):                                  # вне клона (песочница)
    MODEL = '/home/user/koma_models/koma_rec.onnx'

LOOKALIKE = {'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К', 'M': 'М',
             'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х', 'Y': 'У', 'a': 'а', 'c': 'с',
             'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х', 'y': 'у', 'b': 'ь', 'Δ': 'Д',
             'Ο': 'О', 'Τ': 'Т', 'Β': 'В', 'Α': 'А', 'Λ': 'Л', '3': 'З', '0': 'О'}


def vocab():
    chars = open(CHARSET, encoding='utf-8').read().split('\n')
    return [''] + chars[:517] + [' ']


def render(text, font_path, px_h):
    font = ImageFont.truetype(font_path, px_h)
    box = font.getbbox(text)
    w = max(8, box[2] - box[0] + 8)
    h = max(8, box[3] - box[1] + 8)
    img = Image.new('L', (w, h), 255)
    ImageDraw.Draw(img).text((4 - box[0], 4 - box[1]), text, font=font, fill=25)
    arr = np.array(img)
    # лёгкое размытие — как скан/фото, иначе замер нечестно лёгкий
    arr = cv2.GaussianBlur(arr, (3, 3), 0.6)
    return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)


def trim_ink(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    ink = (gray < 128).sum(axis=1)
    if ink.max() <= 0:
        return img
    rows = np.where(ink > max(2, int(img.shape[1] * 0.01)))[0]
    if len(rows) < 4:
        return img
    bands, start, prev = [], rows[0], rows[0]
    for y in rows[1:]:
        if y - prev > 2:
            bands.append((start, prev)); start = y
        prev = y
    bands.append((start, prev))
    h = img.shape[0]
    a, b = max(bands, key=lambda t: t[1] - t[0])
    if b - a < 6:
        return img
    pad = max(1, int((b - a) * 0.06))
    return img[max(0, a - pad):min(h, b + pad + 1)]


def prep(img, H=48, MINW=320):
    h, w = img.shape[:2]
    W = max(MINW, int(round(w * H / h / 8)) * 8)
    canvas = np.zeros((H, W, 3), np.float32)          # дополнение = 0, как в приложении
    new_w = max(1, min(W, int(round(w * H / h))))
    small = cv2.resize(img, (new_w, H), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    canvas[:, :new_w] = small[:, :, ::-1]              # BGR → RGB
    x = ((canvas / 255.0) - 0.5) / 0.5
    return np.transpose(x, (2, 0, 1))[None]


def greedy(probs, voc):
    idx = probs.argmax(axis=1)
    out, prev = [], 0
    for i in idx:
        if i != 0 and i != prev:
            out.append(voc[i] if i < len(voc) else '')
        prev = i
    return ''.join(out)


def fix_look(t):
    return ''.join(LOOKALIKE.get(ch, ch) for ch in t)


def norm(s):
    return ''.join(ch for ch in str(s).upper() if ch.isalnum())


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
    ap.add_argument('--only', default='')
    ap.add_argument('--sizes', default='20,32')
    ap.add_argument('--sheet', default='')
    ap.add_argument('--show', type=int, default=4)
    args = ap.parse_args()

    sess = ort.InferenceSession(MODEL, providers=['CPUExecutionProvider'])
    voc = vocab()
    labels = []
    with open(os.path.join(ROOT, 'data', 'lines-real', 'labels.tsv'), encoding='utf-8') as f:
        for rec in csv.reader(f, delimiter='\t'):
            if len(rec) >= 2 and rec[1].strip():
                labels.append(rec[1].strip())
    # только строки, которые шрифт сможет набрать (буквы, цифры, знаки)
    print(f'строк для проверки: {len(labels)}')

    fonts = {}
    for d in FONTS_DIRS:
        for p in sorted(glob.glob(os.path.join(d, '*.ttf')) + glob.glob(os.path.join(d, '*.otf'))):
            fonts[os.path.basename(p).rsplit('.', 1)[0]] = p
    if args.only:
        fonts = {k: v for k, v in fonts.items() if args.only.lower() in k.lower()}
    if not fonts:
        raise SystemExit('шрифтов не найдено')

    sizes = [int(v) for v in args.sizes.split(',')]
    sheet_rows = []
    for name, path in fonts.items():
        for px in sizes:
            cers, exact = [], 0
            for text in labels:
                try:
                    img = render(text, path, px)
                except Exception:
                    continue
                x = prep(trim_ink(img))
                probs = sess.run(None, {'x': x})[0][0]
                hyp = fix_look(greedy(probs, voc))
                c = cer(norm(text), norm(hyp))
                cers.append(c)
                exact += 1 if c == 0 else 0
                if px == sizes[-1]:
                    sheet_rows.append((name, text, hyp))
            if cers:
                print(f'{name:22s} {px:2d} px · CER {100 * sum(cers) / len(cers):5.1f} % '
                      f'· целиком верных {exact}/{len(cers)}')
    if args.sheet and sheet_rows:
        cols = []
        for name in dict.fromkeys(r[0] for r in sheet_rows):
            tile = np.full((len(sheet_rows) // len(fonts) * 34 + 30, 620), 255, np.uint8)
            y = 4
            for nm, ref, hyp in [r for r in sheet_rows if r[0] == name]:
                cv2.putText(tile, hyp[:34], (4, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, 0, 1)
                y += 34
            cv2.putText(tile, name, (4, tile.shape[0] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 120, 1)
            cols.append(cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR))
        cv2.imwrite(args.sheet, np.hstack(cols))
        print('контактный лист:', args.sheet)


if __name__ == '__main__':
    main()
