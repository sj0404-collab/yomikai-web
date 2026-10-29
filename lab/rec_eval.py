#!/usr/bin/env python3
"""Замер распознавателя строк на нашей разметке — вне приложения, на Python.

Зачем: чтобы «дообучить/улучшить» было чем мерить. Приложение считает CER
внутри Chromium (`lab/eval_in_app.py`), это медленно и не даёт перебирать
варианты подготовки кропа. Здесь тот же контракт модели, что в приложении:

  вход  float32 [1, 3, 48, W],  W кратно 8, хвост нулями, минимум 320
  пиксели: ((x / 255) - 0.5) / 0.5, порядок каналов RGB
  выход float32 [1, T, 519]: 0 = blank, 1..517 = charset, 518 = пробел

Что можно перебирать: подготовку кропа (интерполяция, увеличение, резкость,
бинаризация) и разбор выхода (жадно / с подсловным словарём).

  python3 lab/rec_eval.py --split val                      # точка отсчёта
  python3 lab/rec_eval.py --split val --prep lanczos3       # другой вариант
  python3 lab/rec_eval.py --split all --beam                # со словарным лучом
"""
import argparse
import csv
import json
import os
import sys

import cv2
import numpy as np
import onnxruntime as ort

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINES = os.path.join(ROOT, 'data', 'lines')
CHARSET = os.path.join(ROOT, 'apk', 'app', 'src', 'main', 'assets', 'models', 'charset.txt')


def load_vocab():
    chars = open(CHARSET, encoding='utf-8').read().split('\n')
    # 0 — blank, 1..517 — charset, 518 — пробел (контракт приложения)
    return [''] + chars[:517] + [' ']


def load_rows(split, root=None):
    root = root or LINES
    rows = []
    with open(os.path.join(root, 'labels.tsv'), encoding='utf-8') as f:
        for rec in csv.reader(f, delimiter='\t'):
            name, text = rec[0], rec[1]
            part = rec[3] if len(rec) > 3 else 'all'
            page = rec[2] if len(rec) > 2 else ''
            if split != 'all' and part != split:
                continue
            rows.append((name, text, page))
    return rows


# Латинские и греческие двойники кириллицы: модель обучена на смеси шрифтов и
# часто отдаёт «OHA» вместо «ОНА». Приложение это чинит (fixLookalikes), поэтому
# и замер должен считать так же — иначе CER врёт про качество.
LOOKALIKE = {
    'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К', 'M': 'М', 'O': 'О',
    'P': 'Р', 'T': 'Т', 'X': 'Х', 'Y': 'У', 'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о',
    'p': 'р', 'x': 'х', 'y': 'у', 'b': 'ь', 'H': 'Н', '3': 'З', '0': 'О',
    'Δ': 'Д', 'Ο': 'О', 'Τ': 'Т', 'Β': 'В', 'Α': 'А', 'Λ': 'Л', '1': 'I',
}


def fix_lookalikes(text):
    out = []
    for ch in text:
        out.append(LOOKALIKE.get(ch, ch))
    t = ''.join(out).replace('I', 'И').replace('i', 'и')
    return t


def trim_ink(img):
    """Обрезать кроп до полосы с настоящими чернилами.

    Детектор отдаёт рамку заметно выше строки, и в кроп попадает обрезок
    соседней строки сверху/снизу (видно на листе разметки: «5 ЙЕН» над
    «ПОДОЙДЕТ»). Модель тогда читает два текста сразу и путается. Берём полосу
    строк наибольшей «чернильности».
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    thr = 128
    ink = (gray < thr).sum(axis=1)                     # тёмных пикселей в строке
    if ink.max() <= 0:
        return img
    rows = np.where(ink > max(2, int(img.shape[1] * 0.01)))[0]
    if len(rows) < 4:
        return img
    # склеиваем соседние строки в полосы, берём самую высокую
    bands, start, prev = [], rows[0], rows[0]
    for y in rows[1:]:
        if y - prev > 2:
            bands.append((start, prev))
            start = y
        prev = y
    bands.append((start, prev))
    h = img.shape[0]
    a, b = max(bands, key=lambda t: t[1] - t[0])
    if b - a < 6:
        return img
    pad = max(1, int((b - a) * 0.06))
    return img[max(0, a - pad):min(h, b + pad + 1)]


def pad_white(img, frac):
    """Поля по краям белым — как ступень `pad15` в приложении."""
    h, w = img.shape[:2]
    dy, dx = int(h * frac), int(w * frac)
    return cv2.copyMakeBorder(img, dy, dy, dx, dx, cv2.BORDER_CONSTANT, value=(255, 255, 255))


def prep(img, mode):
    """Как приложение: высота 48, ширина по пропорции, дополнение до 320.

    Приставка `pad15/` и `pad10/` добавляет поля, как в приложении: без них
    крайние буквы обрезаны и CER выходит хуже (4,9 % против 2,9 % в приложении).
    """
    if mode.startswith('trim-'):
        img = trim_ink(img)
        mode = mode[5:]
    if mode.startswith('pad'):
        frac, rest = mode.split('/', 1)
        img = pad_white(img, float(frac[3:]) / 100)
        mode = rest
    h0, w0 = img.shape[:2]
    if w0 < 2 or h0 < 2:
        return None
    if h0 > w0 * 1.8:                                  # вертикальный кроп — поворот
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        h0, w0 = img.shape[:2]
    width = int(round(48 * w0 / h0))
    width = max(8, min(960, width))

    if mode == 'linear':                               # как canvas 'high' в приложении
        interp = cv2.INTER_LINEAR
        src = img
    elif mode == 'cubic2':                            # ×2 кубиком, потом резкость, потом уменьшение
        big = cv2.resize(img, (max(w0 * 2, 8), max(h0 * 2, 8)), interpolation=cv2.INTER_CUBIC)
        blur = cv2.GaussianBlur(big, (0, 0), 1.0)
        big = cv2.addWeighted(big, 1.5, blur, -0.5, 0)
        src, interp = big, cv2.INTER_CUBIC
    elif mode == 'up15':                              # ×1,5 перед уменьшением
        big = cv2.resize(img, (max(int(w0 * 1.5), 8), max(int(h0 * 1.5), 8)), interpolation=cv2.INTER_CUBIC)
        src, interp = big, cv2.INTER_AREA
    elif mode == 'area':
        interp = cv2.INTER_AREA
        src = img
    elif mode == 'lanczos':
        interp = cv2.INTER_LANCZOS4
        src = img
    elif mode == 'cubic':
        interp = cv2.INTER_CUBIC
        src = img
    elif mode == 'lanczos_sharp':                      # сначала ×2 ланчосом, потом резкость
        big = cv2.resize(img, (w0 * 2, h0 * 2), interpolation=cv2.INTER_LANCZOS4)
        blur = cv2.GaussianBlur(big, (0, 0), 1.0)
        big = cv2.addWeighted(big, 1.6, blur, -0.6, 0)
        src, interp = big, cv2.INTER_LANCZOS4
    elif mode == 'lanczos_usm':                        # ланчос + unsharp mask
        big = cv2.resize(img, (max(w0 * 2, 8), max(h0 * 2, 8)), interpolation=cv2.INTER_LANCZOS4)
        g = cv2.GaussianBlur(big, (0, 0), 1.2)
        big = cv2.addWeighted(big, 1.9, g, -0.9, 0)
        src, interp = big, cv2.INTER_LANCZOS4
    elif mode == 'otsu':                               # бинаризация, потом уменьшение
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        src = cv2.cvtColor(bw, cv2.COLOR_GRAY2BGR)
        interp = cv2.INTER_AREA
    elif mode == 'gray_lanczos':                       # серое → ланчос
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        src = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        interp = cv2.INTER_LANCZOS4
    else:
        raise SystemExit('неизвестная подготовка: ' + mode)

    sh, sw = src.shape[:2]
    width = max(8, min(960, int(round(48 * sw / sh))))
    resized = cv2.resize(src, (width, 48), interpolation=interp)
    padded = max(320, width + ((8 - width % 8) % 8))
    # ВАЖНО как в приложении: нормируются ТОЛЬКО настоящие пиксели, дополнение
    # остаётся нулём (0.0 — серый), а не −1. Если нормализовать и дополнение,
    # модель на хвосте выдаёт мусор («…ПОЙДУ» → «ПОЙΔYYwb»), и замер врёт
    # в разы: было 23–25 % CER вместо 3 %.
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
    rgb = (rgb / 255.0 - 0.5) / 0.5
    x = np.zeros((48, padded, 3), dtype=np.float32)
    x[:, :width] = rgb
    x = np.transpose(x, (2, 0, 1))[None, ...]
    return np.ascontiguousarray(x, dtype=np.float32)


def greedy(probs, vocab):
    """Жадный CTC: лучший класс на кадр, повторы и blank убираем (как в приложении)."""
    idx = probs.argmax(axis=1)
    out, prev = [], 0
    for i in idx:
        if i != 0 and i != prev:
            out.append(vocab[i] if i < len(vocab) else '')
        prev = i
    return ''.join(out)


def cer(ref, hyp):
    """Доля правок: расстояние Левенштейна / длина эталона."""
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
    ap.add_argument('--split', default='val', choices=['val', 'train', 'all'])
    ap.add_argument('--prep', default='linear')
    ap.add_argument('--set', default='lines', choices=['lines', 'real'],
                    help='lines — набор из 160 строк (27.10), real — 42 строки с настоящей страницы dense')
    ap.add_argument('--onnx', default=os.path.join(ROOT, 'models', 'koma_rec.onnx'))
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--show', type=int, default=8, help='сколько ошибок напечатать')
    ap.add_argument('--fix-look', action='store_true', help='чинить двойники букв, как приложение')
    args = ap.parse_args()

    vocab = load_vocab()
    real = args.set == 'real'
    root = os.path.join(ROOT, 'data', 'lines-real') if real else LINES
    globals()['LINES'] = root
    rows = load_rows('all' if real else args.split, root)
    if args.limit:
        rows = rows[:args.limit]
    sess = ort.InferenceSession(args.onnx, providers=['CPUExecutionProvider'])
    name = sess.get_inputs()[0].name

    cers, exact, bad, buckets = [], 0, [], {}
    for fn, ref, page in rows:
        path = os.path.join(LINES, fn)
        if not os.path.exists(path):
            continue
        img = cv2.imread(path)
        if img is None:
            continue
        x = prep(img, args.prep)
        if x is None:
            continue
        probs = sess.run(None, {name: x})[0][0]
        hyp = greedy(probs, vocab)
        if args.fix_look:
            hyp = fix_lookalikes(hyp)
        c = cer(ref, hyp)
        hpx = min(img.shape[0], img.shape[1] if img.ndim > 1 else img.shape[0])
        buckets.setdefault('мелкие ≤ 12 px' if hpx <= 12 else 'крупные > 12 px', []).append((c, ref, hyp))
        cers.append(c)
        if c == 0:
            exact += 1
        else:
            bad.append((c, ref, hyp, fn))

    if not cers:
        print('нет строк для замера')
        return 1
    bad.sort(reverse=True)
    print(f'{os.path.basename(args.onnx)} · подготовка {args.prep} · {args.split}: '
          f'строк {len(cers)}, CER {100 * sum(cers) / len(cers):.1f} %, '
          f'целиком верных {exact}/{len(cers)}')
    for name, items in sorted(buckets.items()):
        print(f'   {name}: строк {len(items)}, CER {100 * sum(i[0] for i in items) / len(items):.1f} %')
    for c, ref, hyp, fn in bad[:args.show]:
        print(f'   {100 * c:5.1f} %  эталон: {ref}')
        print(f'            модель: {hyp}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
