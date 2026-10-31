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


PICK = os.environ.get('OWNOCR_PICK', 'score')     # score | vote


def _word_ok(word: str) -> bool:
    core = word.strip(EDGE_PUNCT).upper()
    return bool(VOCAB) and core in VOCAB


def _score_pick(seen: list[tuple[str, float]]) -> tuple[str, float]:
    """Выбрать целое прочтение по оценке: словарные слова, мусор, уверенность."""
    best, best_s = '', -1e9
    for text, conf in seen:
        if not any(ch.isalnum() for ch in text):
            continue                      # одни кавычки и проценты — не прочтение
        words = [w for w in text.split() if w.strip(EDGE_PUNCT)]
        if not words:
            continue
        known = sum(1 for w in words if _word_ok(w)) / len(words)
        junk = sum(1 for ch in text if ch in JUNK_IN_WORD) / max(1, len(text))
        s = 1.0 * known + 0.3 * conf - 2.0 * junk
        if s > best_s:
            best, best_s = text, s
    return best, max((c for t, c in seen if t == best), default=0.0)


def _vote_words(seen: list[tuple[str, float]]) -> tuple[str, float]:
    """Собрать строку по голосам масштабов, слово за словом.

    Если масштабы дали разное число слов, голосовать не по чему — отдаём
    лучшее по уверенности целое прочтение (вызывающий это переживёт).
    """
    parts = [t.split() for t, _ in seen]
    if len({len(p) for p in parts}) != 1:
        return '', -1.0
    out = []
    for pos in range(len(parts[0])):
        cands = [p[pos] for p in parts]
        counts: dict[str, int] = {}
        for c in cands:
            counts[c] = counts.get(c, 0) + 1
        top = max(counts.values())
        finalists = [c for c, n in counts.items() if n == top]
        if len(finalists) == 1:
            out.append(finalists[0])
            continue
        in_vocab = [c for c in finalists
                    if VOCAB and c.strip('.,!?…—«»"():;%').upper() in VOCAB]
        pool = in_vocab or finalists
        # при равенстве — слово из прочтения с большей уверенностью
        order = [t for t, _ in sorted(seen, key=lambda x: -x[1])]
        out.append(next(c for t in order for c in pool if c in t.split()[pos:pos + 1]))
    return ' '.join(out), seen[0][1]


TIDY = os.environ.get('OWNOCR_TIDY', '1') == '1'
DARK_FRAC = float(os.environ.get('OWNOCR_DARK', '0.55'))   # доля тёмного, при которой пробуем перевернуть
JUNK_IN_WORD = '»«"“”„%№$|\\/~^`*+=<>[]{}'


EDGE_PUNCT = '.,!?…—'


def tidy(text: str) -> str:
    """Убрать знаки, которых в реплике быть не может: «П»АЛИЙЯА» → «ПАЛИЙЯА».

    Кавычки и проценты попадают внутрь слова и на его край, когда ученик
    принимает обрывок штриха за букву. Настоящей пунктуацией считаем только
    «.,!?…—»; их по краям оставляем, а кавычки, проценты и скобки убираем.
    Внутри слова остаются буквы, цифры и дефис («ЧТО-НИБУДЬ»).
    """
    out = []
    for word in text.split():
        lead = word[:len(word) - len(word.lstrip(EDGE_PUNCT))]
        rest = word[len(lead):].strip(JUNK_IN_WORD + '()[]{}')
        body = rest.rstrip(EDGE_PUNCT)
        trail = rest[len(body):]
        if len(body) >= 3:
            body = ''.join(c for c in body if c not in JUNK_IN_WORD)
        out.append((lead + body + trail) if body else lead)
    return ' '.join(out)


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
    def __init__(self, model_dir: str, scales=(2.0, 2.5, 3.0, 3.5), sure: float = 0.8,
                 scales_harsh=(3.0, 4.0, 5.0), blur_harsh: bool = False,
                 pad: float = 0.0, vote: bool = True):
        self.ocr = OwnOCR(model_dir)
        self.scales, self.sure = tuple(scales), float(sure)
        self.scales_harsh = tuple(scales_harsh)
        self.blur_harsh = blur_harsh
        # Отступ вокруг буквы. Проверялся (0,12 / 0,15 / 0,18 / 0,20): на деле
        # он ВРЕДИТ — CER на dense-a 13,4 → 20,6 %. Первый перебор показывал
        # выигрыш потому, что тестовый класс добавлял отступ, а затем сам же
        # срезал его повторной обрезкой по чернилам. По умолчанию отступа нет,
        # параметр оставлен для будущих опытов.
        self.pad = float(pad)
        # Голосование по масштабам на уровне слова. Раньше: первый масштаб с
        # уверенностью ≥ sure и всё, остальные не считались. Ошибки на «×2» и
        # «×3» разные (на ×2 «ПОЖАЛУЙСТА» → «ПОЖАЛУ№П%», на ×3 верно), поэтому
        # читаем все масштабы и по каждому слову берём то, за которое
        # проголосовало большинство масштабов, при равенстве — словарное.
        self.vote = bool(vote)

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
        if self.pad > 0:
            h, w = g.shape[:2]
            py, px = max(1, int(round(h * self.pad))), max(1, int(round(w * self.pad)))
            g = cv2.copyMakeBorder(g, py, py, px, px, cv2.BORDER_CONSTANT, value=255)
        # Белый текст на чёрной плашке (нарратив в манге): без переворота такой
        # кроп читается мусором и отбрасывается («ОНО ЧТО-ТО СДЕЛАЛО СО МНОЙ…»
        # на page16 не появлялось вовсе). Но переворачивать всё тёмное нельзя —
        # на dense-b тёмный рисунок дал лишнюю «реплику» и CER 102 %. Поэтому
        # читаем оба варианта и берём тот, где больше словарных слов.
        best = self._read_scales(g, harsh)
        # Перевёрнутый вариант пробуем только когда обычное чтение не дало ни
        # одного словарного слова: так плашка с белым текстом спасается, а
        # тёмный рисунок не порождает лишнюю «реплику» (на dense-b это давало
        # 10 реплик вместо 9 и CER 102 %).
        if g.size and known_words(best[0]) == 0 and float((g < 96).mean()) >= DARK_FRAC:
            alt = self._read_scales(255 - g, harsh)
            # Критерий — не число слов, а их доля: строка плашки короткая
            # («ОНО»), и по числу она проигрывает служебной надписи со края
            # страницы («СГЮАВА НАЛЕВО» — одно слово из двух). Здесь наоборот:
            # у плашки все слова словарные, у надписи — половина.
            words = [w for w in alt[0].split() if w.strip(EDGE_PUNCT)]
            share = sum(1 for w in words if _word_ok(w)) / len(words) if words else 0.0
            if share >= 0.9 and alt[1] >= 0.85:
                return alt
        # Выравнивание контраста по перцентилям для цветной манхвы проверялось:
        # строки читаются не лучше («ДАБЫ ТЕМ САМЫ» вместо «ДАБЫ ТЕМ САМЫМ»),
        # поэтому подстраховка убрана — она только тратит время.
        return best

    def _read_scales(self, g, harsh):
        import cv2

        best: tuple[str, float] = ('', -1.0)
        scales = self.scales_harsh if harsh else self.scales
        seen: list[tuple[str, float]] = []
        for i, k in enumerate(scales):
            big = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC) if k > 1.01 else g
            if harsh and self.blur_harsh:
                big = cv2.GaussianBlur(big, (3, 3), 0)
            r = self.ocr.read_line(big, lexicon=True)
            conf = float(r.get('conf', 0.0))
            seen.append((r['text'], conf))
            if conf > best[1]:
                best = (r['text'], conf)
            if not self.vote and i == 0 and conf >= self.sure:
                break
            # С голосованием читаем дальше, но не зря: если все масштабы уже
            # дали одно и то же слово в слово, следующий ничего не изменит.
            if self.vote and len(seen) >= 2 and len({t for t, _ in seen}) == 1:
                break
        if self.vote and len(seen) > 1:
            if PICK == 'score':
                text, conf = _score_pick(seen)
            else:
                text, conf = _vote_words(seen)
            if text:
                best = (text, max(conf, best[1]))
        return best


def colour_page(rgb: np.ndarray) -> bool:
    """Страница цветная (манхва) или чёрно-белая (типографская манга)?

    На цветных страницах буквы нарисованы от руки, и словарь нужен шире: там
    путаются не только метки, но и сами буквы (О↔С). Замер: починка по парам
    даёт на манхве 25,9 → 24,8 % и склеивает строки пузыря в одну реплику, а на
    типографской манге она же портит текст (11,0 → 11,8 %). Поэтому режим
    выбирается по странице, а не один на всё.
    """
    import cv2

    small = cv2.resize(rgb, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    sat = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)[:, :, 1]
    return float(np.mean(sat)) > 8.0


def read_page(det: PageDetector, reader, rgb: np.ndarray, minconf: float = 0.8):
    harsh = is_harsh_page(rgb)
    if hasattr(reader, 'ocr'):
        reader.ocr.REPAIR = 'marksmall' if colour_page(rgb) else 'marksdigits'
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
            if TIDY:
                text = tidy(text)
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


