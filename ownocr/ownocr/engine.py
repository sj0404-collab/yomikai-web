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
        meta_name = next(f for f in ('ownocr-latest.npz.json', 'ownocr.npz.json')
                         if os.path.exists(os.path.join(model_dir, f)))
        meta = json.load(open(os.path.join(model_dir, meta_name), encoding='utf-8'))
        self.classes = list(meta['classes'])
        self.case = meta.get('case', 'upper')
        self.model = OwnClassifier(meta['dim'], len(self.classes), hidden=meta.get('hidden', 192))
        # курс обучения кладёт модель как ownocr-latest.npz, старые скрипты — ownocr.npz
        weights = [f for f in ('ownocr-latest.npz', 'ownocr.npz') if
                   os.path.exists(os.path.join(model_dir, f))]
        if not weights:
            raise FileNotFoundError(f'в {model_dir} нет ни ownocr-latest.npz, ни ownocr.npz')
        self.model.load(os.path.join(model_dir, weights[0]))
        self.vocab = {}
        self.vocab_by_first = {}
        self.vocab_by_len: dict[int, list[str]] = {}
        self.letter_of: dict[int, str] = {}
        if vocab_path and os.path.exists(vocab_path):
            with open(vocab_path, encoding='utf-8') as f:
                for rank, line in enumerate(f):
                    w = line.strip().upper()
                    if w and len(w) <= 24:
                        self.vocab[w] = rank
                        self.vocab_by_first.setdefault(w[0], []).append(w)
                    if len(self.vocab) >= vocab_size:
                        break
        for w in self.vocab:
            self.vocab_by_len.setdefault(len(w), []).append(w)
        self.letter_of = {i: c for i, c in enumerate(self.classes)}
        self.cls_index = {c: i for i, c in enumerate(self.classes)}

    # ── чтение одной строки ──────────────────────────────────────────────────
    def read_line(self, gray: np.ndarray, lexicon: bool = True, topk: int = 5,
                  band: bool = True, method: str = 'auto'):
        bw = binarize(gray)
        if band:
            y0, y1 = line_band(bw)
            if y1 - y0 >= 6 and y1 - y0 < gray.shape[0]:
                gray = gray[y0:y1]
                bw = binarize(gray)
        if method == 'auto':
            a = self._read_by_boxes(gray, bw, lexicon, topk)
            if a is not None and self._sure(a):
                if lexicon and a.get('text'):
                    a['text'] = self.repair_marks(a['text'])
                return a                       # дешёвый путь уверен — не тратим время
            if bw.shape[1] > 900:              # не настоящая строка, а полоса листа
                return a or {'text': '', 'glyphs': [], 'conf': 0.0}
            b = self._read_by_segmentation(gray, bw, lexicon, topk)
            if a is None:
                best = b or {'text': '', 'glyphs': [], 'conf': 0.0}
            elif b is None:
                best = a
            else:
                best = b if self._line_score(b) > self._line_score(a) else a
            if lexicon and best.get('text'):
                best['text'] = self.repair_marks(best['text'])
            return best
        if method == 'segment':
            r = self._read_by_segmentation(gray, bw, lexicon, topk)
            if r is not None:
                return r
        return self._read_by_boxes(gray, bw, lexicon, topk)

    # ── починка потерянных меток ─────────────────────────────────────────────
    # Замер по настоящей странице: «Й» читалась как «И» в 42 % случаев, «Ё» как
    # «Е» — в 100 %. Все случаи — на месте, где краткая и точки меньше пикселя:
    # буква в манге набрана кеглем ~12 px, метка на ней не рисуется вовсе.
    # Признаки и адресное дообучение это не лечат (проверено, оба варианта хуже),
    # а сверка со словарём — лечит: «ПОЖАЛУИСТА» в словаре нет, «ПОЖАЛУЙСТА» есть.
    MARK_SWAPS = [('И', 'Й'), ('Е', 'Ё'), ('0', 'О'), ('2', 'О'), ('4', 'Ч'),
                  ('O', 'О'), ('A', 'А'), ('B', 'В'), ('H', 'Н'), ('K', 'К'),
                  ('M', 'М'), ('T', 'Т'), ('X', 'Х'), ('C', 'С'), ('P', 'Р'),
                  ('Y', 'У'), ('3', 'З'), ('6', 'Б'), ('8', 'В')]

    REPAIR = os.environ.get('OWNOCR_REPAIR', 'marksdigits')   # marksdigits | marks | general | off

    LEXWORD = os.environ.get('OWNOCR_LEXWORD', '0') == '1'   # замер: с ним хуже (18,1 % против 16,3 %)

    def _lexicon_word(self, probs, idxs, extra_cost: float = 2.0):
        """Перечитать слово целиком по словарю: какое слово вероятнее всего.

        Не «замена одной буквы» (она ломала верные слова: «СДЕЛАИ» → «СДЕЛАЛ»),
        а выбор слова по сумме логарифмов вероятностей всех его букв плюс
        частота слова. Кандидаты — все слова словаря нужной длины (±1, с
        штрафом за лишнюю/недостающую букву).

        Зачем: на настоящем почерке ученик путает П↔И, В↔З, Т↔Л. Правильного
        ответа часто нет в топ-5 букв, но вероятность у него не нулевая — и
        словарь вытягивает «ПОВВОИЬ» → «ПОЗВОЛЬ», «ШЕЛЧЕТ» → «ШЕПЧЕТ».
        """
        if not self.vocab:
            return None
        n = len(idxs)
        if n < 3 or n > 20:
            return None
        # вероятности букв по позициям: (n, classes)
        P = np.asarray([probs[i] for i in idxs], np.float64)
        cls = np.array([int(k) for k in idxs], np.int32)
        logP = np.log(np.clip(P, 1e-6, 1.0))
        best, best_score = None, -1e9
        for L, cost in ((n, 0.0), (n + 1, extra_cost), (n - 1, extra_cost)):
            words = self.vocab_by_len.get(L, ())
            if not words:
                continue
            idx_map = np.array([[self.cls_index.get(c, -1) for c in w] for w in words],
                               np.int32)
            ok = (idx_map >= 0).all(axis=1)
            if not ok.any():
                continue
            words_ok = [w for w, k in zip(words, ok) if k]
            M = idx_map[ok]
            rows_idx = np.arange(n)[None, :]
            if L == n:
                sc = logP[rows_idx, M].sum(axis=1)
            else:
                # грубое выравнивание при сдвиге длины: берём лучшее по позициям
                sc = np.array([-cost - 0.7 * abs(L - n)
                               * np.log(10) for _ in range(len(words_ok))])
                for j, w in enumerate(words_ok):
                    m = min(L, n)
                    cols = np.array([[self.cls_index[c] for c in w[:m]]])
                    sc[j] += logP[np.arange(m)[None, :], cols].sum()
            freq = np.array([0.6 * math.log(1 + 40000.0 / (1 + self.vocab[w]))
                             + self.VOCAB_BONUS for w in words_ok])
            total = sc + freq
            k = int(np.argmax(total))
            if total[k] > best_score:
                best_score, best = float(total[k]), words_ok[k]
        return (best, best_score) if best else None

    VOCAB_BONUS = 2.0

    # Пары, которые ученик действительно путает на странице (из разбора выше):
    # П↔Л, В↔З, Т↔Г, И↔Л, И↔Н, Ш↔Щ, Ч↔П, Ь↔И.
    CONFUSABLE = [('П', 'Л'), ('Л', 'П'), ('В', 'З'), ('З', 'В'), ('Т', 'Г'), ('Г', 'Т'),
                  ('И', 'Л'), ('Л', 'И'), ('И', 'Н'), ('Н', 'И'), ('Ш', 'Щ'), ('Щ', 'Ш'),
                  ('Ч', 'П'), ('П', 'Ч'), ('Ь', 'И'), ('И', 'Ь'), ('Д', 'И'), ('И', 'Д'),
                  ('С', 'О'), ('О', 'С'), ('Н', 'Б'), ('Б', 'Н'), ('Ж', 'Х'), ('Х', 'Ж')]

    def _repair_word(self, word: str, max_subs: int = 1) -> str:
        """Если слово не из словаря — взять ближайшее словарное той же длины.

        Не «подогнать под словарь что угодно», а именно вернуть потерянную
        метку: правим только слова, которых в словаре нет, и только если
        найденное слово отличается на 1–2 символа. Из кандидатов берём самое
        частое (у него меньший номер в частотном списке).
        """
        if not self.vocab or len(word) < 3:
            return word
        up = word.upper()
        if up in self.vocab:
            return word
        if self.REPAIR in ('marks', 'marksdigits') and not any(c.isdigit() for c in up):
            # только метки: одна замена из списка похожих пар.
            # только метки: одна замена из списка похожих пар. Общий поиск
            # «ближайшего слова» проверялся — он ломает верные слова
            # («СДЕЛАИ» → «СДЕЛАЛ» вместо «СДЕЛАЙ»), поэтому по умолчанию
            # работает осторожный вариант.
            for i, ch in enumerate(up):
                for src, dst in self.MARK_SWAPS:
                    if ch == src:
                        cand = up[:i] + dst + up[i + 1:]
                        if cand in self.vocab:
                            return cand
            return word
        if self.REPAIR in ('marksmall', 'marksdigits') and not any(c.isdigit() for c in up):
            # Рукописные буквы (манхва): «СВОИХ» читается «ОВОИХ», «АБСОЛЮТОМ» —
            # «АБООЛЮТОМ». Правим ОДНУ замену, и только в знакомых парах —
            # словарь тут не «угадывает слово», а возвращает букву по форме.
            best = None
            # ищем по длине, а не по первой букве: путаница О↔С меняет и первую
            for w in self.vocab_by_len.get(len(up), []):
                diff = [i for i, (a, b) in enumerate(zip(up, w)) if a != b]
                if len(diff) != 1:
                    continue
                i = diff[0]
                if not any((up[i] == a and w[i] == b) for a, b in self.CONFUSABLE):
                    continue
                rank = self.vocab.get(w, 10 ** 6)
                if best is None or rank < best[0]:
                    best = (rank, w)
            return best[1] if best else word
        if self.REPAIR == 'marksdigits' and any(c.isdigit() for c in up):
            # Цифра внутри слова — почти всегда потерянная буква («УТОДН2» →
            # «УГОДНО», «Р5ИОМ» → «РЯДОМ»). Здесь словарь разрешаю шире, чем для
            # обычных слов: правил меток не хватает, нужно две замены. Но ищу
            # только среди слов, где на месте цифры стоит буква, — иначе
            # словарь начнёт переписывать верные слова.
            digits = [i for i, c in enumerate(up) if c.isdigit()]
            best = None
            for w in self.vocab_by_len.get(len(up), []):
                if any(w[i].isdigit() for i in digits):
                    continue
                diff = [i for i, (a, b) in enumerate(zip(up, w)) if a != b]
                if len(diff) > 2 or not set(diff) - set(digits) == set(diff) - set(digits):
                    continue
                # буквенные замены разрешаем только в знакомых парах
                letters_ok = all(any((up[i] == a and w[i] == b) for a, b in self.CONFUSABLE)
                                 for i in diff if i not in digits)
                if not letters_ok:
                    continue
                rank = self.vocab.get(w, 10 ** 6)
                if best is None or rank < best[0]:
                    best = (rank, w)
            return best[1] if best else word
        cands = self.vocab_by_first.get(up[0], [])
        best = None
        for w in cands:
            if len(w) != len(up):
                continue
            diff = [i for i, (a, b) in enumerate(zip(up, w)) if a != b]
            if len(diff) > max_subs:
                continue
            # цифра внутри слова — почти всегда потерянная буква, а не цифра
            digits = any(c.isdigit() for c in up)
            if len(diff) == 2 and not (digits or len(up) >= 9):
                continue
            rank = self.vocab.get(w, 10 ** 6)
            if best is None or rank < best[0]:
                best = (rank, w)
        return best[1] if best else word

    def repair_marks(self, text: str) -> str:
        """Починить метки во всей строке (слова от трёх букв)."""
        if not self.vocab or not text or self.REPAIR == 'off':
            return text
        out, changed = [], False
        for word in text.split(' '):
            core = word.strip('.,!?…—«»"():;%')
            fixed = self._repair_word(core) if core else core
            if fixed != core:
                changed = True
                word = word.replace(core, fixed)
            out.append(word)
        return ' '.join(out) if changed else text

    def _sure(self, r) -> bool:
        """Дешёвое чтение можно принять без разреза по узнаванию?"""
        text = (r.get('text') or '').upper()
        words = [w for w in text.split() if len(w) >= 2]
        if not words or r.get('conf', 0) < 0.88:
            return False
        known = sum(1 for w in words if w in self.vocab)
        return known / len(words) >= 0.75

    def _line_score(self, r) -> float:
        """Оценка прочтения: уверенность букв + знакомость слов (выше — лучше)."""
        text = r.get('text') or ''
        letters = sum(1 for c in text if c.isalnum())
        if not letters:
            return -9.0
        words = [w for w in text.upper().split() if len(w) >= 2]
        known = sum(1 for w in words if w in self.vocab)
        return float(r.get('conf', 0.0)) + 0.15 * (known / len(words) if words else 0)

    def _read_by_boxes(self, gray: np.ndarray, bw: np.ndarray, lexicon: bool, topk: int):
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

        # Обрывки от рамки облачка и штриховки: очень узкие или очень широкие
        # пятна — это не буквы. Без этого в реплику попадают «П»АЛИЙЯА», «ЭП%»,
        # «Р5ИОМ»: обрывок рамки читается как буква и приклеивается к слову.
        if os.environ.get('OWNOCR_SLIVER', '1') == '1' and len(keep) >= 5:
            heights = np.array([b[3] - b[1] for b in keep], np.float32)
            med_h = float(np.median(heights)) or 1.0
            words_w = np.array(widths, np.float32) if (widths := [b[2] - b[0] for b in keep]) else None
            med_w0 = float(np.median(words_w)) or 1.0
            ok = []
            for i, b in enumerate(keep):
                h = max(1, b[3] - b[1])
                w = max(1, b[2] - b[0])
                if h < 0.45 * med_h and w < 0.6 * med_w0:
                    continue                     # мелкая точка-шум
                if w > 2.6 * med_w0 or h > 3.0 * med_h:
                    continue                     # полоса рамки
                ok.append(i)
            if len(ok) >= max(2, int(0.5 * len(keep))):
                keep = [keep[i] for i in ok]
                feats = [feats[i] for i in ok]
                probs = probs[ok]
                order = order[ok]

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

    def _near_word(self, word: str, by_first: dict) -> int:
        """Частота ближайшего слова с одной заменой (для «почти слова»)."""
        cands = by_first.get(word[:1], [])
        best = -1
        for w in cands:
            if abs(len(w) - len(word)) > 1:
                continue
            if len(w) == len(word):
                diff = sum(1 for a, b in zip(word, w) if a != b)
                if diff > 1:
                    continue
            else:
                longer, shorter = (word, w) if len(word) > len(w) else (w, word)
                if not any(longer[:i] + longer[i + 1:] == shorter for i in range(len(longer))):
                    continue
            r = self.vocab.get(w, 10 ** 6)
            if best < 0 or r < best:
                best = r
        return best

    def _read_by_segmentation(self, gray, bw, lexicon, topk):
        """Чтение через разрез по узнаванию (segment.py). None — если не вышло."""
        from .segment import segment_line
        try:
            pieces = segment_line(self, gray, bw, topk=topk)
        except Exception:
            return None
        if not pieces:
            return None
        # Обрывки: очень узкий кусок (полоска рамки, штрих) или очень широкий —
        # это не буква. Из-за них в репликах появляется «П»АЛИЙЯА», «ЭП%».
        if os.environ.get('OWNOCR_SLIVER', '1') == '1' and len(pieces) >= 6:
            ws = np.array([pc[1] - pc[0] for pc in pieces], np.float32)
            med = float(np.median(ws)) or 1.0
            kept = [pc for pc in pieces
                    if 0.34 * med <= (pc[1] - pc[0]) <= 2.5 * med]
            if len(kept) >= max(3, int(0.6 * len(pieces))):
                pieces = kept
        # куски отдают только топ-k, поэтому собираем полную матрицу классов
        # (57 столбцов): иначе декодер принимает номер в топе за номер класса
        probs = np.zeros((len(pieces), len(self.classes)), np.float32)
        for i, pc in enumerate(pieces):
            probs[i, pc[2]] = pc[3]
        # куски без вероятностей отбрасываем (бывает на пустом крае)
        glyphs, words = [], []
        boxes = [(x, 0, y, gray.shape[0]) for x, y, _, _, _ in pieces]
        # пробелы уже расставлены разрезом (см. segment.py: start_of_word)
        groups, group = [], []
        for i, pc in enumerate(pieces):
            if pc[4] and group:
                groups.append(group)
                group = []
            group.append(i)
        if group:
            groups.append(group)
        for g in groups:
            if lexicon and len(g) >= 2:
                word, detail = self._decode_word(probs, None, g, topk=max(topk, 5))
            else:
                word, detail = '', []
                for i in g:
                    word += self.classes[int(probs[i].argmax())]
                    detail.append({'char': self.classes[int(probs[i].argmax())],
                                   'prob': float(probs[i].max())})
            for pos, item in enumerate(detail):
                item['box'] = boxes[g[pos]] if pos < len(g) else None
            words.append(word)
            glyphs.extend(detail)
        text = ' '.join(w for w in words if w)
        if self.case == 'upper':
            text = text.upper()
        conf = float(np.mean([g['prob'] for g in glyphs])) if glyphs else 0.0
        return {'text': text, 'glyphs': glyphs, 'conf': conf}

    def _decode_word(self, probs, order, idxs, beam: int = 16, topk: int = 5):
        """Свой beam search: буквы по вероятностям + бонус словарю за слово."""
        # слова-кандидаты по первому символу: с ними бонус словарю работает не
        # только для идеального совпадения, но и для «почти слова»
        by_first = self.vocab_by_first or None
        beams = [('', 0.0, [])]
        for i in idxs:
            cand = []
            if order is not None:
                row = [(int(order[i, r]), float(probs[i, int(order[i, r])]))
                       for r in range(order.shape[1])]
            else:
                top = np.argsort(-probs[i])[:topk]
                row = [(int(k), float(probs[i, int(k)])) for k in top]
            for prefix, score, detail in beams:
                for k, p in row:
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
                near = self._near_word(key, by_first) if by_first else -1
                if near >= 0:
                    # «почти слово»: отличаемся одной буквой — половина бонуса
                    score += 0.5 * (2.0 + 0.6 * math.log(1 + 40000.0 / (1 + near)))
                else:
                    score -= 0.5
            if score > best_score:
                best_score, best = score, (text, score, detail)
        text, _, detail = best
        if self.LEXWORD and self.vocab and 3 <= len(text) <= 20:
            # Сравниваем две гипотезы ОДНОЙ формулой: сумма логарифмов
            # вероятностей букв + премия за частотное слово. Раньше сравнивались
            # несравнимые числа (beam уже содержал премию), и словарь не влиял.
            logP = np.log(np.clip(np.array([probs[i] for i in idxs], np.float64), 1e-6, 1.0))
            def score_of(w):
                m = min(len(w), logP.shape[0])
                cols = np.array([[self.cls_index.get(c, 0) for c in w[:m]]])
                sc = float(logP[np.arange(m)[None, :], cols].sum())
                if len(w) != logP.shape[0]:
                    sc -= 2.0
                if w in self.vocab:
                    sc += self.VOCAB_BONUS + 0.6 * math.log(1 + 40000.0 / (1 + self.vocab[w]))
                else:
                    sc -= 0.5
                return sc
            cand = self._lexicon_word(probs, idxs)
            if cand:
                word, _ = cand
                if score_of(word) > score_of(text) + 0.05:
                    text = word
                    detail = [{'char': c, 'prob': 0.9} for c in word]
                    best_score = score_of(word)
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
