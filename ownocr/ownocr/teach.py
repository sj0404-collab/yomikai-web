"""Учитель и ученик: курс уроков на одном листе.

Логика — как у человека-учителя:

  урок 1  «Азбука»      — 12 самых простых шрифтов, только заглавные и цифры;
  урок 2  «Полный алфавит» — те же шрифты, но все 90 знаков (строчные, знаки);
  урок 3  «Сорок шрифтов»  — добавляем начертания, пока не кончатся силы;
  урок 4  «Весь лист»      — все 104 учебных шрифта;
  урок 5  «Разбор ошибок»  — учитель смотрит, какие пары букв ученик путает, и
                             даёт ПРИЦЕЛЬНЫЕ дополнительные примеры (hard mining);
  урок 6  «Мелкий кегль и курсив» — то, на чём модель обычно ломается.

После каждого урока — проверка на 26 отложенных шрифтах, которых ученик НИКОГДА
не видел. Учитель не подглядывает в проверку при обучении: это честная оценка.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

from . import data as D
from .features import features
from .model import OwnClassifier

EASY_FONTS = [  # чистые, «книжные» начертания — с них удобно начинать
    'Advent Pro', 'Alegreya', 'Alegreya Sans', 'Alice', 'Andika', 'Arimo',
    'Arsenal', 'Bitter', 'Carlito', 'Charis SIL', 'Balsamiq Sans', 'Bellota Text',
]


def _classes(imgs, labels):
    cls = sorted(set(labels))
    idx = {c: i for i, c in enumerate(cls)}
    y = np.array([idx[c] for c in labels], np.int32)
    return cls, y


def build_features(imgs, labels, mode='easy', variants=2, seed=0, log=None):
    """Признаки для пачки глифов с «упражнениями» (аугментация)."""
    rng = np.random.default_rng(seed)
    X, Y = [], []
    for v in range(variants):
        for img, lab in zip(imgs, labels):
            g = img if v == 0 else D.augment(img, rng, mode)
            f = features(g)
            if f is None:          # пустой кроп — не буква, пропускаем вместе с подписью
                continue
            X.append(f)
            Y.append(lab)
        if log and variants > 1:
            log(f'      упражнение {v + 1}/{variants}: примеров {len(X)}')
    return np.stack(X), np.array(Y)


def top_confusions(y_true, y_pred, cls, k=6):
    from collections import Counter
    c = Counter((cls[a], cls[b]) for a, b in zip(y_true, y_pred) if a != b)
    return c.most_common(k)


class Teacher:
    def __init__(self, sheet_png: str, manifest: str, model_path: str, workdir: str,
                 log_path: str | None = None, case: str = 'upper'):
        self.imgs, self.labels, self.fonts, self.holdout, sheet = D.load_sheet(sheet_png, manifest)
        self.meta = sheet['meta']
        self.case = case
        if case == 'upper':
            # «а» и «А» — один класс: модель нормирует размер, поэтому регистр ей
            # физически не виден, и половина ошибок была именно «э»/«Э», «д»/«Д».
            # Манга набрана капсом, так что это не потеря, а меньше путаницы.
            self.labels = [l.upper() for l in self.labels]
        self.cls, self.y = _classes(self.imgs, self.labels)
        self.font_arr = np.array(self.fonts)
        self.model_path = model_path
        self.workdir = workdir
        self.log_lines = []
        self.log_path = log_path or os.path.join(workdir, 'teacher-log.txt')
        self.history = []          # для графика: (урок, val_acc)
        self.model = None
        self.val_cache = None
        self.trained_classes = set()

    # ── журнал ───────────────────────────────────────────────────────────────
    def say(self, text: str = ''):
        print(text, flush=True)
        self.log_lines.append(text)
        with open(self.log_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.log_lines) + '\n')

    # ── проверка на отложенных шрифтах ───────────────────────────────────────
    def validation(self, mode='clean', variants=1, seed=999, only_trained=True):
        if self.val_cache is None:
            m = self.holdout
            imgs = [i for i, h in zip(self.imgs, m) if h]
            labs = [l for l, h in zip(self.labels, m) if h]
            fonts = self.font_arr[m]
            X, keep = build_features(imgs, labs, mode='easy', variants=1)
            good = [i for i in imgs if features(i) is not None]
            self.val_cache = {'imgs': good, 'labs': list(keep), 'fonts': fonts, 'X': X}
        if mode == 'clean':
            X = self.val_cache['X']
            labs = self.val_cache['labs']
        else:
            rng = np.random.default_rng(seed)
            imgs = [D.augment(i, rng, mode) for i in self.val_cache['imgs']]
            feats = [features(i) for i in imgs]
            keep = [l for l, f in zip(self.val_cache['labs'], feats) if f is not None]
            X = np.stack([f for f in feats if f is not None])
            labs = keep
        y = np.array([self.cls.index(l) for l in labs], np.int32)
        pred = self.model.predict_proba(X).argmax(axis=1)
        if only_trained and self.trained_classes:
            keep = np.array([l in self.trained_classes for l in labs])
            if keep.sum() == 0:
                return 0.0, y, pred, labs
            acc = float((pred[keep] == y[keep]).mean())
            return acc, y[keep], pred[keep], [l for l, k in zip(labs, keep) if k]
        acc = float((pred == y).mean())
        return acc, y, pred, labs

    def report_val(self, acc, y, pred, title='проверка'):
        self.say(f'   {title} на отложенных шрифтах (26, не учились): {100 * acc:.1f} %')
        conf = top_confusions(y, pred, self.cls, k=6)
        if conf:
            pairs = ' · '.join(f'«{a}»/«{b}» ×{n}' for (a, b), n in conf)
            self.say(f'   учитель: худшие пары — {pairs}')

    # ── уроки ────────────────────────────────────────────────────────────────
    def _train(self, mask, mode, variants, epochs, lr, seed, title, weight=None, extra=None):
        imgs = [i for i, m in zip(self.imgs, mask) if m]
        labs = [l for l, m in zip(self.labels, mask) if m]
        if extra:
            imgs += extra[0]
            labs += extra[1]
        self.say(f'\n── УРОК «{title}» · глифов в листе {len(imgs)} · '
                 f'упражнений {variants} · эпох {epochs}')
        t = time.time()
        X, Y = build_features(imgs, labs, mode=mode, variants=variants, seed=seed,
                              log=self.say)
        yv = np.array([self.cls.index(l) for l in Y], np.int32)
        if self.model is None:
            self.model = OwnClassifier(X.shape[1], len(self.cls), hidden=192, seed=seed)
        w = weight(Y) if weight else None
        batch = int(max(32, min(256, len(yv) // 16)))
        self.say(f'   батч {batch} · шагов за эпоху {max(1, len(yv) // batch)}')
        self.model.fit(X, yv, epochs=epochs, batch=batch, lr=lr, seed=seed,
                       log=self.say, sample_weight=w)
        self.trained_classes |= set(Y)
        self.say(f'   обучение: {time.time() - t:.1f} с · примеров {len(yv)} · '
                 f'классов в работе {len(self.trained_classes)}')
        acc, y, pred, _ = self.validation()
        self.report_val(acc, y, pred)
        self.history.append({'lesson': title, 'val_acc': acc, 'n': len(yv)})
        self.model.save(self.model_path)
        json.dump({'classes': self.cls, 'case': self.case, 'dim': self.model.d_in,
                   'hidden': self.model.hidden, 'meta': self.meta},
                  open(self.model_path + '.json', 'w'), ensure_ascii=False)
        return acc

    def run(self, lessons=None):
        self.say('═' * 78)
        self.say(f'ЛИСТ: {self.meta["fonts"]} шрифтов, {self.meta["glyphs"]} глифов, '
                 f'{len(self.cls)} классов, размер {self.meta["size"][0]}×{self.meta["size"][1]}')
        self.say(f'УЧЕБНЫХ ШРИФТОВ: {self.meta["fonts"] - self.meta["holdout_fonts"]} · '
                 f'ОТЛОЖЕНО: {self.meta["holdout_fonts"]}')
        self.say('═' * 78)

        fonts_train = sorted(set(self.font_arr[~self.holdout]))
        easy = set(EASY_FONTS) & set(fonts_train)
        easy_mask = np.isin(self.font_arr, list(easy))
        upper_mask = np.isin(self.labels, list('АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ0123456789'))
        f40 = set(fonts_train[:40])
        f40_mask = np.isin(self.font_arr, list(f40))
        all_train = ~self.holdout

        steps = lessons or [1, 2, 3, 4, 5, 6]
        if 1 in steps:
            self._train(easy_mask & upper_mask, 'easy', 2, 5, 2e-3, 1, 'Азбука')
        if 2 in steps:
            self._train(easy_mask, 'easy', 2, 6, 1.5e-3, 2, 'Полный алфавит')
        if 3 in steps:
            self._train(f40_mask, 'easy', 2, 6, 1.2e-3, 3, 'Сорок шрифтов')
        if 4 in steps:
            self._train(all_train, 'easy', 2, 8, 1e-3, 4, 'Весь лист')
        if 5 in steps:
            acc, y, pred, _ = self.validation()
            conf = top_confusions(y, pred, self.cls, k=8)
            bad = set()
            for (a, b), n in conf:
                if n >= 4:
                    bad.update([a, b])
            self.say(f'\n   диагностика: {len(bad)} классов в худших парах — '
                     + ' '.join(sorted(bad)))
            sel = np.isin(self.labels, list(bad)) & all_train
            extra_imgs = [i for i, m in zip(self.imgs, sel) if m]
            extra_labs = [l for l, m in zip(self.labels, sel) if m]
            self._train(all_train, 'hard', 2, 6, 8e-4, 5,
                        'Разбор ошибок', weight=lambda Y: np.where(np.isin(Y, list(bad)), 2.5, 1.0),
                        extra=(extra_imgs, extra_labs))
        if 6 in steps:
            self._train(all_train, 'small' if False else 'italic', 2, 5, 6e-4, 6,
                        'Мелкий кегль и курсив')
            # и отдельно честная проверка на трудном варианте
            acc, y, pred, _ = self.validation(mode='small')
            self.report_val(acc, y, pred, title='проверка на МЕЛКОМ кегле')
            self.history.append({'lesson': 'мелкий кегль (проверка)', 'val_acc': acc, 'n': 0})

        self.say('\n' + '═' * 78)
        best = max(self.history, key=lambda h: h['val_acc'])
        self.say(f'ИТОГ: лучший урок «{best["lesson"]}» — {100 * best["val_acc"]:.1f} % '
                 f'на отложенных шрифтах')
        json.dump(self.history, open(os.path.join(self.workdir, 'history.json'), 'w'),
                  ensure_ascii=False, indent=1)
        self.say(f'модель: {self.model_path} · журнал: {self.log_path}')
        return self.model
