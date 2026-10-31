#!/usr/bin/env python3
"""Коллаборация: детектор приложения + СВОЙ распознаватель на целой странице.

    python3 scripts/10_pair_page.py --page ../koma-lab/dense-a.jpg \
        --det /home/user/koma_models/koma_det.onnx --out out/pair-dense-a.png

Что происходит:

1. детектор находит на странице текст (карта вероятностей → компоненты → боксы);
2. каждый бокс режется на строки по проекции чернил (логика приложения);
3. **каждую строку читает свой ученик** (`ownocr.model`, прошедший курс и урок 7);
4. строки собираются в реплики и выстраиваются в порядке чтения манги
   (справа налево, сверху вниз) — это тоже логика приложения, а не наша.

Для сравнения тем же кодом читает и CTC-распознаватель приложения
(`koma_rec.onnx`), если он есть: один и тот же детектор, одни и те же строки,
разница только в том, кто читает буквы.
"""
import argparse
import json
import os
import sys
import time

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr.engine import OwnOCR                     # noqa: E402
from ownocr.page_det import (PageDetector, Region, bubbles_of,  # noqa: E402
                             split_panels, text_lines)


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


VOCAB = set(w.strip().upper() for w in
             open(os.path.join(ROOT, 'ownocr', 'vocab-ru.txt'), encoding='utf-8'))


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

    def __init__(self, model_dir: str, scales=(2.0, 3.0), sure: float = 0.8):
        self.ocr = OwnOCR(model_dir)
        self.scales, self.sure = tuple(scales), float(sure)

    def read(self, gray: np.ndarray) -> tuple[str, float]:
        import cv2

        g = np.asarray(gray)
        if g.ndim == 3:
            g = cv2.cvtColor(g, cv2.COLOR_RGB2GRAY)
        best: tuple[str, float] = ('', -1.0)
        for i, k in enumerate(self.scales):
            big = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC) if k > 1.01 else g
            r = self.ocr.read_line(big, lexicon=True)
            conf = float(r.get('conf', 0.0))
            if conf > best[1]:
                best = (r['text'], conf)
            if i == 0 and conf >= self.sure:
                break
        return best


def read_page(det: PageDetector, reader, rgb: np.ndarray, minconf: float = 0.8):
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
                text, score = reader.read(np.array(Image.fromarray(crop).convert('L')))
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
            'lines': n_lines, 'seconds': time.time() - t0}


def draw(page_path: str, out_png: str, boxes, lines):
    """Страница + рамки детектора (серые) + собранные реплики (цветные)."""
    import cv2

    img = cv2.imread(page_path)
    H, W = img.shape[:2]
    for (x1, y1, x2, y2) in boxes:
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (150, 150, 150), 1)
    for i, line in enumerate(lines, 1):
        p1 = (int(line.left * W), int(line.top * H))
        p2 = (int(line.right * W), int(line.bottom * H))
        cv2.rectangle(img, p1, p2, (60, 200, 90), 2)
        cv2.putText(img, str(i), (p1[0] + 3, max(14, p1[1] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (60, 200, 90), 2)
    cv2.imwrite(out_png, img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--page', default=os.path.join(ROOT, '..', 'koma-lab', 'dense-a.jpg'))
    ap.add_argument('--det', default='/home/user/koma_models/koma_det.onnx')
    ap.add_argument('--ctc', default='/home/user/koma_models/koma_rec.onnx')
    ap.add_argument('--dict', default='/home/user/koma_models/koma_dict.txt')
    ap.add_argument('--model', default=os.path.join(ROOT, 'model'))
    ap.add_argument('--expected', default='')
    ap.add_argument('--out', default=os.path.join(ROOT, 'out', 'pair-page.png'))
    ap.add_argument('--json', default='')
    ap.add_argument('--minconf', type=float, default=0.8,
                    help='порог уверенности своего ученика (CTC проверяется своим, 0.25)')
    a = ap.parse_args()

    rgb = np.array(Image.open(a.page).convert('RGB'))
    det = PageDetector(a.det)
    mine = read_page(det, OwnReader(a.model), rgb, minconf=a.minconf)
    res = {'page': os.path.basename(a.page), 'size': list(rgb.shape[:2]),
           'own': {'replies': [l.text for l in mine['replies']],
                   'dropped': mine['dropped'], 'boxes': mine['boxes'],
                   'lines': mine['lines'], 'seconds': round(mine['seconds'], 2)}}

    print(f'страница {os.path.basename(a.page)} {rgb.shape[1]}×{rgb.shape[0]}')
    print(f'детектор: {mine["boxes"]} боксов → {mine["lines"]} строк · '
          f'свой ученик прочитал за {mine["seconds"]:.1f} с')

    if os.path.exists(a.ctc) and os.path.exists(a.dict):
        ctc = read_page(det, CtcReader(a.ctc, a.dict), rgb, minconf=0.25)
        res['ctc'] = {'replies': [l.text for l in ctc['replies']],
                      'dropped': ctc['dropped'], 'boxes': ctc['boxes'],
                      'lines': ctc['lines'], 'seconds': round(ctc['seconds'], 2)}

    exp = []
    if a.expected and os.path.exists(a.expected):
        exp = json.load(open(a.expected, encoding='utf-8'))
    if exp:
        print(f'\nэталон: {len(exp)} реплик')
        for name in ('own', 'ctc'):
            if name not in res:
                continue
            got = res[name]['replies']
            n = min(len(exp), len(got))
            cers = [cer(clean(exp[i]), clean(got[i])) for i in range(n)]
            cers += [1.0] * abs(len(exp) - len(got))
            exact = sum(1 for i in range(n) if clean(exp[i]) == clean(got[i]))
            res[name].update({'cer': round(float(np.mean(cers)), 4),
                              'exact': exact, 'n_expected': len(exp), 'n_got': len(got)})
            print(f'  {name:4s}: реплик {len(got)} из {len(exp)} · '
                  f'CER {100 * np.mean(cers):.1f} % · целиком верных {exact}/{len(exp)}')

    print('\nчто прочитал свой ученик (в порядке чтения):')
    for i, line in enumerate(mine['replies'], 1):
        print(f'  {i:2d}. {line.text}')
        res['own'].setdefault('order', []).append(line.text)

    if a.json:
        os.makedirs(os.path.dirname(a.json) or '.', exist_ok=True)
        json.dump(res, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('\njson:', a.json)

    boxes = det.detect_page(rgb)
    os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
    draw(a.page, a.out, boxes, mine['replies'])
    print('картинка:', a.out)


if __name__ == '__main__':
    main()
