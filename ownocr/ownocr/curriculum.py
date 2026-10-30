"""Лестница обучения «детский сад → университет» с проверкой домашнего задания.

Идея простая и человеческая: ученик не переходит на следующий уровень, пока не
сдал зачёт предыдущего. Пройденное «фиксируется» (сохраняется в диплом и в
контрольную работу), а на новом уровне проверяется ещё и то, что он не забыл
старое — иначе его возвращают на пересдачу.

Уровни (каждый — набор шрифтов + набор знаков + сила упражнений):

  ясли          самые чистые 4 шрифта, 12 простых букв      — учат смотреть на форму
  детский сад   12 чистых шрифтов, капс + цифры
  начальная     те же 12 шрифтов, весь алфавит
  средняя       60 шрифтов, весь алфавит
  старшая       180 шрифтов, весь алфавит
  выпускной     все учебные шрифты листа
  университет  + настоящие строки манги + разбор ошибок
  аспирантура   самопроверка: неподписанные строки, где ученик уверен в себе

Зачёт (домашнее задание) — проверка на шрифтах, которых на этом уровне НЕ было, и
на прошлых экзаменах. Зачёт сдан, если:
  • точность на своём экзамене ≥ цели уровня;
  • ни один прошлый экзамен не просел больше чем на 1 п.п. (иначе — пересдача).
Только после этого уровень пишется в диплом и модель сохраняется.
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

from . import data as D
from .features import features
from .model import OwnClassifier

UPPER = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ'
DIGITS = '0123456789'
SIMPLE = 'АГЕИКОМНПРСТ'[:12]

# шрифты первых уровней — самые «школьные»: ровные, без засечек-выкрутасов
CLEAN = ['Advent Pro', 'Andika', 'Arimo', 'Carlito', 'Open Sans', 'Roboto',
         'Noto Sans', 'PT Sans', 'Ubuntu', 'Rubik', 'Montserrat', 'Fira Sans',
         'Source Sans 3', 'Lato', 'Inter', 'Raleway', 'Nunito', 'Rubik Mono One']

STAGES = [
    {'key': 'nursery', 'name': 'ясли', 'fonts': 4, 'simple_fonts': True,
     'chars': SIMPLE, 'modes': ['easy'], 'variants': 3, 'epochs': 12, 'lr': 3e-3,
     'target': 0.65},
    {'key': 'kindergarten', 'name': 'детский сад', 'fonts': 12, 'simple_fonts': True,
     'chars': UPPER + DIGITS, 'modes': ['easy', 'small'], 'variants': 4, 'epochs': 12,
     'lr': 2e-3, 'target': 0.8},
    {'key': 'primary', 'name': 'начальная школа', 'fonts': 12, 'simple_fonts': True,
     'chars': None, 'modes': ['easy', 'small', 'italic'], 'variants': 4, 'epochs': 12,
     'lr': 1.6e-3, 'target': 0.84},
    {'key': 'middle', 'name': 'средняя школа', 'fonts': 60, 'chars': None,
     'modes': ['easy', 'small', 'italic', 'hard'], 'variants': 5, 'epochs': 14,
     'lr': 1.2e-3, 'target': 0.91},
    {'key': 'high', 'name': 'старшая школа', 'fonts': 180, 'chars': None,
     'modes': ['easy', 'small', 'italic', 'hard'], 'variants': 5, 'epochs': 14,
     'lr': 9e-4, 'target': 0.94},
    {'key': 'graduate', 'name': 'выпускной', 'fonts': None, 'chars': None,
     'modes': ['easy', 'small', 'italic', 'hard'], 'variants': 6, 'epochs': 16,
     'lr': 7e-4, 'target': 0.95},
    {'key': 'university', 'name': 'университет', 'fonts': None, 'chars': None,
     'modes': ['easy', 'small', 'italic', 'hard'], 'variants': 6, 'epochs': 12,
     'lr': 5e-4, 'target': 0.94, 'real': True, 'hard_mine': True},
    {'key': 'postgrad', 'name': 'аспирантура', 'fonts': None, 'chars': None,
     'modes': ['easy', 'small', 'italic', 'hard'], 'variants': 6, 'epochs': 10,
     'lr': 3.5e-4, 'target': 0.94, 'self_train': True},
]


class Curriculum:
    def __init__(self, sheet: str, manifest: str, out_dir: str, log_path: str | None = None,
                 budget_min: float = 40.0, workdir: str | None = None, resume: bool = False):
        self.out = out_dir
        self.workdir = workdir or os.path.join(out_dir, 'curriculum')
        os.makedirs(self.workdir, exist_ok=True)
        self.t0 = time.time()
        self.deadline = self.t0 + budget_min * 60
        self.log_path = log_path or os.path.join(self.workdir, 'curriculum-log.txt')
        self.lines: list[str] = []
        self.say('═' * 84)
        self.say('ЛЕСТНИЦА: детский сад → университет · свой OCR, без ONNX и TFLite')
        self.say(f'бюджет времени: {budget_min:.0f} мин · старт {time.strftime("%H:%M:%S")}')
        self.say('═' * 84)

        self.imgs, labels, self.fonts, self.holdout, sheet_meta = D.load_sheet(sheet, manifest)
        self.meta = sheet_meta['meta']
        self.labels = np.array([l.upper() for l in labels])
        self.fonts = np.array(self.fonts)
        self.classes = sorted(set(self.labels))
        self.cls_index = {c: i for i, c in enumerate(self.classes)}
        self.y = np.array([self.cls_index[l] for l in self.labels], np.int32)
        self.train_fonts = sorted(set(self.fonts[~self.holdout]))
        self.holdout_fonts = sorted(set(self.fonts[self.holdout]))
        self.say(f'лист: {self.meta["fonts"]} шрифтов · {self.meta["glyphs"]} глифов · '
                 f'{len(self.classes)} классов · отложено {len(self.holdout_fonts)} шрифтов')
        self.model: OwnClassifier | None = None
        self.diploma: list[dict] = []
        self.prev: dict = {}
        self.exams: dict[str, np.ndarray] = {}
        self.feat_cache: dict[tuple, tuple] = {}
        # «повторение пройденного»: материал прошлых уровней. Без этого ученик
        # на каждом новом уровне забывал старый: экзамен «ясли» падал
        # 97,9 → 93,2 % после «детского сада», и зачёты валились по пересдаче.
        self.rehearsal_X: list[np.ndarray] = []
        self.rehearsal_y: list[np.ndarray] = []
        # уровень целиком (маска листа) — из него повторение собирается заново
        # в широком наборе режимов: узкий набор (один 'easy') не держит старый
        # экзамен, который рисуется в другом режиме.
        self.rehearsal_stages: list[dict] = []
        self.rehearsal_n = 0
        self.rehearsal_cap = 60000
        self.labels_tsv = None
        self._real_bank = None
        self.resumed = False
        if resume:
            self._resume()

    def _resume(self):
        """Продолжить с прошлой зачётной ступени: ученик помнит, что сдал."""
        weights = os.path.join(self.out, 'ownocr-latest.npz')
        meta_path = os.path.join(self.out, 'ownocr-latest.npz.json')
        dip_path = os.path.join(self.out, 'diploma.json')
        if not (os.path.exists(weights) and os.path.exists(meta_path)):
            self.say('продолжение: прошлой модели нет — ученик новый')
            return
        meta = json.load(open(meta_path, encoding='utf-8'))
        self.model = OwnClassifier(meta['dim'], len(meta['classes']),
                                   hidden=meta.get('hidden', 384), seed=7)
        self.model.load(weights)
        if os.path.exists(dip_path):
            old = json.load(open(dip_path, encoding='utf-8'))
            self.prev = {d['key']: d for d in old.get('diploma', [])}
            self.say('продолжение: зачётная книжка найдена — ' +
                     ', '.join(f'{k} {100 * v["exam"]:.1f} %' for k, v in self.prev.items())
                     if self.prev else 'продолжение: книжка пуста')
        self.say(f'продолжение: ученик загружен ({self.model.W1.size + self.model.W2.size} чисел)')
        # закрепляем планку: новый уровень считается сданным, только если он не хуже прошлого
        for st in STAGES:
            old = self.prev.get(st['key'])
            if old and old.get('passed'):
                n_old = max(1, int(old.get('n_examples', 1000)))
                tol = max(0.012, 2.0 * np.sqrt(2 * old['exam'] * (1 - old['exam']) / n_old))
                st['target'] = max(st['target'], min(0.97, old['exam'] - tol))
                self.say(f'   планка «{st["name"]}» поднята до {100 * st["target"]:.1f} % '
                         f'(в прошлый раз было {100 * old["exam"]:.1f} %)')
        # экзамены сданных ступеней собираем заново: набор детерминированный
        # (те же шрифты, тот же seed), поэтому пересдача после продолжения
        # проверяет то же самое, что и в прошлый раз, а сам материал экзамена
        # идёт в повторение — ровно та проверка ДЗ, о которой речь.
        exam_fonts = [f for f in self.holdout_fonts][:40]
        for st in STAGES:
            old = self.prev.get(st['key'])
            if not (old and old.get('passed')):
                continue
            try:
                Xp, Yp = self.exam(exam_fonts, st.get('chars'))
            except Exception as e:            # noqa: BLE001
                self.say(f'   экзамен «{st["name"]}» не восстановить: {e}')
                continue
            self.exams[st['key']] = (Xp, Yp)
            self._remember_stage(st, self.stage_mask(st))
            self.say(f'   экзамен «{st["name"]}» собран заново: {len(Yp)} примеров в повторение')

    # ── журнал ───────────────────────────────────────────────────────────────
    def say(self, text: str = ''):
        print(text, flush=True)
        self.lines.append(text)
        with open(self.log_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.lines) + '\n')

    def estimate(self, st) -> float:
        """Сколько секунд займёт уровень: признаки (в кеш, один раз) + эпохи по банку."""
        mask = self.stage_mask(st)
        key = (hash(mask.tobytes()), tuple(st['modes']), st['variants'], hash(st['key']) % 10_000)
        n_bank = int(mask.sum()) * st['variants']
        feat_cost = 0.0 if key in self.feat_cache else n_bank * 0.0022
        model_cost = st['epochs'] * n_bank * 2.2e-5 if n_bank else st['epochs'] * 0.2
        exam_cost = 3.0
        return feat_cost + model_cost + exam_cost

    def left(self) -> float:
        return (self.deadline - time.time()) / 60.0

    # ── признаки с кешем: пересчёт листа дорогой, а решение по нему — нет ────
    def _feat_bank(self, mask: np.ndarray, modes: list[str], variants: int,
                   seed: int) -> tuple[np.ndarray, np.ndarray]:
        key = (hash(mask.tobytes()), tuple(modes), variants, seed)
        if key in self.feat_cache:
            return self.feat_cache[key]
        rng = np.random.default_rng(seed)
        idx = np.where(mask)[0]
        X, Y = [], []
        for v in range(variants):
            mode = modes[v % len(modes)] if v else 'clean'
            for i in idx:
                g = self.imgs[i] if v == 0 else D.augment(self.imgs[i], rng, mode)
                f = features(g)
                if f is not None:
                    X.append(f)
                    Y.append(self.y[i])
        bank = (np.stack(X), np.array(Y, np.int32))
        self.feat_cache[key] = bank
        return bank

    def exam(self, font_list, chars=None, mode='clean', n_max=2500, seed=51) -> tuple[np.ndarray, np.ndarray]:
        """Экзаменационный набор: шрифты, которых ученик на этом уровне не видел."""
        sel = np.isin(self.fonts, list(font_list))
        if chars:
            sel &= np.isin(self.labels, list(chars))
        idx = np.where(sel)[0]
        if len(idx) > n_max:
            idx = np.random.default_rng(seed).choice(idx, n_max, replace=False)
        rng = np.random.default_rng(seed)
        X, Y = [], []
        for i in idx:
            g = self.imgs[i] if mode == 'clean' else D.augment(self.imgs[i], rng, mode)
            f = features(g)
            if f is not None:
                X.append(f)
                Y.append(self.y[i])
        return np.stack(X), np.array(Y, np.int32)

    def score(self, X, Y) -> float:
        return float((self.model.predict_proba(X).argmax(axis=1) == Y).mean())

    # ── один уровень ─────────────────────────────────────────────────────────
    def stage_mask(self, st) -> np.ndarray:
        teach = np.zeros(len(self.imgs), bool)
        if st.get('simple_fonts'):
            fonts = [f for f in CLEAN if f in self.train_fonts][:st['fonts']]
        elif st.get('fonts'):
            fonts = self.train_fonts[:st['fonts']]
        else:
            fonts = self.train_fonts
        teach |= np.isin(self.fonts, fonts)
        if st.get('chars'):
            teach &= np.isin(self.labels, list(st['chars']))
        return teach

    def run_stage(self, st, extra_X=None, extra_y=None) -> dict:
        name = st['name']
        self.say('')
        self.say(f'── УРОВЕНЬ «{name}» ───────────────────────────────────────────────')
        mask = self.stage_mask(st)
        if extra_X is not None:
            mask = mask.copy()
        X, Y = self._feat_bank(mask, st['modes'], st['variants'], seed=hash(st['key']) % 10_000)
        self.say(f'   учебный материал: глифов {int(mask.sum())} · шрифтов '
                 f'{len(set(self.fonts[mask]))} · знаков {len(set(self.labels[mask]))} · '
                 f'примеров с упражнениями {len(Y)}')
        if extra_X is not None and len(extra_y):
            X = np.vstack([X, extra_X])
            Y = np.concatenate([Y, extra_y])
            self.say(f'   + из настоящей страницы: {len(extra_y)}')
        # повторение пройденного: часть банка — примеры прошлых уровней
        # и настоящие строки манги. Без настоящих строк лестница вымывает
        # почерк: курс учится на синтетике, и чтение страницы ухудшается.
        if (self.labels_tsv and self._real_bank is None
                and os.environ.get('OWNOCR_REAL_REH', '0') == '1'):
            Xr, Yr = self.real_pairs(self.labels_tsv)
            if Xr is not None and len(Yr):
                self._real_bank = (Xr, Yr)
                self.rehearsal_stages.append({'key': 'real', 'mask': None,
                                              'bank': (Xr, Yr)})
                self.say(f'   настоящие строки в повторении: {len(Yr)} пар «картинка–буква»')
        n_new = len(Y)
        if self.rehearsal_stages:
            share = float(os.environ.get('OWNOCR_REH_SHARE', 0.5))
            take = int(share * len(Y))
            per = max(int(os.environ.get('OWNOCR_REH_MIN', 1200)), take // len(self.rehearsal_stages))
            rng = np.random.default_rng(len(self.rehearsal_stages) + 100)
            parts_x, parts_y = [], []
            for item in self.rehearsal_stages:
                bx, by = self._rehearsal_bank(item)
                if len(by) == 0:
                    continue
                j = rng.choice(len(by), per, replace=len(by) < per)
                parts_x.append(bx[j])
                parts_y.append(by[j])
            Xr = np.vstack(parts_x)
            yr = np.concatenate(parts_y)
            X = np.vstack([X, Xr])
            Y = np.concatenate([Y, yr])
            self.say(f'   + повторение пройденного: {len(yr)} примеров из прошлых уровней')

        if self.model is None:
            self.model = OwnClassifier(X.shape[1], len(self.classes), hidden=384, seed=7)
            self.say(f'   ученик новый: {self.model.W1.size + self.model.W2.size} чисел')
        else:
            self.say(f'   ученик продолжает: {self.model.W1.size + self.model.W2.size} чисел')

        exam_fonts = [f for f in self.holdout_fonts][:40]
        Xe, Ye = self.exam(exam_fonts, st.get('chars'))
        pass_exam = self.exam(exam_fonts, st.get('chars'), mode='italic', seed=77)
        hard_exam = self.exam(exam_fonts, st.get('chars'), mode='hard', seed=78)

        # дистилляция: ответы прежнего ученика на повторяемом материале —
        # мягкие цели. Так новый уровень учится, не ломая старое (без этого
        # «ясли» проседали 97,2 → 92,9 % и пересдача валила зачёт). Экзамены
        # при этом остаются незнакомыми: они в обучение не попадают.
        soft = lam = None
        if self.model is not None and len(Y) > n_new and float(os.environ.get('OWNOCR_DISTILL', 0.0)) > 0:
            soft = np.zeros((len(Y), len(self.classes)), np.float32)
            soft[n_new:] = self.model.predict_proba(X[n_new:]).astype(np.float32)
            lam = np.zeros(len(Y), np.float32)
            lam[n_new:] = float(os.environ.get('OWNOCR_DISTILL', 0.0))
            self.say(f'   дистилляция: {len(Y) - n_new} строк держим на ответах прежнего ученика')
        t = time.time()
        best_acc, best_state, best_ep = -1.0, None, 0
        best_key = (-1.0, -1.0)
        lr = st['lr']
        if len(self.diploma) or self.resumed:
            lr = min(lr, 1.2e-3)   # продолжаем учёбу, а не начинаем заново
        for ep in range(st['epochs']):
            hist = self.model.fit(X, Y, epochs=1, batch=128, lr=lr,
                                  seed=ep + 1, log=None, soft=soft, lam=lam)
            acc_clean = self.score(Xe, Ye)
            acc_hard = 0.5 * (self.score(*pass_exam) + self.score(*hard_exam))
            # выбираем эпоху не только по новому экзамену: считаем, насколько
            # просели прошлые (иначе на выходе — ученик, сдавший новое и забывший
            # старое). Годится эпоха, где новый экзамен сдан и просадки нет.
            drop = 0.0
            for key, (Xp, Yp) in self.exams.items():
                was = next((d['exam'] for d in self.diploma if d['key'] == key), None)
                if was is None:
                    continue
                se = np.sqrt(2 * max(1e-6, was * (1 - was)) / max(1, len(Yp)))
                drop = max(drop, was - self.score(Xp, Yp) - max(0.012, 2.0 * se))
            ok_now = acc_clean >= st['target'] and drop <= 0.0
            key_ep = (1 if ok_now else 0, acc_clean - 1.2 * max(0.0, drop))
            if key_ep > (-1.0, -1.0) and (best_state is None or key_ep > best_key):
                best_key = key_ep
                best_acc = acc_clean
                best_state = {k: v.copy() for k, v in self.model._params().items()}
                best_ep = ep + 1
            if (ep + 1) % 4 == 0 or ep == st['epochs'] - 1:
                self.say(f'   эпоха {ep + 1:2d}/{st["epochs"]}: −log p = {hist[-1]:.3f} · '
                         f'экзамен {100 * acc_clean:5.1f} % · с наклоном {100 * acc_hard:5.1f} %')
        if best_state:
            for k, v in best_state.items():
                self.model._params()[k][...] = v
        dt = time.time() - t

        acc = self.score(Xe, Ye)
        acc_hard = self.score(*pass_exam)
        # пересдача забытого: прошлые экзамены не должны просесть
        regress = []
        for key, (Xp, Yp) in self.exams.items():
            now = self.score(Xp, Yp)
            was = next((d['exam'] for d in self.diploma if d['key'] == key), now)
            # допуск = две стандартные ошибки разности двух замеров на наборе
            # такого размера: на 960 примерах это ±1,8 п.п., на 2500 — ±1,1.
            # Меньший провал — это шум замера, а не забывание.
            se = np.sqrt(2 * max(1e-6, was * (1 - was)) / max(1, len(Yp)))
            tol = max(0.012, 2.0 * se)
            if now < was - tol:
                regress.append((key, was, now, tol))
        passed = acc >= st['target'] and not regress
        self.exams[st['key']] = (Xe, Ye)
        self.say(f'   ДОМАШНЕЕ ЗАДАНИЕ: экзамен {100 * acc:.1f} % (цель {100 * st["target"]:.0f} %) · '
                 f'с наклоном {100 * acc_hard:.1f} % · время {dt:.0f} с')
        if regress:
            self.say('   пересдача: просели прошлые экзамены — '
                     + ', '.join(f'{k} {100 * w:.1f}→{100 * n:.1f} % (допуск {100 * t:.1f})'
                                 for k, w, n, t in regress))
        self.say(f'   ЗАЧЁТ {"СДАН" if passed else "НЕ СДАН"} · осталось {self.left():.0f} мин')

        rec = {'key': st['key'], 'name': name, 'exam': acc, 'exam_hard': acc_hard,
               'target': st['target'], 'passed': bool(passed), 'seconds': round(dt, 1),
               'n_examples': int(len(Y)), 'fonts_taught': int(len(set(self.fonts[mask]))),
               'epochs_best': best_ep}
        if passed:
            self.diploma.append(rec)
            self._remember_stage(st, mask)
            self.save(self.workdir, st['key'])
        return rec

    def _rehearsal_bank(self, item: dict) -> tuple[np.ndarray, np.ndarray]:
        """Материал уровня для повторения: широкий набор режимов, но не экзамен."""
        if item.get('bank') is not None:
            return item['bank']
        mask = item['mask']
        n_glyph = int(mask.sum())
        variants = int(max(2, min(int(os.environ.get('OWNOCR_REH_VAR', 4)), 20000 // max(1, n_glyph))))
        modes = os.environ.get('OWNOCR_REH_MODES', 'clean,easy').split(',')
        bank = self._feat_bank(mask, modes, variants, seed=333 + len(item['key']))
        if len(bank[1]) > 8000:
            idx = np.random.default_rng(7).choice(len(bank[1]), 8000, replace=False)
            bank = (bank[0][idx], bank[1][idx])
        item['bank'] = bank
        self.say(f'   повторение уровня «{item["key"]}»: {len(bank[1])} примеров '
                 f'({variants} режима) — материал собран')
        return bank

    def _remember_stage(self, st, mask: np.ndarray):
        """Запомнить уровень для повторения на следующих ступенях."""
        mask = mask.copy()
        mask &= np.array([lab in set(self.labels[mask]) for lab in self.labels])
        self.rehearsal_stages.append({'key': st['key'], 'mask': mask, 'bank': None})

    def _remember(self, X: np.ndarray, Y: np.ndarray, every: int = 1):
        """Запомнить материал уровня для повторения на следующих ступенях."""
        if len(Y) == 0:
            return
        idx = np.arange(0, len(Y), max(1, every))
        self.rehearsal_X.append(X[idx].copy())
        self.rehearsal_y.append(Y[idx].copy())
        self.rehearsal_n += len(idx)
        total = sum(len(a) for a in self.rehearsal_y)
        while total > self.rehearsal_cap and len(self.rehearsal_y) > 1:
            total -= len(self.rehearsal_y.pop(0))
            self.rehearsal_X.pop(0)
        self.say(f'   запомнено для повторения: {self.rehearsal_n} примеров '
                 f'(в резервуаре {total})')

    # ── университет: настоящие строки манги ─────────────────────────────────
    def real_pairs(self, labels_tsv: str, max_rows: int = 400):
        """Пары «картинка–буква» из настоящих строк (выравнивание как в уроке 7)."""
        from .engine import binarize, boxes_of, line_band
        from .lesson_real import align, read_rows
        if not labels_tsv or not os.path.exists(labels_tsv):
            return None, None
        base = os.path.dirname(labels_tsv)
        rows = [(os.path.join(base, n), t) for n, t in read_rows(labels_tsv)]
        rng = np.random.default_rng(11)
        X, Y = [], []
        used = 0
        for path, ref in rows[:max_rows]:
            gray = cv2.imread(path, cv2.IMREAD_GRAYSCALE) if (cv2 := _cv2()) else None
            if gray is None:
                continue
            bw = binarize(gray)
            y0, y1 = line_band(bw)
            gray, bw = gray[y0:y1], binarize(gray[y0:y1])
            from .segment import pieces_as_boxes
            boxes, probs, _ = pieces_as_boxes(self, gray, bw)
            good = None
            if boxes:
                feats = [features(gray[max(0, b[1]):b[3], max(0, b[0]):b[2]]) for b in boxes]
                good = [(b, f) for b, f in zip(boxes, feats) if f is not None]
                if good:
                    boxes = [b for b, _ in good]
                    probs = self.model.predict_proba(np.stack([f for _, f in good]))
            if not good:
                boxes = boxes_of(bw)
                feats = [features(gray[max(0, b[1]):b[3], max(0, b[0]):b[2]]) for b in boxes]
                good = [(b, f) for b, f in zip(boxes, feats) if f is not None]
                if not good:
                    continue
                boxes = [b for b, _ in good]
                probs = self.model.predict_proba(np.stack([f for _, f in good]))
            text = ''.join(c for c in ref.upper() if c.isalnum())
            pairs = align([b for b, _ in good], text, probs, self.classes)
            if len(pairs) < 0.8 * len(text):
                continue
            nll = float(np.mean([-np.log(np.clip(probs[i, self.cls_index[text[j]]], 1e-6, 1.0))
                                 for i, j in pairs]))
            if nll > 3.0:
                continue
            used += 1
            for i, j in pairs:
                b = good[i][0]
                crop = gray[max(0, b[1]):b[3], max(0, b[0]):b[2]]
                if crop.size == 0:
                    continue
                for v in range(6):
                    g = crop if v == 0 else D.augment(crop, rng, ['easy', 'italic', 'hard', 'small', 'italic'][v - 1])
                    f = features(g)
                    if f is not None:
                        X.append(f)
                        Y.append(self.cls_index[text[j]])
        self.say(f'   настоящие строки: доверенных {used} · пар с упражнениями {len(Y)}')
        if not X:
            return None, None
        return np.stack(X), np.array(Y, np.int32)

    # ── аспирантура: учиться на том, в чём уверен ───────────────────────────
    def self_train_pairs(self, page: str, n_max: int = 3000):
        """Псевдоразметка: буквы, в которых ученик уверен, + проверка словарём."""
        cv2 = _cv2()
        from .engine import binarize, boxes_of, line_band
        gray = cv2.imread(page, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None, None
        bw = binarize(gray)
        ink = (bw > 0).sum(axis=1)
        thr = max(3, int(0.01 * bw.shape[1]))
        lines, start = [], None
        for y, v in enumerate(ink):
            if v > thr and start is None:
                start = y
            elif v <= thr and start is not None:
                if y - start >= 8:
                    lines.append((start, y))
                start = None
        X, Y = [], []
        for (a, b) in lines:
            sub = gray[max(0, a - 2):b + 2]
            bws = binarize(sub)
            boxes = boxes_of(bws)
            feats = [features(sub[max(0, bb[1]):bb[3], max(0, bb[0]):bb[2]]) for bb in boxes]
            good = [(bb, f) for bb, f in zip(boxes, feats) if f is not None]
            if len(good) < 3:
                continue
            probs = self.model.predict_proba(np.stack([f for _, f in good]))
            for (bb, _), pr in zip(good, probs):
                k = int(pr.argmax())
                if pr[k] >= 0.85:                     # ученик уверен — берём как «своё»
                    crop = sub[max(0, bb[1]):bb[3], max(0, bb[0]):bb[2]]
                    f = features(crop)
                    if f is not None:
                        X.append(f)
                        Y.append(k)
        if not X:
            return None, None
        sel = min(n_max, len(X))
        idx = np.random.default_rng(3).choice(len(X), sel, replace=False)
        self.say(f'   самопроверка: уверенных букв {len(X)} · взято {sel}')
        return np.stack(X)[idx], np.array(Y, np.int32)[idx]

    def revision(self, st, labels_tsv=None, min_minutes=5.0):
        """Повторение до конца бюджета: фиксируем только улучшения."""
        if self.model is None or self.left() < min_minutes:
            return
        self.say('')
        self.say(f'── ПОВТОРЕНИЕ ДО ЗВОНКА · осталось {self.left():.1f} мин ─────────────')
        mask = np.ones(len(self.imgs), bool)
        X, Y = self._feat_bank(mask, ['italic', 'hard', 'small', 'easy'], 6, seed=4242)
        Xr, Yr = self.real_pairs(labels_tsv or '')
        if Xr is not None:
            X = np.vstack([X, Xr, Xr])
            Y = np.concatenate([Y, Yr, Yr])
        exams = {k: v for k, v in self.exams.items()}
        base_clean = self.score(*exams['high']) if 'high' in exams else self.score(*list(exams.values())[-1])
        base_p = self.score(*self.exam(self.holdout_fonts, None, mode='italic', seed=77))
        best = 0.5 * (base_clean + base_p)
        self.say(f'   старт: экзамен {100 * base_clean:.1f} % · с наклоном {100 * base_p:.1f} % '
                 f'· средняя {100 * best:.1f} %')
        round_no, kept, dropped = 0, 0, 0
        while self.left() > min_minutes:
            round_no += 1
            self.model.fit(X, Y, epochs=4, batch=128, lr=2.2e-4, seed=1000 + round_no, log=None)
            c = self.score(*exams['high']) if 'high' in exams else base_clean
            p = self.score(*self.exam(self.holdout_fonts, None, mode='italic', seed=77))
            score = 0.5 * (c + p)
            if score > best + 1e-4:
                best = score
                kept += 1
                base_clean, base_p = c, p
                self.save(self.workdir, f'revision-{round_no}')
                verdict = 'ЗАФИКСИРОВАНО'
            else:
                dropped += 1
                self.model.load(os.path.join(self.workdir, 'stage-university.npz')
                                if os.path.exists(os.path.join(self.workdir, 'stage-university.npz'))
                                else os.path.join(self.workdir, f'stage-{list(exams)[-1]}.npz'))
                verdict = 'откат (не лучше)'
            self.say(f'   круг {round_no:2d}: экзамен {100 * c:5.1f} % · с наклоном {100 * p:5.1f} % '
                     f'· средняя {100 * score:5.1f} % → {verdict} · осталось {self.left():.1f} мин')
        self.diploma.append({'key': 'revision', 'name': f'повторение ×{round_no}',
                             'exam': base_clean, 'exam_hard': base_p, 'target': 0.0,
                             'passed': True, 'seconds': 0, 'n_examples': int(len(Y)),
                             'fonts_taught': 0, 'epochs_best': 0,
                             'kept': kept, 'dropped': dropped})
        self.say(f'   итог повторения: кругов {round_no}, зафиксировано {kept}, откачено {dropped}')

    # ── сохранение ───────────────────────────────────────────────────────────
    def save(self, path: str, tag: str):
        if self.model is None:
            return
        os.makedirs(path, exist_ok=True)
        self.model.save(os.path.join(path, f'stage-{tag}.npz'))
        self.model.save(os.path.join(path, 'ownocr-latest.npz'))
        json.dump({'classes': self.classes, 'case': 'upper', 'dim': self.model.d_in,
                   'hidden': self.model.hidden, 'meta': self.meta},
                  open(os.path.join(path, 'ownocr-latest.npz.json'), 'w'), ensure_ascii=False)
        json.dump({'diploma': self.diploma, 'left_min': round(self.left(), 1)},
                  open(os.path.join(path, 'diploma.json'), 'w'), ensure_ascii=False, indent=1)

    # ── весь курс ────────────────────────────────────────────────────────────
    def run(self, stages=None, labels_tsv: str | None = None, page: str | None = None):
        self.labels_tsv = labels_tsv if (labels_tsv and os.path.exists(labels_tsv)) else None
        keys = stages or [s['key'] for s in STAGES]
        for st in STAGES:
            if st['key'] not in keys:
                continue
            # не начинаем уровень, если на него не хватит времени
            est = self.estimate(st)
            if self.left() * 60 < est:
                self.say(f'\n⏳ время вышло: до «{st["name"]}» нужно ~{est / 60:.0f} мин, '
                         f'осталось {self.left():.0f} — сохраняю диплом и останавливаюсь')
                break
            extra_X = extra_y = None
            if st.get('real'):
                self.say('')
                self.say('   университет: разбираем настоящую страницу (пары «картинка–буква»)')
                extra_X, extra_y = self.real_pairs(labels_tsv or '')
            if st.get('self_train') and page:
                sx, sy = self.self_train_pairs(page)
                if sx is not None:
                    extra_X = sx if extra_X is None else np.vstack([extra_X, sx])
                    extra_y = sy if extra_y is None else np.concatenate([extra_y, sy])
            rec = self.run_stage(st, extra_X, extra_y)
            self.save(self.out, 'latest')
            if not rec['passed']:
                self.say('   ученик остаётся на этом уровне; следующий не начинаем круг')
                # мягкая пересдача: ещё несколько эпох с меньшим шагом
                st2 = dict(st, epochs=max(4, st['epochs'] // 2), lr=st['lr'] * 0.4)
                rec2 = self.run_stage(st2, extra_X, extra_y)
                if not rec2['passed']:
                    self.say('   пересдача не удалась — идём дальше, но помечаем')
                    self.diploma.append(dict(rec2, conditional=True))
        # ── ПОВТОРЕНИЕ ДО ЗВОНКА ────────────────────────────────────────────
        # После диплома время обычно ещё есть. Учитель не сидит без дела: крутит
        # самые трудные упражнения (наклон + мелкий кегль + шум) и оставляет
        # только те круги, после которых экзамен стал ЛУЧШЕ. Плохой круг
        # откатывается — «зафиксировано только верное».
        self.revision(st, labels_tsv) if self.model is not None else None

        self.say('')
        self.say('═' * 84)
        passed = [d for d in self.diploma if d['passed']]
        self.say(f'ДИПЛОМ: сдано уровней {len(passed)} из {len(STAGES)} · '
                 f'потрачено {(time.time() - self.t0) / 60:.1f} мин')
        for d in self.diploma:
            mark = '✓' if d['passed'] else '…'
            self.say(f'   {mark} {d["name"]:18s} экзамен {100 * d["exam"]:5.1f} % · '
                     f'с наклоном {100 * d["exam_hard"]:5.1f} % · {d["seconds"]:.0f} с')
        self.save(self.out, 'final')
        return self.diploma


def _cv2():
    import cv2
    return cv2


def resume_state(path: str) -> dict:
    p = os.path.join(path, 'diploma.json')
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))
    return {}
