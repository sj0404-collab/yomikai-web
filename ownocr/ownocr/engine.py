"""Движок чтения: свои разрез строки на буквы, свой сборщик слов.

Три шага, каждый — свой код, без внешних OCR:

  1. РАЗРЕЗ. Чернила по Отсу → связные пятна → склейка мелких пятен с основным
     (точки «Ё», дужка «Й», точки «i», «:») → порядок слева направо.
  2. ЧТЕНИЕ. Каждое пятно → 135 признаков → классификатор → вероятности классов.
     Берём не только лучший класс: храним топ-5, они нужны декодеру.
  3. СБОРКА СЛОВА. Свой beam search по этим топ-5 с двумя оценками:
     сумма log p по буквам + бонус словарю за известное слово (частота слова,
     как в любом OCR). Это чинит «З↔3», «О↔0», «Ъ↔Ь», «Е↔Ё» — пары, которые
     одинаковы по форме, но различаются по смыслу.
"""
from __future__ import annotations

import json
import math
import os

import cv2
import numpy as np

from .features import features

DEFAULT_VOCAB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vocab-ru.txt')


def binarize(gray: np.ndarray) -> np.ndarray:
    """Чернила = 255. Два шага: убрать освещённость, потом Отсу.

    Просто Отсу на скане манги плохо разделяет: фон серый, буквы серые, и порог
    уезжает — на настоящих кропах это давало 21–32 % «чернил» и склейку всех букв
    в одно пятно. Поэтому сначала вычитаем фон (сильное размытие минус кадр) и
    растягиваем контраст: «чернил» становится 14–21 %, буквы распадаются.
    """
    if gray.mean() < 110:
        gray = 255 - gray
    bg = cv2.GaussianBlur(gray, (0, 0), max(3.0, gray.shape[0] / 3.0))
    flat = cv2.normalize(cv2.subtract(bg, gray), None, 0, 255, cv2.NORM_MINMAX)
    _, bw = cv2.threshold(flat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # тонкий шрифт (Cormorant, антиква с волосяными штрихами) на 28 px рвётся на
    # куски: если чернил меньше 8 %, штрих утолщаем на пиксель
    if (bw > 0).mean() < 0.08:
        bw = cv2.dilate(bw, np.ones((2, 2), np.uint8))
    return bw


def line_band(bw: np.ndarray, pad_frac: float = 0.08):
    """Полоса ОДНОЙ строки внутри кропа.

    Детектор в приложении обводит рамку с запасом, и в кроп попадают обрезки
    соседних строк: на настоящих кропах это видно сразу — пятна склеиваются
    через строки, «ПОДОЙДЕТ» вырастает в две строки, и всё чтение ломается.
    Поэтому перед разрезом на буквы берём полосу с наибольшим количеством
    чернил (это и есть строка) и работаем только внутри неё.
    """
    ink = (bw > 0).sum(axis=1)
    if ink.max() <= 0:
        return 0, bw.shape[0]
    thr = max(1, int(0.06 * ink.max()))
    rows = np.where(ink >= thr)[0]
    if len(rows) < 3:
        return 0, bw.shape[0]
    bands, start, prev = [], rows[0], rows[0]
    for y in rows[1:]:
        if y - prev > 2:
            bands.append((start, prev))
            start = y
        prev = y
    bands.append((start, prev))
    # самая «тяжёлая» полоса = строка (по сумме чернил, не по высоте)
    a, b = max(bands, key=lambda t: ink[t[0]:t[1] + 1].sum())
    pad = max(1, int((b - a) * pad_frac))
    return max(0, a - pad), min(bw.shape[0], b + pad + 1)


def boxes_of(bw: np.ndarray, min_area_frac=0.00035):
    """Пятна чернил → рамки букв (с приклейкой диакритики)."""
    H, W = bw.shape
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    boxes = []
    min_area = max(4, min_area_frac * H * W)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < min_area or w < 2 or h < 2:
            continue
        if w > 0.9 * W and h > 0.9 * H:            # рамка панели, не буква
            continue
        if h < max(2, 0.08 * H) and w > 0.6 * W:   # горизонтальная линия
            continue
        boxes.append([int(x), int(y), int(x + w), int(y + h)])

    # приклеить мелкое пятно к основному: точка «Ё», дужка «Й», двоеточие
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                aw, bw_ = a[2] - a[0], b[2] - b[0]
                ov = min(a[2], b[2]) - max(a[0], b[0])
                if ov <= 0:
                    continue
                if ov < 0.55 * min(aw, bw_):
                    continue
                gap = max(a[1], b[1]) - min(a[3], b[3])
                big = max(a[3] - a[1], b[3] - b[1])
                small = min(a[3] - a[1], b[3] - b[1])
                if gap < 0.5 * big and small < 0.62 * big:
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    boxes.pop(j)
                    merged = True
                    break
            if merged:
                break
    boxes = split_wide(boxes, bw)
    boxes.sort(key=lambda b: b[0])
    return boxes


def split_wide(boxes, bw=None, ratio: float = 1.6):
    """Разрезать склеенные буквы по «долинам» вертикальной проекции.

    Рукописный шрифт манги часто пишет буквы встык: «НОШЕНИЯ?» приходит одним
    пятном. Режем такое пятно в местах, где столбцов чернил почти нет, и только
    если кусок заметно шире обычной буквы строки. Ширину «обычной» буквы берём
    как медиану по уже найденным пятнам.
    """
    if not boxes or bw is None or len(boxes) < 2:
        return boxes
    widths = [b[2] - b[0] for b in boxes]
    med = float(np.median(widths))
    if med < 4:
        return boxes
    out = []
    for b in boxes:
        w = b[2] - b[0]
        pieces = max(1, int(round(w / med)))
        if pieces < 2:
            out.append(b)
            continue
        sub = bw[b[1]:b[3], b[0]:b[2]]
        col = (sub > 0).sum(axis=0).astype(np.float32)
        # искать границы рядом с ожидаемыми позициями (по числу «буквных» ширин)
        cuts = [0]
        for k in range(1, pieces):
            expect = int(round(k * w / pieces))
            lo, hi = max(1, expect - max(2, w // (3 * pieces))), min(w - 1, expect + max(2, w // (3 * pieces)))
            if hi <= lo:
                continue
            idx = lo + int(np.argmin(col[lo:hi]))
            if col[idx] > 0.30 * col.max():     # там нет настоящей долины
                continue
            if idx - cuts[-1] < max(3, 0.4 * med) or w - idx < max(3, 0.4 * med):
                continue
            cuts.append(idx)
        cuts.append(w)
        for i in range(len(cuts) - 1):
            x0, x1 = b[0] + cuts[i], b[0] + cuts[i + 1]
            if x1 - x0 >= 2:
                out.append([x0, b[1], x1, b[3]])
    return out


class OwnOCR:
    def __init__(self, model_dir: str, vocab_path: str | None = DEFAULT_VOCAB,
                 vocab_size: int = 40000):
        from .model import OwnClassifier
        meta = json.load(open(os.path.join(model_dir, 'ownocr.npz.json'), encoding='utf-8'))
        self.classes = list(meta['classes'])
        self.case = meta.get('case', 'upper')
        self.model = OwnClassifier(meta['dim'], len(self.classes), hidden=meta.get('hidden', 192))
        self.model.load(os.path.join(model_dir, 'ownocr.npz'))
        self.vocab = {}
        if vocab_path and os.path.exists(vocab_path):
            with open(vocab_path, encoding='utf-8') as f:
                for rank, line in enumerate(f):
                    w = line.strip().upper()
                    if w and len(w) <= 24:
                        self.vocab[w] = rank
                    if len(self.vocab) >= vocab_size:
                        break

    # ── чтение одной строки ──────────────────────────────────────────────────
    def read_line(self, gray: np.ndarray, lexicon: bool = True, topk: int = 5,
                  band: bool = True):
        bw = binarize(gray)
        if band:
            y0, y1 = line_band(bw)
            if y1 - y0 >= 6 and y1 - y0 < gray.shape[0]:
                gray = gray[y0:y1]
                bw = binarize(gray)
        boxes = boxes_of(bw)
        if not boxes:
            return {'text': '', 'glyphs': [], 'conf': 0.0}

        feats, keep = [], []
        for b in boxes:
            f = features(gray[max(0, b[1]):b[3], max(0, b[0]):b[2]])
            if f is None:
                continue
            feats.append(f)
            keep.append(b)
        if not feats:
            return {'text': '', 'glyphs': [], 'conf': 0.0}

        probs = self.model.predict_proba(np.stack(feats))
        order = np.argsort(-probs, axis=1)[:, :topk]

        # разбиваем на слова по промежуткам между рамками
        widths = [b[2] - b[0] for b in keep]
        med_w = float(np.median(widths)) if widths else 1.0
        gaps = np.array([keep[i][0] - keep[i - 1][2] for i in range(1, len(keep))], np.float32)
        # порог «буква / пробел» — по самим промежуткам: у букв они мелкие, у слов
        # крупные, поэтому Отсу по промежуткам разделяет их сам, без магических чисел
        if len(gaps) >= 4 and gaps.max() > 2:
            g8 = np.clip(gaps * (255.0 / max(1.0, float(gaps.max()))), 0, 255).astype(np.uint8)
            t8, _ = cv2.threshold(g8.reshape(1, -1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            space_gap = max(0.30 * med_w, float(t8) * gaps.max() / 255.0)
        else:
            space_gap = 0.42 * med_w
        groups, cur, prev_right = [], [0], keep[0][2]
        for i in range(1, len(keep)):
            gap = keep[i][0] - prev_right
            if gap > space_gap:
                groups.append(cur)
                cur = []
            cur.append(i)
            prev_right = keep[i][2]
        groups.append(cur)

        glyphs = []
        words = []
        for g in groups:
            if lexicon and len(g) >= 2:
                word, detail = self._decode_word(probs, order, g)
            else:
                word, detail = '', []
                for i in g:
                    c = self.classes[order[i, 0]]
                    word += c
                    detail.append({'char': c, 'prob': float(probs[i, order[i, 0]]), 'box': keep[i]})
            for pos, item in enumerate(detail):
                item['box'] = keep[g[pos]] if pos < len(g) else None
            words.append(word)
            glyphs.extend(detail)

        text = ' '.join(w for w in words if w)
        if self.case == 'upper':
            text = text.upper()
        conf = float(np.mean([g['prob'] for g in glyphs])) if glyphs else 0.0
        return {'text': text, 'glyphs': glyphs, 'conf': conf}

    def _decode_word(self, probs, order, idxs, beam: int = 16):
        """Свой beam search: буквы по вероятностям + бонус словарю за слово."""
        beams = [('', 0.0, [])]
        for i in idxs:
            cand = []
            for prefix, score, detail in beams:
                for rank in range(order.shape[1]):
                    k = order[i, rank]
                    p = float(probs[i, k])
                    if p < 1e-3:
                        continue
                    ch = self.classes[k]
                    cand.append((prefix + ch, score + math.log(p + 1e-9),
                                 detail + [{'char': ch, 'prob': p, 'box': None}]))
            cand.sort(key=lambda t: -t[1])
            beams = cand[:beam]

        best, best_score = beams[0], -1e9
        for text, score, detail in beams:
            key = text.upper()
            if self.vocab and key in self.vocab:
                # бонус за известное слово: чем чаще слово, тем выше (log частоты)
                score += 2.0 + 0.6 * math.log(1 + 40000.0 / (1 + self.vocab[key]))
            elif self.vocab and len(key) >= 3:
                score -= 0.5
            if score > best_score:
                best_score, best = score, (text, score, detail)
        text, _, detail = best
        return text, [{'char': d['char'], 'prob': d['prob']} for d in detail]

    # ── чтение страницы ──────────────────────────────────────────────────────
    def read_page(self, gray: np.ndarray, lexicon: bool = True):
        """Разрез страницы на строки по горизонтальной проекции чернил."""
        bw = binarize(gray)
        rows = (bw > 0).sum(axis=1)
        thr = max(3, int(0.01 * bw.shape[1]))
        lines, start = [], None
        for y, v in enumerate(rows):
            if v > thr and start is None:
                start = y
            elif v <= thr and start is not None:
                if y - start >= 6:
                    lines.append((start, y))
                start = None
        if start is not None:
            lines.append((start, len(rows)))
        out = []
        for y0, y1 in lines:
            r = self.read_line(gray[max(0, y0 - 2):y1 + 2], lexicon=lexicon)
            if r['text']:
                out.append({'text': r['text'], 'y': [y0, y1], 'conf': r['conf'],
                            'glyphs': r['glyphs']})
        return out


def cer(ref: str, hyp: str) -> float:
    """Доля правок (Левенштейн / длина эталона), регистр и знаки не в счёт."""
    keep = lambda s: ''.join(c for c in str(s).upper() if c.isalnum())
    r, h = list(keep(ref)), list(keep(hyp))
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        cur = [i] + [0] * len(h)
        for j in range(1, len(h) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r[i - 1] != h[j - 1]))
        prev = cur
    return prev[len(h)] / len(r)
