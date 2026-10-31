"""Связка: детектор приложения находит текст, свой ученик читает строки.

Общий модуль для `scripts/10_pair_page.py` (одна страница) и
`scripts/11_three_variants.py` (цвет / ч-б / инверсия).
"""
from __future__ import annotations

import os
import time

import cv2
import numpy as np
from PIL import Image

from .engine import OwnOCR
from .page_det import PageDetector, Region, bubbles_of, split_panels, text_lines

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def is_harsh_page(rgb: np.ndarray) -> bool:
    """Страница без полутонов: чёрно-белая после скана или печати."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) if rgb.ndim == 3 else rgb
    return len(np.unique(gray[::4, ::4])) <= 8


def normalize_page(rgb: np.ndarray) -> np.ndarray:
    """Привести страницу к одному виду: тёмные буквы на светлом фоне.

    Зачем: та же страница приходит в трёх видах — цветная, чёрно-белая
    (после сканирования/печати) и инверсированная (тёмная тема читалки). Если
    этот шаг пропустить, инверсия даёт **ноль** реплик: ищем чёрное на белом,
    а там белое на чёрном. Определяем полярность по доле тёмных пикселей.

    Замер: без этого шага инверсия давала 0 реплик вместо 9.
    """
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) if rgb.ndim == 3 else rgb
    dark = float((gray < 128).mean())
    if dark > 0.55:                       # инверсия: белое на чёрном
        rgb = 255 - rgb
        gray = 255 - gray
    if rgb.ndim == 2:
        rgb = np.dstack([rgb] * 3)
    elif rgb.shape[2] == 4:
        rgb = rgb[:, :, :3]
    return rgb


VOCAB = set(w.strip().upper() for w in
             open(os.path.join(ROOT, 'ownocr', 'vocab-ru.txt'), encoding='utf-8'))


def cer(ref: str, hyp: str) -> float:
    """Доля правок (Левенштейн по символам) к длине эталона."""
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(ref) + 1))
    for i, ch in enumerate(hyp, 1):
        cur = [i]
        for j, rc in enumerate(ref, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != ch)))
        prev = cur
    return prev[-1] / len(ref)


def known_words(text: str) -> int:
    """Сколько слов реплики есть в словаре (25 000 частых русских слов)."""
    words = [w.strip('.,!?…—«»"():;%') for w in text.upper().replace('-', ' ').split()]
    return sum(1 for w in words if len(w) >= 3 and w in VOCAB)


def clean(text: str) -> str:
    return ''.join(c for c in text.upper() if c.isalnum() or c == ' ').strip()


class CtcReader:
    """Распознаватель приложения (PP-OCR CTC) — для честного сравнения."""

    def __init__(self, model: str, dictionary: str):
        import onnxruntime as ort
        self.sess = ort.InferenceSession(model, providers=['CPUExecutionProvider'])
        self.name = self.sess.get_inputs()[0].name
        letters = open(dictionary, encoding='utf-8').read().splitlines()
        self.dictionary = [''] + letters + [' ']

    def read(self, rgb: np.ndarray) -> tuple[str, float]:
        ch, cw = rgb.shape[:2]
        width = int(np.clip(round(48 * cw / ch), 8, 960))
        canvas = np.full((48, max(320, width), 3), 128, dtype=np.uint8)
        canvas[:, :width] = np.array(Image.fromarray(rgb).resize((width, 48), Image.BILINEAR))
        x = np.transpose((canvas.astype(np.float32) / 255.0 - 0.5) / 0.5, (2, 0, 1))[None]
        logits = self.sess.run(None, {self.name: x})[0][0]
        text, score, count, prev = [], 0.0, 0, 0
        for row in logits:
            best = int(np.argmax(row))
            if best != 0 and best != prev:
                text.append(self.dictionary[best] if best < len(self.dictionary) else '')
                score += float(row[best])
                count += 1
            prev = best
        return ''.join(text), (score / count if count else 0.0)


class OwnReader:
    """Свой ученик: читает строку целиком (boxes/segment/auto внутри движка).

    Строка со страницы мельче, чем глифы листа (на манге высота буквы ~20 px,
    на листе 30 px), поэтому кроп увеличивается. Один масштаб — лотерея: на ×2
    «ПОЖАЛУЙСТА» читается «ПОЖАЛУ№П%», на ×3 — «ПОЖАЛУЙСТА». Берём оба и
    оставляем прочтение с большей уверенностью; если на ×2 ученик уже уверен
    (≥ 0,8), ×3 не запускаем — страница читается вдвое быстрее.
    """

    # Пороги подобраны перебором на плотной странице. Для чёрно-белой страницы
    # (без сглаженных краёв у букв) нужен более крупный масштаб и лёгкое
    # размытие уже после увеличения — так буквы снова получают градиент, на
    # котором учился ученик.
    def __init__(self, model_dir: str, scales=(2.0, 3.0), sure: float = 0.8,
                 scales_harsh=(3.0, 4.0, 5.0), blur_harsh: bool = False):
        self.ocr = OwnOCR(model_dir)
        self.scales, self.sure = tuple(scales), float(sure)
        self.scales_harsh = tuple(scales_harsh)
        self.blur_harsh = blur_harsh

    def read(self, gray: np.ndarray, harsh: bool = False) -> tuple[str, float]:
        import cv2

        g = np.asarray(gray)
        if g.ndim == 3:
            g = cv2.cvtColor(g, cv2.COLOR_RGB2GRAY)
        # Обрезаем кроп по чернилам: в кроп от детектора попадает фон и
        # соседние штрихи, из-за них строка читается хуже.
        ys, xs = np.where(g < 160)
        if len(ys):
            y0, y1 = max(0, ys.min() - 2), min(g.shape[0], ys.max() + 3)
            x0, x1 = max(0, xs.min() - 2), min(g.shape[1], xs.max() + 3)
            if y1 - y0 >= 6 and x1 - x0 >= 6:
                g = g[y0:y1, x0:x1]
        best: tuple[str, float] = ('', -1.0)
        scales = self.scales_harsh if harsh else self.scales
        for i, k in enumerate(scales):
            big = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC) if k > 1.01 else g
            if harsh and self.blur_harsh:
                big = cv2.GaussianBlur(big, (3, 3), 0)
            r = self.ocr.read_line(big, lexicon=True)
            conf = float(r.get('conf', 0.0))
            if conf > best[1]:
                best = (r['text'], conf)
            if i == 0 and conf >= self.sure:
                break
        return best


def read_page(det: PageDetector, reader, rgb: np.ndarray, minconf: float = 0.8):
    harsh = is_harsh_page(rgb)
    rgb = normalize_page(rgb)
    gray = np.array(Image.fromarray(rgb).convert('L'))
    H, W = gray.shape
    t0 = time.time()
    boxes = det.detect_page(rgb)
    n_boxes = len(boxes)
    regions, n_lines = [], 0
    for box in boxes[:400]:
        for (x0, y0, x1, y1) in text_lines(rgb, box):
            n_lines += 1
            crop = rgb[y0:y1, x0:x1]
            if crop.size == 0:
                continue
            if crop.shape[0] > crop.shape[1] * 1.8:          # вертикальная надпись
                crop = np.rot90(crop, k=-1)
            if hasattr(reader, 'ocr'):
                text, score = reader.read(np.array(Image.fromarray(crop).convert('L')), harsh=harsh)
            else:
                text, score = reader.read(crop)
            text = text.strip()
            alnum = sum(c.isalnum() for c in text)
            if text and score >= minconf and alnum >= 2 and alnum / max(1, len(text)) >= 0.5:
                regions.append(Region(text, x0 / W, y0 / H, x1 / W, y1 / H, score))
    lines = [line for panel in split_panels(regions, True) for line in bubbles_of(panel, True)]
    # Отбраковка «неречи» на уровне собранной реплики, а не отдельных кусков:
    # если фильтровать куски, мусор с рисунка перестаёт склеивать облачка и одна
    # реплика рвётся на две. Реплика без единого словарного слова — это подпись
    # рисунка, водяной знак или штриховка, прочитанная как буквы.
    kept = [line for line in lines if known_words(line.text) >= 1]
    return {'replies': kept, 'dropped': len(lines) - len(kept), 'boxes': n_boxes,
            'lines': n_lines, 'harsh': harsh, 'seconds': time.time() - t0}


