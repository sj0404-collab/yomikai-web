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

from .text_clean import dejunk, plausible
from .crew import Foreman, Proposal, WEIGHTS
from .engine import OwnOCR
from .det_tune import tune as tune_lines
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


VOWELS = set('АЕЁИОУЫЭЮЯ')

# Накладки самого приложения-читалки, которые попадают в скриншот: «Справа
# налево», «Загрузка», счётчик страниц и т.п. Это не реплики страницы, и в
# приёмке их быть не должно. Список намеренно узкий: только служебные слова.
UI_WORDS = {'СПРАВА', 'НАЛЕВО', 'СЛЕВА', 'НАПРАВО', 'ЗАГРУЗКА', 'СКАЧАТЬ',
            'ПОВТОРИТЬ', 'ОШИБКА', 'СТРАНИЦА', 'ПРОКРУТКА', 'МЕНЮ', 'OCR'}
UI_BIGRAMS = {'СПРАВА НАЛЕВО', 'СЛЕВА НАПРАВО', 'ОШИБКА OCR'}


def is_junk_word(word: str) -> bool:
    """Контролёр: «слово» из обрывка штриховки, которого в русском быть не может."""
    core = word.strip('.,!?…—«»"():;%').upper()
    if not core or any(ch.isdigit() for ch in core):
        return False
    if core in VOCAB:
        return False
    doubled = any(core[i] == core[i + 1] and core[i] in 'ЁЪЬЙ' for i in range(len(core) - 1))
    no_vowel = not (set(core) & VOWELS)
    return doubled or (no_vowel and len(core) >= 2)


def junk_words(text: str) -> str:
    """Выбросить «ЮЁЁЩ»: буквы есть, слова нет.

    Признаки мусора: не словарное, короткое, и либо внутри двойная одна и та же
    буква («ЁЁ»), либо нет гласных вовсе, либо букв меньше трёх. Настоящие
    имена собственные (ХАНОЙ, ХАНЫ) так не отсекаются: в них есть гласные.
    """
    out = []
    for word in text.split():
        core = word.strip('.,!?…—«»"():;%').upper()
        if not core:
            continue
        if any(ch.isdigit() for ch in core):
            out.append(word)          # цифры не мусор: «5 ЙЕН ПОДОЙДЕТ…»
            continue
        doubled = any(core[i] == core[i + 1] and core[i] in 'ЁЪЬЙ' for i in range(len(core) - 1))
        no_vowel = not (set(core) & VOWELS)
        # одна буква — ещё не мусор: «Я», «В», «К», «С» настоящие слова
        if core not in VOCAB and (doubled or (no_vowel and len(core) >= 2)):
            continue
        out.append(word)
    return ' '.join(out)


def known_words(text: str) -> int:
    """Сколько слов реплики есть в словаре (25 000 частых русских слов)."""
    words = [w.strip('.,!?…—«»"():;%') for w in text.upper().replace('-', ' ').split()]
    return sum(1 for w in words if len(w) >= 3 and w in VOCAB)


def levenshtein(a: str, b: str) -> int:
    """Расстояние правки: сколько букв испорчено в строке."""
    a, b = clean(a), clean(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


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
CREW = os.environ.get('OWNOCR_CREW', '1') == '1'
RESCUE = os.environ.get('OWNOCR_RESCUE', '1') == '1'
ESLAV_STRETCH = float(os.environ.get('OWNOCR_ESLAV_STRETCH', '1.1'))
ESLAV_WIDE = int(os.environ.get('OWNOCR_ESLAV_WIDE', '160'))
ESLAV_CONF = float(os.environ.get('OWNOCR_ESLAV_CONF', '0.6'))
OTSU = os.environ.get('OWNOCR_OTSU', '0') == '1'
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


class CtcLineReader:
    """Работник «эслав»: строчный CTC-распознаватель, дообученный на нашем домене.

    Читает кроп целиком как строку (1×32×W), поэтому его ошибки не похожи на
    ошибки посимвольного ученика: он видит слово целиком и не рвёт его на
    отдельные пятна. В бригаде отвечает за слова, где ученик путает буквы.
    """

    def __init__(self, path: str):
        import onnxruntime as ort
        from . import eslav as E
        self.E = E
        self.sess = ort.InferenceSession(path, providers=['CPUExecutionProvider'])
        self.name = self.sess.get_inputs()[0].name

    def read(self, gray: np.ndarray, stretch: float = 1.0) -> tuple[str, float]:
        x = self.E.prepare(gray)
        if abs(stretch - 1.0) > 1e-3:
            import cv2
            w = max(8, int(round(x.shape[-1] * stretch)))
            img = (x[0, 0] + 1.0) * 127.5
            img = cv2.resize(img, (w, x.shape[2]), interpolation=cv2.INTER_LINEAR)
            x = (img / 127.5 - 1.0)[None, None].astype('float32')
        out = np.asarray(self.sess.run(None, {self.name: x})[0]).reshape(-1, self.E.NUM_CLASSES)
        # уверенность: средняя вероятность выбранных классов (без «пусто»)
        mx = out.max(axis=1)
        idx = out.argmax(axis=1)
        keep = idx != self.E.BLANK
        conf = float(np.exp(np.log(np.clip(np.exp(mx[keep]), 1e-6, 1.0))).mean()) if keep.any() else 0.0
        return self.E.decode_logits(out), float(np.clip(conf, 0.0, 1.0))


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
        self.scales_rescue = tuple(float(x) for x in
                                   os.environ.get('OWNOCR_RESCUE_SCALES', '4,5').split(','))
        env_harsh = os.environ.get('OWNOCR_HARSH')
        if env_harsh:
            scales_harsh = tuple(float(x) for x in env_harsh.split(','))
        self.scales_harsh = tuple(scales_harsh)
        self.blur_harsh = (os.environ.get('OWNOCR_HARSH_BLUR', '0') == '1') or blur_harsh
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
        # Бригада: у каждого работника своя зона ответственности, бригадир
        # сводит голоса пословно (см. ownocr/crew.py). Редактор и контролёр —
        # те же функции, что уже отлажены в движке.
        # Работник «эслав» подключается, если есть дообученная модель.
        # Роли бригады. Реестр в ownocr/roles.py: добавить чтеца — одна запись,
        # голосование и веса уже умеют любое число работников.
        from . import roles as _roles
        self.roles = _roles.build(_roles.enabled(), ocr=self.ocr)
        self.foreman = Foreman(
            getattr(self.ocr, 'vocab', set()),
            fix=lambda w: self.ocr._fix_word(w) if hasattr(self.ocr, '_fix_word') else w,
            is_junk=lambda w: is_junk_word(w))


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
        # Языковой отбор: победитель голосования может быть мусором («ЮЁЁЩ» на
        # кропе «ВСЁ ЕЩЁ»), а другой работник — прав («BCЁ EЩE»). Тогда решает
        # язык, а не вес голоса.
        if best[0]:
            alt = self._language_fallback(best[0])
            if alt != best[0]:
                best = (alt, best[1])
        # Мастер-наставник: если ни один работник не дал ни одного словарного
        # слова, зовём его — он читает тот же кроп на нестандартных увеличениях
        # (×4, ×5) и с выровненным контрастом. Это не «ещё один масштаб всем»:
        # он включается только там, где бригада провалилась, и потому не
        # замедляет обычные строки.
        # На чёрно-белой странице крупные увеличения врут (бинаризация убивает
        # края), проверено: 21,6 → 23,7 %. Поэтому наставник туда не идёт.
        rescue = known_words(best[0]) == 0 and RESCUE and not harsh
        if rescue:
            R = self._read_rescue(g, harsh)
            # Наставник засчитывается только если его прочтение ЧИТАЕМО: доля
            # словарных слов не меньше половины. Иначе он вытаскивал служебную
            # надпись приложения («ОШИБКА OCR САППО1…») и выдавал её за реплику.
            words = [w for w in R[0].split() if w.strip(EDGE_PUNCT)]
            share = sum(1 for w in words if _word_ok(w)) / len(words) if words else 0.0
            if known_words(R[0]) > known_words(best[0]) and share >= 0.5:
                best = R
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

    def _language_fallback(self, text: str) -> str:
        """Если победитель голосования — мусор, взять того, чей текст читается.

        Пример с dense-b: на кропе «ВСЁ ЕЩЁ» ученик выдал «ЮЁЁЩ» и выиграл по
        весу, а приложение прочитало «BCE EЩE» — то есть верно. Такое же было с
        «НО...» (ученик: «НАД»). Язык тут единственный судья: берём первое по
        весу предложение, которое после чистки состоит из правдоподобных слов.
        """
        if not text or (plausible(dejunk(text), VOCAB) and dejunk(text)):
            return text
        for cand, weight, _conf in sorted(self._last_props, key=lambda p: -p[1]):
            fixed = dejunk(cand)
            if fixed and plausible(fixed, VOCAB):
                return cand
        return text

    def _read_rescue(self, g, harsh):
        """Мастер-наставник: нестандартные увеличения и выровненный контраст."""
        import cv2

        forms = [g]
        lo, hi = float(np.percentile(g, 5)), float(np.percentile(g, 95))
        if hi - lo >= 20:
            flat = np.clip((g.astype(np.float32) - lo) * 255.0 / (hi - lo), 0, 255)
            forms.append(flat.astype(np.uint8))
        props: list[Proposal] = []
        for fi, form in enumerate(forms):
            for k in self.scales_rescue:
                big = cv2.resize(form, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
                r = self.ocr.read_line(big, lexicon=True)
                props.append(Proposal('contrast' if fi else f'x{k:g}',
                                      WEIGHTS.get(f'x{k:g}', 0.8), r['text'],
                                      float(r.get('conf', 0.0))))
        text, conf = self.foreman.decide(props)
        return (text or '', conf)

    def _read_scales(self, g, harsh):
        import cv2

        best: tuple[str, float] = ('', -1.0)
        scales = self.scales_harsh if harsh else self.scales
        seen: list[tuple[str, float]] = []
        self._last_workers = []
        self._last_props = []
        for i, k in enumerate(scales):
            big = cv2.resize(g, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC) if k > 1.01 else g
            if harsh and self.blur_harsh:
                big = cv2.GaussianBlur(big, (3, 3), 0)
            forms = [big]
            if OTSU and i == 0:
                # второй вид того же кропа: жёсткое ч/б по Отсу. На рукописных
                # буквах со смазанным краем даёт другую сеть ошибок, и
                # голосование словом вытягивает верный вариант.
                forms.append(cv2.threshold(big, 0, 255,
                                           cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1])
            for fi, form in enumerate(forms):
                r = self.ocr.read_line(form, lexicon=True)
                conf = float(r.get('conf', 0.0))
                name = f'x{k:g}' if fi == 0 else ('otsu' if fi == 1 else 'contrast')
                self._last_workers.append(name)
                seen.append((r['text'], conf))
                if conf > best[1]:
                    best = (r['text'], conf)
            if not self.vote and i == 0 and conf >= self.sure:
                break
            # С голосованием читаем дальше, но не зря: если все масштабы уже
            # дали одно и то же слово в слово, следующий ничего не изменит.
            if self.vote and len(seen) >= 2 and len({t for t, _ in seen}) == 1:
                break
        # Роли бригады: каждая — отдельный чтец со своим весом и зоной. Список
        # задаётся OWNOCR_ROLES («хоть 5, хоть 10»), по умолчанию те же две роли,
        # что работали раньше: эслав и он же на растянутой строке.
        for role in (self.roles if not harsh else []):
            try:
                for text, conf in role.emit(g):
                    if text.strip():
                        seen.append((text, conf))
                        self._last_workers.append(role.name)
            except Exception as exc:
                if os.environ.get('OWNOCR_ROLE_DEBUG'):
                    print(f'роль «{role.name}» упала: {exc}')
        if CREW and seen and not harsh:
            props = [Proposal(worker, WEIGHTS.get(worker, 0.9), text, conf)
                     for worker, (text, conf) in zip(self._last_workers, seen)]
            text, conf = self.foreman.decide(props)
            if text:
                best = (text, max(conf, best[1]))
            # Запоминаем ВСЕ предложения: если победитель окажется мусором, есть
            # из чего выбрать (см. `_language_fallback`).
            self._last_props = [(p.text, p.weight, p.conf) for p in props]
        elif self.vote and len(seen) > 1:
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


# Поля вокруг строки. Проверял два подхода:
#   * ровный отступ 8 % высоты — ЛОМАЕТ чтение: dense-a 0,9 → 40,8 % (чтецы
#     обучены на плотных кропах, и белое поле сбивает нормировку);
#   * расширять только там, где буква реально касается края кропа, — то, что
#     нужно: обрезанный край («О» без бока, «Ш» без зубцов) чинится, остальные
#     кропы не меняются вовсе.
STEP = int(os.environ.get('OWNOCR_PAD_STEP', '3'))      # сколько добавлять за раз
TRIES = int(os.environ.get('OWNOCR_PAD_TRIES', '3'))    # до 9 px в каждую сторону
PAD_MODE = os.environ.get('OWNOCR_PAD', 'off')   # по умолчанию — как настроено чтение        # edges | off | frac
DEJUNK = os.environ.get('OWNOCR_DEJUNK', '1') == '1'
DET_TUNE = os.environ.get('OWNOCR_DET_TUNE_ON', '1') == '1'
DEBUG_LINES = os.environ.get('OWNOCR_DEBUG_LINES', '0') == '1'
PAD_FRAC = float(os.environ.get('OWNOCR_PAD_FRAC', '0.0'))


def _ink_on_edge(sub: np.ndarray, side: str, thr: int = 170) -> bool:
    """Касаются ли чернила края картинки."""
    if sub.size == 0:
        return False
    g = sub if sub.ndim == 2 else cv2.cvtColor(sub, cv2.COLOR_RGB2GRAY)
    if side == 'top':
        line = g[0, :]
    elif side == 'bottom':
        line = g[-1, :]
    elif side == 'left':
        line = g[:, 0]
    else:
        line = g[:, -1]
    return bool((line < thr).any())


MIN_CROP_H = int(os.environ.get('OWNOCR_MIN_CROP_H', '7'))


def crop_ok(crop: np.ndarray) -> tuple[bool, str]:
    """Годен ли кроп для чтения. Битый кроп — источник крякозябр, его лучше пропустить.

    Что считается поломкой: кроп ниже 7 px (буквы не различить), уже 4 px, почти
    целиком чёрный или целиком белый (нет текста, только фон или плашка), или
    вытянутый в 20 раз (это линия рамки, а не строка).
    """
    if crop.size == 0:
        return False, 'пусто'
    h, w = crop.shape[:2]
    if h < MIN_CROP_H:
        return False, 'низкий'
    if w < 4:
        return False, 'узкий'
    if w / float(h) > 20:
        return False, 'линия'
    g = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    ink = float((g < 140).mean())
    if ink < 0.01:
        return False, 'нет чернил'
    if ink > 0.92:
        return False, 'залито'
    return True, ''


def _padded(rgb: np.ndarray, x0: int, y0: int, x1: int, y1: int, frac: float = None):
    """Кроп строки, дотянутый там, где текст упёрся в край.

    Возвращает (кроп, x0, y0, x1, y1) — координаты уже расширенные, чтобы рамка
    в отчёте совпадала с тем, что читали.
    """
    H, W = rgb.shape[:2]
    frac = PAD_FRAC if frac is None else frac
    if PAD_MODE == 'frac':
        h = max(1, y1 - y0)
        pad = max(0, int(round(h * frac)))
        nx0, ny0 = max(0, x0 - pad), max(0, y0 - pad)
        nx1, ny1 = min(W, x1 + pad), min(H, y1 + pad)
        return rgb[ny0:ny1, nx0:nx1], nx0, ny0, nx1, ny1
    if PAD_MODE == 'off':
        return rgb[y0:y1, x0:x1], x0, y0, x1, y1
    # edges: тянем только те стороны, где чернила касаются края
    nx0, ny0, nx1, ny1 = x0, y0, x1, y1
    for _ in range(max(1, TRIES)):
        touched = False
        sub = rgb[ny0:ny1, nx0:nx1]
        if ny0 > 0 and _ink_on_edge(sub, 'top'):
            ny0 = max(0, ny0 - STEP)
            touched = True
        sub = rgb[ny0:ny1, nx0:nx1]
        if ny1 < H and _ink_on_edge(sub, 'bottom'):
            ny1 = min(H, ny1 + STEP)
            touched = True
        sub = rgb[ny0:ny1, nx0:nx1]
        if nx0 > 0 and _ink_on_edge(sub, 'left'):
            nx0 = max(0, nx0 - STEP)
            touched = True
        sub = rgb[ny0:ny1, nx0:nx1]
        if nx1 < W and _ink_on_edge(sub, 'right'):
            nx1 = min(W, nx1 + STEP)
            touched = True
        if not touched:
            break
    return rgb[ny0:ny1, nx0:nx1], nx0, ny0, nx1, ny1


def read_page(det: PageDetector, reader, rgb: np.ndarray, minconf: float = 0.8):
    harsh = is_harsh_page(rgb)
    rgb = normalize_page(rgb)
    if hasattr(reader, 'ocr'):
        # Цвет определяем ПОСЛЕ приведения полярности: у перевёрнутой страницы
        # насыщенность считается от инвертированных пикселей и выходит завышенной
        # (на dense-a инверсия получала «рукописный» режим и теряла починку цифр:
        # Р5ИОМ, УТОДН2). После нормализации цвет и инверсия дают одно и то же.
        reader.ocr.REPAIR = 'marksmall' if colour_page(rgb) else 'marksdigits'
    gray = np.array(Image.fromarray(rgb).convert('L'))
    H, W = gray.shape
    t0 = time.time()
    boxes = det.detect_page(rgb)
    n_boxes = len(boxes)
    regions, n_lines, broken = [], 0, 0
    # Все строки страницы собираем сразу и дочищаем вместе: детектор отдаёт
    # одну и ту же строку по два-три раза (precision 80 % против 97,6 % после
    # снятия дублей), а дубли внутри одной страницы видно только на всей пачке.
    all_lines = []
    for box in boxes[:400]:
        all_lines.extend(text_lines(rgb, box))
    if DET_TUNE:
        all_lines = tune_lines(rgb, all_lines)
    for (x0, y0, x1, y1) in all_lines:
        n_lines += 1
        # Поля вокруг строки. Бокс приходит обрезанным по чернилам, и на
        # тонких штрихах сглаженный край буквы срезался: «О» теряла бок,
        # «Ш» — зубцы. Отступ добавляется ТОЛЬКО там, где буква касается
        # края (см. `_padded`); ровные 8 % высоты чтение ломают.
        crop, x0, y0, x1, y1 = _padded(rgb, x0, y0, x1, y1)
        ok_crop, why = crop_ok(crop)
        if not ok_crop:
            broken += 1
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
        ok = bool(text) and score >= minconf and alnum >= 2 and alnum / max(1, len(text)) >= 0.5
        if DEBUG_LINES:
            print(f'  строка y={y0:4d} x={x0:3d} {x1 - x0:3d}×{y1 - y0:2d} '
                  f'{text!r} уверенность {score:.2f} {"принята" if ok else "ОТБРОШЕНА"}')
        if ok:
            regions.append(Region(text, x0 / W, y0 / H, x1 / W, y1 / H, score))
    lines = [line for panel in split_panels(regions, True) for line in bubbles_of(panel, True)]
    # Отбраковка «неречи» на уровне собранной реплики, а не отдельных кусков:
    # если фильтровать куски, мусор с рисунка перестаёт склеивать облачка и одна
    # реплика рвётся на две. Реплика без единого словарного слова — это подпись
    # рисунка, водяной знак или штриховка, прочитанная как буквы.
    # Реплика проходит, если в ней есть словарное слово И их доля не меньше
    # 40 %. Второе условие отсекает служебные надписи приложения и подписи
    # картинок: «ОШИБКА ОСР САППО1 СОЕГСЕ УАТ ЧЕ ТО» — одно словарное слово из
    # семи, это не реплика.
    def _ui(text: str) -> bool:
        """Накладка приложения, а не речь страницы."""
        words = [w.strip('.,!?…—«»"():;%').upper() for w in text.split()]
        words = [w for w in words if w]
        if not words:
            return False
        if ' '.join(words) in UI_BIGRAMS:
            return True
        return all(w in UI_WORDS or w.isdigit() for w in words)

    def _readable(text: str) -> bool:
        # Считаем только слова от трёх букв: «ЧЕ» и «ТО» — словарные, но их
        # наличие не делает репликой служебную надпись «ОШИБКА ОСР САППО1…».
        words = [w.strip('.,!?…—«»"():;%') for w in text.split()]
        # «ЧТО-НИБУДЬ» — это два слова: без разбивки по дефису настоящая реплика
        # «ПЫТАЮТСЯ МНЕ ЧТО-ТО СКАЗАТЬ» недосчитывалась словарных слов и
        # выбрасывалась целиком.
        words = [part for w in words for part in w.split('-')]
        words = [w for w in words if len(w) >= 3]
        if not words:
            return bool(text.strip())
        known = sum(1 for w in words if _word_ok(w))
        share = known / len(words)
        # Либо два словарных слова (шумная, но настоящая реплика), либо одно и
        # оно покрывает половину строки («ЧТО?»). Служебная надпись приложения
        # даёт одно слово из пяти — отсекается.
        return known >= 2 or share >= 0.5

    kept = [line for line in lines if _readable(line.text) and not _ui(line.text)]
    # Правки на уровне готовой реплики: слова склеиваются из переносов
    # («РАССЧИ-» + «ТЬВАЮ»), и каждая половина по отдельности ни в какие
    # правила не попадает — только целое слово. Заодно убираем мусорные
    # «слова» из обрывков штриховки («ЮЁЁЩ»), которых в русском быть не может.
    dropped_junk = 0
    clean = []
    for line in kept:
        text = junk_words(line.text)
        if hasattr(reader, 'ocr'):
            text = reader.ocr._fix_common(text)
        # Редактор и склейка работают и на готовой реплике: слова, разорванные
        # переносом, лежат в РАЗНЫХ кропах («РАССЧ№» и «ТЬВАЮ»), и внутри кропа
        # их не соединить — только здесь, когда реплика собрана.
        if CREW and not harsh and getattr(reader, 'foreman', None) is not None:
            text = reader.foreman._polish(text)
        # Последним шагом — чистка крякозябр: латиница/греческий/украинские
        # буквы, перемешанный регистр, обрывки штриховки. После неё строка без
        # единого правдоподобного слова выбрасывается целиком.
        if DEJUNK:
            text = dejunk(text)
            if not text or not plausible(text, VOCAB):
                dropped_junk += 1
                continue
        line.text = text
        clean.append(line)
    kept = clean
    return {'replies': kept, 'dropped': len(lines) - len(kept), 'junk': dropped_junk,
            'broken_crops': broken,
            'boxes': n_boxes,
            'lines': n_lines, 'harsh': harsh, 'seconds': time.time() - t0}


