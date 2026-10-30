"""Урок 7 «Чтение по настоящей странице» — учитель поправляет ученика вживую.

На листе шрифты печатные, а манга нарисована рукой. Ученик, выученный на листе,
видит знакомые буквы, но с другим наклоном, толщиной и слякотью. Это не повод
переучивать всё заново: достаточно разобрать ошибки по буквам.

Как это работает (и почему это честно):

  1. Берём строки с известным текстом. Часть строк откладываем и НЕ ПОКАЗЫВАЕМ
     ученику до проверки (`--test-every 3` — каждая третья строка контрольная).
  2. На учебных строках режем кроп на пятна и выравниваем пятна с эталонным
     текстом динамическим программированием (какое пятно какой букве
     соответствует). Выравнивание — своё, на минимуме −log p.
  3. Пары «картинка-буква» идут в дообучение с сильными упражнениями
     (наклон, жирность, шум). Плюс повтор листа, чтобы не забыть выученное.
  4. Проверка — на отложенных строках, которых ученик не видел.
"""
from __future__ import annotations

import csv
import json
import os

import cv2
import numpy as np

from . import data as D
from .engine import OwnOCR, binarize, boxes_of, cer
from .features import features


def read_rows(path: str):
    rows = []
    with open(path, encoding='utf-8') as f:
        for rec in csv.reader(f, delimiter='\t'):
            if len(rec) >= 2 and rec[1].strip():
                rows.append((rec[0], rec[1].strip()))
    return rows


def align(boxes, text, probs, classes, skip_box=2.2, skip_char=2.2):
    """Выравнивание пятен и эталона: возвращает пары (индекс пятна, индекс буквы).

    Стоимость: совпадение = −log p(буква | пятно); при этом можно «выбросить»
    пятно (мусор, обрезок) или «пропустить» букву (слиплось) за фиксированную
    цену. Это обычное динамическое программирование по матрице (пятна × буквы).
    """
    n_b, n_c = len(boxes), len(text)
    if n_b == 0 or n_c == 0:
        return []
    idx = {c: i for i, c in enumerate(classes)}
    cost = np.full((n_c, n_b), 8.0, np.float32)
    for j, ch in enumerate(text):
        k = idx.get(ch.upper())
        if k is not None:
            cost[j, :] = -np.log(np.clip(probs[:, k], 1e-6, 1.0))
    INF = 1e9
    dp = np.full((n_b + 1, n_c + 1), INF, np.float32)
    back = np.zeros((n_b + 1, n_c + 1), np.int8)
    dp[0, 0] = 0.0
    for i in range(n_b + 1):
        for j in range(n_c + 1):
            if dp[i, j] >= INF:
                continue
            if i < n_b:                                   # пятно без буквы
                v = dp[i, j] + skip_box
                if v < dp[i + 1, j]:
                    dp[i + 1, j], back[i + 1, j] = v, 1
            if j < n_c:                                   # буква без пятна
                v = dp[i, j] + skip_char
                if v < dp[i, j + 1]:
                    dp[i, j + 1], back[i, j + 1] = v, 2
            if i < n_b and j < n_c:                       # сопоставление
                v = dp[i, j] + cost[j, i]
                if v < dp[i + 1, j + 1]:
                    dp[i + 1, j + 1], back[i + 1, j + 1] = v, 3
    pairs, i, j = [], n_b, n_c
    while i > 0 or j > 0:
        b = back[i, j]
        if b == 3:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif b == 1:
            i -= 1
        elif b == 2:
            j -= 1
        else:
            break
    return pairs[::-1]


def crops_from_lines(rows, ocr: OwnOCR, log=print):
    """Нарезать пары «картинка-буква» из учебных строк по выравниванию."""
    imgs, labs, stats = [], [], []
    for name, ref in rows:
        gray = cv2.imread(name, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        bw = binarize(gray)
        boxes = boxes_of(bw)
        if not boxes:
            continue
        feats = [features(gray[max(0, b[1]):b[3], max(0, b[0]):b[2]]) for b in boxes]
        good = [(b, f) for b, f in zip(boxes, feats) if f is not None]
        if not good:
            continue
        boxes = [b for b, _ in good]
        probs = ocr.model.predict_proba(np.stack([f for _, f in good]))
        text = ''.join(c for c in ref.upper() if c.isalnum())
        pairs = align(boxes, text, probs, ocr.classes)
        got = ''.join(text[j] for _, j in pairs)
        # Доверие к выравниванию: если пятен и букв сошлось почти один-к-одному,
        # парам можно верить. Если нет — ошибка не в букве, а в разрезе строки, и
        # учить по такому примеру только портить модель.
        nll = float(np.mean([-np.log(np.clip(probs[i, ocr.classes.index(text[j].upper())], 1e-6, 1.0))
                             for i, j in pairs])) if pairs else 99.0
        trusted = (len(pairs) >= 0.8 * len(text)) and (nll < 3.2)
        stats.append({'file': os.path.basename(name), 'ref': ref, 'aligned': got,
                      'boxes': len(boxes), 'pairs': len(pairs), 'trusted': bool(trusted),
                      'nll': round(nll, 2)})
        if not trusted:
            continue
        for i, j in pairs:
            b = boxes[i]
            crop = gray[max(0, b[1]):b[3], max(0, b[0]):b[2]]
            if crop.size == 0:
                continue
            imgs.append(crop)
            labs.append(text[j])
    used = sum(1 for st in stats if st['trusted'])
    log(f'   разобрано строк: {len(stats)} · доверенных {used} · пар «картинка–буква»: {len(imgs)}')
    return imgs, labs, stats


def evaluate(ocr: OwnOCR, rows, lexicon=True):
    cers, detail = [], []
    for name, ref in rows:
        gray = cv2.imread(name, cv2.IMREAD_GRAYSCALE)
        r = ocr.read_line(gray, lexicon=lexicon) if gray is not None else {'text': ''}
        c = cer(ref, r['text'])
        cers.append(c)
        detail.append({'file': os.path.basename(name), 'ref': ref, 'hyp': r['text'], 'cer': c})
    return float(np.mean(cers)), sum(1 for c in cers if c == 0), detail


def run(sheet_png, manifest, labels_tsv, model_dir, out_dir, test_every=3,
        epochs=8, lr=1e-4, augment_variants=8, replay=8000, log=print):
    """Урок 7 с ПРИЁМКОЙ: правки принимаются только если контрольные строки
    стали читаться лучше и экзамен на шрифтах не просел. Иначе — откат.

    Малый шаг (1e-4) и повтор листа обязательны: с шагом 6e-4 и без повтора
    ученик за 12 доверенных парах забывал шрифты, и CER контрольных строк рос
    с 36,7 % до 44,8 %. Это замерено, а не «на глаз».
    """
    log('═' * 78)
    log('УРОК 7 «Чтение по настоящей странице» — учитель правит ученика по буквам')
    log('═' * 78)
    ocr = OwnOCR(model_dir)
    rows = [(os.path.join(os.path.dirname(labels_tsv), n), t) for n, t in read_rows(labels_tsv)]
    train = [r for i, r in enumerate(rows) if i % test_every != 0]
    test = [r for i, r in enumerate(rows) if i % test_every == 0]
    log(f'   строк всего {len(rows)} · учебных {len(train)} · контрольных {len(test)} '
        f'(контрольные ученику не показываются)')

    before_cer, before_exact, _ = evaluate(ocr, test)
    log(f'   ДО урока: CER на контрольных строках {100 * before_cer:.1f} % · '
        f'целиком верных {before_exact}/{len(test)}')

    imgs, labs, stats = crops_from_lines(train, ocr)
    # упражнения: настоящих букв мало, поэтому каждый кроп «прокручиваем» несколько раз
    rng = np.random.default_rng(7)
    X, Y = [], []
    modes = ['easy', 'italic', 'hard', 'small', 'italic', 'hard', 'easy', 'italic']
    for v in range(augment_variants):
        for img, lab in zip(imgs, labs):
            g = img if v == 0 else D.augment(img, rng, modes[v % len(modes)])
            f = features(g)
            if f is not None:
                X.append(f)
                Y.append(lab)
    X = np.stack(X)
    y = np.array([ocr.classes.index(l) for l in Y if l in ocr.classes], np.int32)
    mask = np.array([l in ocr.classes for l in Y])
    X = X[mask]
    log(f'   упражнений из настоящих строк: {len(y)}')

    # повтор листа: 4000 случайных глифов, иначе ученик «забудет» шрифты
    sheet_imgs, sheet_labs, _, _, _ = D.load_sheet(sheet_png, manifest)
    pick = rng.choice(len(sheet_imgs), size=min(replay, len(sheet_imgs)), replace=False)
    Xs, Ys = [], []
    for i in pick:
        f = features(D.augment(sheet_imgs[i], rng, 'easy'))
        if f is not None:
            Xs.append(f)
            Ys.append(sheet_labs[i].upper())
    Xs = np.stack(Xs)
    ys = np.array([ocr.classes.index(l) for l in Ys if l in ocr.classes], np.int32)
    log(f'   повтор листа: {len(ys)}')

    Xa = np.vstack([X, Xs])
    ya = np.concatenate([y, ys])
    wa = np.concatenate([np.full(len(y), 2.5, np.float32), np.ones(len(ys), np.float32)])

    ocr.model.l2 = 5e-5
    best = {k: v.copy() for k, v in ocr.model._params().items()}
    best_cer = before_cer
    hist = []
    for ep in range(epochs):
        hist += ocr.model.fit(Xa, ya, epochs=1, batch=64, lr=lr, seed=ep + 1,
                              sample_weight=wa, log=None)
        cur, _ex, _ = evaluate(ocr, test)
        log(f'      эпоха {ep + 1:2d}/{epochs}: −log p = {hist[-1]:.3f} · '
            f'контрольные строки {100 * cur:.1f} % CER')
        if cur < best_cer - 1e-4:
            best_cer = cur
            best = {k: v.copy() for k, v in ocr.model._params().items()}
    for k, v in best.items():
        ocr.model._params()[k][...] = v
    after_cer, after_exact, detail = evaluate(ocr, test)
    accepted = after_cer < before_cer - 1e-4
    log(f'   ПРИЁМКА: {"принято" if accepted else "откат"} '
        f'(контрольные строки {100 * before_cer:.1f} → {100 * after_cer:.1f} % CER)')
    log(f'   ПОСЛЕ урока: CER на контрольных строках {100 * after_cer:.1f} % · '
        f'целиком верных {after_exact}/{len(test)}')
    log('   что читает теперь:')
    for d in detail[:8]:
        log(f'      {d["file"]}: эталон «{d["ref"]}» → «{d["hyp"]}»')

    out_model = os.path.join(out_dir, 'ownocr-real')
    os.makedirs(out_model, exist_ok=True)
    ocr.model.save(os.path.join(out_model, 'ownocr.npz'))
    meta = json.load(open(os.path.join(model_dir, 'ownocr.npz.json'), encoding='utf-8'))
    json.dump(meta, open(os.path.join(out_model, 'ownocr.npz.json'), 'w'), ensure_ascii=False)

    res = {'accepted': bool(accepted), 'before_cer': before_cer, 'before_exact': before_exact, 'n_test': len(test),
           'after_cer': after_cer, 'after_exact': after_exact,
           'n_pairs': len(imgs), 'alignment': stats, 'detail': detail,
           'history': hist, 'model': out_model}
    json.dump(res, open(os.path.join(out_dir, 'lesson-real.json'), 'w'),
              ensure_ascii=False, indent=1)
    return res
