#!/usr/bin/env python3
"""Итоговые замеры своего движка: всё, что попадает в отчёт.

  python3 scripts/05_metrics.py
"""
import csv
import glob
import json
import os
import sys
import time

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr import data as D                       # noqa: E402
from ownocr.engine import OwnOCR, cer              # noqa: E402
from ownocr.features import features               # noqa: E402
from ownocr.lesson_real import align, read_rows    # noqa: E402
from ownocr.engine import binarize, boxes_of       # noqa: E402

OUT = os.path.join(ROOT, 'out')
MODEL = os.path.join(ROOT, 'model')
FONTS = '/var/tmp/ownocr/fonts'


def glyph_metrics(ocr: OwnOCR, manifest: str, sheet: str, mode='clean'):
    meta = json.load(open(manifest, encoding='utf-8'))
    img = cv2.imread(sheet, cv2.IMREAD_GRAYSCALE)
    rng = np.random.default_rng(4242)
    imgs, labs = [], []
    for g in meta['glyphs']:
        if not g['holdout']:
            continue
        x0, y0, x1, y1 = g['box']
        crop = img[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0:
            continue
        imgs.append(crop)
        labs.append(g['char'].upper())
    if mode != 'clean':
        imgs = [D.augment(i, rng, mode) for i in imgs]
    feats = [features(i) for i in imgs]
    keep = [(f, l) for f, l in zip(feats, labs) if f is not None]
    X = np.stack([f for f, _ in keep])
    pred = ocr.model.predict_proba(X).argmax(axis=1)
    acc = float(np.mean([ocr.classes[p] == l for p, (_, l) in zip(pred, keep)]))
    return {'acc': acc, 'n': len(keep)}


def prose_metrics(ocr: OwnOCR, manifest: str):
    """Строки прозы в ОТЛОЖЕННЫХ шрифтах — то, что движок умеет целиком."""
    meta = json.load(open(manifest, encoding='utf-8'))
    hold = sorted({g['font'] for g in meta['glyphs'] if g['holdout']})[:12]
    paths = {os.path.splitext(os.path.basename(p))[0].replace('_', ' '): p
             for p in glob.glob(os.path.join(FONTS, '*.ttf'))}
    phrases = ['ПОЖАЛУЙСТА, СНИМИ С ХАНЫ ЭТО ПРОКЛЯТИЕ',
               'Я РАССЧИТЫВАЮ НА ВАС, ДУХИ',
               'ГОТОВО, НЕ ЗНАЮ, ПОМОЖЕТ ЛИ ЭТО']
    rows = []
    for fon in hold:
        p = paths.get(fon)
        if not p:
            continue
        for ph in phrases:
            f = ImageFont.truetype(p, 28)
            w = int(f.getlength(ph)) + 20
            img = Image.new('L', (w, 54), 255)
            ImageDraw.Draw(img).text((10, 8), ph, font=f, fill=25)
            arr = cv2.GaussianBlur(np.array(img), (3, 3), 0.5)
            r = ocr.read_line(arr, lexicon=True)
            rows.append({'font': fon, 'ref': ph, 'hyp': r['text'], 'cer': cer(ph, r['text'])})
    return {'n': len(rows), 'cer': float(np.mean([r['cer'] for r in rows])),
            'exact': sum(1 for r in rows if r['cer'] == 0), 'rows': rows}


def manga_metrics(ocr: OwnOCR, labels: str):
    rows = [(os.path.join(os.path.dirname(labels), n), t) for n, t in read_rows(labels)]
    detail = []
    for name, ref in rows:
        gray = cv2.imread(name, cv2.IMREAD_GRAYSCALE)
        r = ocr.read_line(gray, lexicon=True) if gray is not None else {'text': '', 'glyphs': []}
        detail.append({'file': os.path.basename(name), 'ref': ref, 'hyp': r['text'],
                       'cer': cer(ref, r['text'])})
    # точность по буквам там, где выравнивание надёжно
    pairs_ok = pairs_all = 0
    for name, ref in rows:
        gray = cv2.imread(name, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        from ownocr.engine import line_band
        bw = binarize(gray)
        y0, y1 = line_band(bw)
        gray, bw = gray[y0:y1], binarize(gray[y0:y1])
        boxes = boxes_of(bw)
        feats = [features(gray[max(0, b[1]):b[3], max(0, b[0]):b[2]]) for b in boxes]
        good = [(b, f) for b, f in zip(boxes, feats) if f is not None]
        if not good:
            continue
        probs = ocr.model.predict_proba(np.stack([f for _, f in good]))
        text = ''.join(c for c in ref.upper() if c.isalnum())
        al = align([b for b, _ in good], text, probs, ocr.classes)
        if len(al) < 0.8 * len(text):
            continue
        for i, j in al:
            pairs_all += 1
            pairs_ok += int(ocr.classes[int(probs[i].argmax())] == text[j])
    return {'n': len(rows), 'cer': float(np.mean([d['cer'] for d in detail])),
            'exact': sum(1 for d in detail if d['cer'] == 0),
            'letter_acc': pairs_ok / max(1, pairs_all), 'letters': pairs_all,
            'rows': detail}


def speed(ocr: OwnOCR, manifest: str):
    meta = json.load(open(manifest, encoding='utf-8'))
    img = cv2.imread(os.path.join(OUT, 'sheet.png'), cv2.IMREAD_GRAYSCALE)
    row = [g for g in meta['glyphs'] if g['row'] == 7]
    y0 = min(g['box'][1] for g in row) - 3
    y1 = max(g['box'][3] for g in row) + 3
    x0 = min(g['box'][0] for g in row) - 3
    x1 = max(g['box'][2] for g in row) + 3
    strip = img[y0:y1, x0:x1]
    t = time.time()
    for _ in range(20):
        ocr.read_line(strip)
    ms = (time.time() - t) / 20 * 1000
    return {'line_ms': ms, 'line_px': [x1 - x0, y1 - y0]}


def labels_path():
    own = os.path.join(ROOT, 'data-real', 'labels.tsv')
    return own if os.path.exists(own) else os.path.join(ROOT, '..', 'data', 'lines-real', 'labels.tsv')


def main():
    ocr = OwnOCR(MODEL)
    manifest = os.path.join(OUT, 'sheet-manifest.json')
    sheet = os.path.join(OUT, 'sheet.png')
    res = {
        'classes': len(ocr.classes),
        'vocab': len(ocr.vocab),
        'model_size_kb': round(os.path.getsize(os.path.join(MODEL, 'ownocr.npz')) / 1024, 1),
        'params': int(ocr.model.W1.size + ocr.model.b1.size + ocr.model.W2.size + ocr.model.b2.size),
        'sheet_clean': glyph_metrics(ocr, manifest, sheet, 'clean'),
        'sheet_small': glyph_metrics(ocr, manifest, sheet, 'small'),
        'sheet_italic': glyph_metrics(ocr, manifest, sheet, 'italic'),
        'prose': prose_metrics(ocr, manifest),
        'manga': manga_metrics(ocr, labels_path()),
        'speed': speed(ocr, manifest),
    }
    json.dump(res, open(os.path.join(OUT, 'metrics.json'), 'w'), ensure_ascii=False, indent=1)

    print(f'классов {res["classes"]} · словарь {res["vocab"]} слов · '
          f'модель {res["model_size_kb"]} КБ · {res["params"]} чисел')
    print(f'шрифты, которых не было в обучении (26): '
          f'{100 * res["sheet_clean"]["acc"]:.1f} % (N={res["sheet_clean"]["n"]}) · '
          f'наклон/курсив {100 * res["sheet_italic"]["acc"]:.1f} % · '
          f'мелкий кегль {100 * res["sheet_small"]["acc"]:.1f} %')
    print(f'строки прозы в отложенных шрифтах: CER {100 * res["prose"]["cer"]:.1f} % · '
          f'целиком верных {res["prose"]["exact"]}/{res["prose"]["n"]}')
    print(f'страница манги: CER {100 * res["manga"]["cer"]:.1f} % · '
          f'верных {res["manga"]["exact"]}/{res["manga"]["n"]} · '
          f'по буквам {100 * res["manga"]["letter_acc"]:.1f} % (N={res["manga"]["letters"]})')
    print(f'скорость: {res["speed"]["line_ms"]:.0f} мс на строку '
          f'{res["speed"]["line_px"][0]}×{res["speed"]["line_px"][1]} px (одно ядро)')


if __name__ == '__main__':
    main()
