"""Один лист: 100+ кириллических шрифтов на одной странице.

Лист — это и есть учебник. Шрифтовые файлы нужны только чтобы нарисовать лист;
дальше ученик видит ТОЛЬКО пиксели листа и подписи к ним (какая буква где).

Раскладка строки: слева имя шрифта (мелко, чтобы учитель знал, кто это), справа
алфавит с цифрами и знаками. Каждый глиф рисуется отдельно и его рамка
запоминается в манифесте — поэтому «нарезка» листа на буквы честная, без
угадывания границ.
"""
from __future__ import annotations

import json
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ALPHABET = (
    'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ'
    'абвгдеёжзийклмнопрстуфхцчшщъыьэюя'
    '0123456789'
    ',.!?-:;()«»"№%'
)
LABEL_W = 210          # левая колонка с именем шрифта
PAD = 10
CHAR_GAP = 7


def font_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0].replace('_', ' ')


def _has_glyph(font: ImageFont.FreeTypeFont, ch: str) -> bool:
    try:
        box = font.getbbox(ch)
    except Exception:
        return False
    return box is not None and box[2] > box[0] and box[3] > box[1]


def render_sheet(font_paths, out_png: str, out_manifest: str, px: int = 30,
                 holdout_every: int = 5) -> dict:
    """Нарисовать один лист и вернуть манифест (где какая буква)."""
    label_font = None
    for cand in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                 '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
                 '/usr/share/fonts/truetype/freefont/FreeSans.ttf'):
        try:
            label_font = ImageFont.truetype(cand, 15)
            break
        except Exception:
            continue
    if label_font is None:
        label_font = ImageFont.load_default()
    rows = []
    for i, path in enumerate(font_paths):
        try:
            font = ImageFont.truetype(path, px)
        except Exception:
            continue
        widths = []
        for ch in ALPHABET:
            try:
                widths.append(float(font.getlength(ch)) if _has_glyph(font, ch) else 8.0)
            except Exception:
                widths.append(8.0)
        rows.append({'path': path, 'font': font_name(path), 'px': px,
                     'holdout': (i % holdout_every == 0), 'widths': widths})

    row_h = px + 22
    # ширина листа = самая длинная строка (иначе правые буквы обрезаются —
    # ровно это и случилось в первом прогоне: 11 698 глифов в манифесте,
    # а нарезалось 6 952)
    width = int(LABEL_W + max(sum(r['widths']) for r in rows)
                + CHAR_GAP * len(ALPHABET) + 2 * PAD)
    height = row_h * len(rows) + 2 * PAD
    sheet = Image.new('L', (width, height), 255)
    draw = ImageDraw.Draw(sheet)
    manifest = []

    for ri, row in enumerate(rows):
        y = PAD + ri * row_h
        draw.text((6, y + px // 2 - 6), row['font'][:30], font=label_font, fill=140)
        font = ImageFont.truetype(row['path'], px)
        x = LABEL_W
        baseline_top = y + 4
        for ci, ch in enumerate(ALPHABET):
            try:
                box = font.getbbox(ch)
            except Exception:
                box = None
            if box is None or box[2] <= box[0]:
                x += 8
                continue
            draw.text((x, baseline_top), ch, font=font, fill=20)
            x0, y0 = x + box[0], baseline_top + box[1]
            x1, y1 = x + box[2], baseline_top + box[3]
            if x1 > x0 and y1 > y0:
                manifest.append({'row': ri, 'font': row['font'], 'holdout': row['holdout'],
                                 'char': ch, 'box': [int(x0) - 1, int(y0) - 1,
                                                     int(x1) + 1, int(y1) + 1]})
            x += row['widths'][ci] + CHAR_GAP
        # тонкая линия-разделитель строк, чтобы лист читался глазами
        draw.line([(4, y + row_h - 3), (width - 4, y + row_h - 3)], fill=232)

    os.makedirs(os.path.dirname(out_png) or '.', exist_ok=True)
    sheet.save(out_png)
    meta = {'px': px, 'fonts': len(rows), 'glyphs': len(manifest),
            'holdout_fonts': sum(1 for r in rows if r['holdout']),
            'alphabet': ALPHABET, 'size': [width, height]}
    json.dump({'meta': meta, 'glyphs': manifest}, open(out_manifest, 'w'), ensure_ascii=False)
    return meta


def load_sheet(png: str, manifest: str):
    """Нарезать лист обратно на глифы: (картинки, подписи, шрифты, holdout)."""
    img = cv2.imread(png, cv2.IMREAD_GRAYSCALE)
    data = json.load(open(manifest, encoding='utf-8'))
    imgs, labels, fonts, hold = [], [], [], []
    for g in data['glyphs']:
        x0, y0, x1, y1 = g['box']
        crop = img[max(0, y0):y1, max(0, x0):x1]
        if crop.size == 0:
            continue
        imgs.append(crop)
        labels.append(g['char'])
        fonts.append(g['font'])
        hold.append(g['holdout'])
    return imgs, labels, fonts, np.array(hold, bool), data


# ── «упражнения», которые задаёт учитель ────────────────────────────────────
def augment(gray: np.ndarray, rng: np.random.Generator, mode: str = 'easy') -> np.ndarray:
    """Испортить глиф так, как его портит скан: поворот, кегль, жирность, шум."""
    img = gray
    if mode in ('easy', 'hard', 'italic'):
        ang = rng.uniform(-4, 4) if mode == 'easy' else rng.uniform(-12, 12)
        h, w = img.shape
        m = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
        img = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    if mode == 'italic':                                   # наклон строки, как курсив
        h, w = img.shape
        shear = rng.uniform(-0.35, 0.35)
        m = np.float32([[1, shear, -shear * h / 2], [0, 1, 0]])
        img = cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    # кегль: для «мелкого кегля» специально уменьшаем и обратно не растягиваем
    k = rng.uniform(0.85, 1.25) if mode != 'small' else rng.uniform(0.45, 0.7)
    if abs(k - 1.0) > 0.02:
        img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    # жирность: размытие/эрозия имитируют нажим пера и потерю штриха
    if rng.random() < 0.5:
        img = cv2.GaussianBlur(img, (3, 3), rng.uniform(0.3, 1.1))
    if rng.random() < 0.35:
        kk = np.ones((2, 2), np.uint8)
        img = cv2.erode(img, kk) if rng.random() < 0.5 else cv2.dilate(img, kk)
    if mode in ('hard', 'small') and rng.random() < 0.5:   # шум сканера
        noise = rng.normal(0, rng.uniform(4, 16), img.shape)
        img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
    return img
