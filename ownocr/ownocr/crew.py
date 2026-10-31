"""Бригада чтения: у каждого работника своя зона ответственности и свой голос.

Зачем: сейчас решение за строку принимается одним правилом «выбрать целое
прочтение по словарной оценке». Это работает, но теряет знание о том, КТО из
работников что сказал: масштаб ×3 может ошибаться в одной букве и быть правым в
другой, а словарь — знать слово, которого не знает никто.

Кто за что отвечает:

    Глаза ×2 / ×2,5 / ×3 / ×3,5   — чтение одного и того же кропа в разном
                                    увеличении; дают РАЗНЫЕ ошибки на одном слове
    Осветитель                    — выравнивание контраста и жёсткое ч/б для
                                    бледных и рукописных букв
    Перевёртыш                    — белый текст на чёрной плашке (нарратив)
    Узнаватель                    — сама модель букв (внутри каждого «глаза»)
    Редактор                      — словарные правки: ё, Ь↔Ы, -ОИ→-ОЙ, хвосты
    Контролёр                     — выбрасывает «слова» из обрывков штриховки
    Бригадир                      — сводит голоса по КАЖДОМУ СЛОВУ отдельно,
                                    с весом работника и премией за словарное слово
    Прораб                        — порядок панелей, пузырей и строк в реплике

Правило бригадира: слово выбирается по сумме голосов (вес × уверенность),
словарное слово получает премию, незнакомое — штраф. Если работники дали разное
число слов, голосовать пословно не по чему: бригадир отдаёт решение тому, чьё
прочтение целиком набрало больше очков (прежнее поведение).
"""
from __future__ import annotations

import math
import os

VOWELS = set('АЕЁИОУЫЭЮЯ')


class Proposal:
    """Голос работника: что он прочитал и насколько уверен."""

    __slots__ = ('worker', 'weight', 'text', 'conf')

    def __init__(self, worker: str, weight: float, text: str, conf: float):
        self.worker, self.weight, self.text, self.conf = worker, weight, text, float(conf)

    def __repr__(self):
        return f'{self.worker}({self.weight:.2f})={self.text!r}@{self.conf:.2f}'


# веса работников: сколько доверия их голосу. Глаза ×2 — родной масштаб модели,
# ему верим больше; крупные масштабы полезны, но чаще «додумывают».
WEIGHTS = {'x2': 1.0, 'x2.5': 0.95, 'x3': 0.9, 'x3.5': 0.85, 'x4': 0.8, 'x5': 0.7,
           'contrast': 0.7, 'otsu': 0.6, 'flip': 0.9}


# Окончания русских слов. Нужны, потому что словарь — 25 000 начальных форм, и
# «ВКУСНОЙ» в нём нет, хотя «ВКУСНО» есть. Без этого редактор считал настоящее
# слово мусором и не мог исправить «ЕКУСНОЙ».
ENDINGS = ('ОГО', 'ЕГО', 'ОМУ', 'ЕМУ', 'ЫМИ', 'ИМИ', 'АМИ', 'ЯМИ', 'ЫХ', 'ИХ',
           'ОЙ', 'ЕЙ', 'ЫЙ', 'ИЙ', 'АЯ', 'ЯЯ', 'ОЕ', 'ЕЕ', 'ЫЕ', 'ИЕ', 'ОМ', 'ЕМ',
           'УЮ', 'ЮЮ', 'ОВ', 'ЕВ', 'АМ', 'ЯМ', 'АХ', 'ЯХ', 'ИЯ', 'ИЕ', 'ЬЮ',
           'А', 'Я', 'У', 'Ю', 'Е', 'И', 'Ы', 'О', 'Ь', 'Й')


def stem_ok(word: str, vocab) -> bool:
    """Слово похоже на настоящее: есть в словаре или основа+окончание в словаре."""
    if not word:
        return False
    if word in vocab:
        return True
    for end in ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 3:
            if word[:len(word) - len(end)] in vocab:
                return True
    return False


class Foreman:
    """Бригадир: решает, какое слово писать, по голосам работников."""

    def __init__(self, vocab, fix=None, is_junk=None, word_bonus: float = 1.5):
        self.vocab = vocab
        self.fix = fix                # редактор: callable(word) -> word
        self.is_junk = is_junk        # контролёр: callable(word) -> bool
        self.word_bonus = word_bonus

    # ── помощники ────────────────────────────────────────────────────────────
    @staticmethod
    def _tokens(text: str) -> list[str]:
        return [t for t in text.split(' ') if t]

    @staticmethod
    def _core(word: str) -> str:
        return word.strip('.,!?…—«»"():;%').upper()

    def _word_value(self, word: str) -> float:
        """Премия за словарное слово, штраф за незнакомое и за мусор."""
        core = self._core(word)
        if not core:
            return 0.0
        v = 0.0
        if stem_ok(core, self.vocab):
            v += self.word_bonus if core in self.vocab else 0.7 * self.word_bonus
        elif any(ch.isdigit() for ch in core):
            v -= 0.2
        else:
            v -= 0.5
        if self.is_junk and self.is_junk(word):
            v -= 2.0
        return v

    def _line_value(self, text: str, conf: float) -> float:
        words = self._tokens(text)
        if not words:
            return -9.0
        known = sum(1 for w in words if self._core(w) in self.vocab) / len(words)
        junk = sum(1 for ch in text if ch in '»«%"') / max(1, len(text))
        return known + 0.3 * conf - 2.0 * junk

    # ── решение ──────────────────────────────────────────────────────────────
    JOIN = True
    PAIRS = [('Е', 'В'), ('В', 'Е'), ('И', 'Й'), ('Й', 'И'), ('И', 'Ы'), ('Ы', 'И'),
             ('Ь', 'Ы'), ('Ы', 'Ь'), ('О', 'И'), ('И', 'О'), ('Т', 'П'), ('П', 'Т'),
             ('С', 'О'), ('О', 'С'), ('Ж', 'Х'), ('Х', 'Ж'), ('А', 'О'), ('О', 'А'),
             ('У', 'И'), ('И', 'У'), ('Л', 'И'), ('И', 'Л'), ('Н', 'И'), ('И', 'Н'),
             ('З', 'Э'), ('Э', 'З'), ('Ю', 'О'), ('О', 'Ю'), ('Ш', 'Щ'), ('Щ', 'Ш')]
    QUORUM = 2          # сколько работников должны сойтись на слове, чтобы его взять
    USE_CHECKER = True  # старший бригадир: сравнить с целым прочтением

    def decide(self, proposals: list[Proposal]) -> tuple[str, float]:
        live = [p for p in proposals if p.text and p.text.strip()]
        if os.environ.get('OWNOCR_DEBUG'):
            print('   голоса:', live)
        if not live:
            return '', -1.0
        if len(live) == 1:
            return self._polish(live[0].text), live[0].conf

        parts = [self._tokens(p.text) for p in live]
        same_len = len({len(p) for p in parts}) == 1

        if not same_len:
            # работники разошлись в числе слов — пословно голосовать не по чему
            best = max(live, key=lambda p: self._line_value(p.text, p.conf))
            return self._polish(best.text), best.conf

        out = []
        for pos in range(len(parts[0])):
            votes: dict[str, float] = {}
            confs: dict[str, float] = {}
            for prop, toks in zip(live, parts):
                word = toks[pos]
                votes[word] = votes.get(word, 0.0) + prop.weight * prop.conf
                confs.setdefault(word, prop.conf)
            # премия/штраф по словарю — отдельно от голосов
            for word in votes:
                votes[word] += 0.35 * self._word_value(word)
                fixed = self.fix(word) if self.fix else word
                if fixed != word:
                    votes[word] += 0.25 * self._word_value(fixed)
            # кворум: если слово поддержал только один работник, а у другого
            # есть словарное слово на этом месте — берём словарное
            top = max(votes.values())
            leaders = [w for w, v in votes.items() if v >= top - 1e-9]
            support = {w: sum(1 for p, t in zip(live, parts) if t[pos] == w)
                       for w in leaders}
            if len(leaders) > 1:
                leaders.sort(key=lambda w: (support[w], self._word_value(w)), reverse=True)
            elif support[leaders[0]] < self.QUORUM and len(live) >= self.QUORUM:
                alt = [w for w in votes if stem_ok(self._core(w), self.vocab)]
                if alt:
                    leaders = [max(alt, key=lambda w: votes[w])]
            out.append(leaders[0])

        merged = ' '.join(out)
        conf = max(p.conf for p in live)
        if self.USE_CHECKER:
            best_line = max(live, key=lambda p: self._line_value(p.text, p.conf))
            # старший бригадир: целое прочтение лучше, если в нём больше
            # словарных слов и не больше мусора; иначе оставляем сведённое
            if self._line_value(best_line.text, best_line.conf) > \
                    self._line_value(merged, conf) + 1e-6:
                return self._polish(best_line.text), best_line.conf
        return self._polish(merged), conf

    LETTERS = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ'

    def _repair_to_dict(self, word: str) -> str:
        """Редактор по словарю: одна замена в знакомых парах или одна вставка.

        «ЕКУСНОЙ» → «ВКУСНОЙ» (Е→В), «ХАНОИ» → «ХАНОЙ». Трогаем только те слова,
        которых в словаре нет: настоящее слово редактор не переписывает.
        """
        core = self._core(word)
        if not core or stem_ok(core, self.vocab) or len(core) < 3:
            return word
        pairs = self.PAIRS
        for i, ch in enumerate(core):
            for a, b in pairs:
                if ch == a:
                    cand = core[:i] + b + core[i + 1:]
                    if stem_ok(cand, self.vocab):
                        return cand
        # Вставки буквы здесь запрещены: перебор вставок превращал настоящие
        # слова в другие («С ХАНЫ» → «ОХРАНЫ», «БЫ И» → «БИБИ»). Разорванные
        # переносом слова склеивает отдельный работник ниже.
        return word

    def _join_broken(self, words: list[str]) -> list[str]:
        """Склейка слов, разорванных переносом: «РАССЧ» + «ТЬВАЮ».

        Пробуем соединить пару соседних слов и довести соединение до словарного
        слова одной вставкой и одной заменой в знакомых парах. Это ровно то, что
        делает человек: видит «РАССЧ» и «ТЬВАЮ» и понимает, что это
        «РАССЧИТЫВАЮ».
        """
        out: list[str] = []
        i = 0
        while i < len(words):
            if i + 1 < len(words):
                # срезаем мусорный хвост обрывка: «РАССЧ№» → «РАССЧ». Именно
                # из-за «№» склейка не срабатывала, и выходило «РАССЧ ТЬВАЮ».
                a = self._core(words[i]).rstrip('№%»«"()[]{}|/\\~^`*+=<>.,!?…—:;')
                b = self._core(words[i + 1]).lstrip('№%»«"()[]{}|/\\~^`*+=<>.,!?…—:;')
                if a and b and not stem_ok(a, self.vocab) and not stem_ok(b, self.vocab) \
                        and not any(ch.isdigit() for ch in a + b):
                    merged = self._merge_to_dict(a, b)
                    if merged:
                        out.append(merged)
                        i += 2
                        continue
            out.append(words[i])
            i += 1
        return out

    def _merge_to_dict(self, a: str, b: str) -> str | None:
        base = a + b
        if base in self.vocab:
            return base
        for pos in range(len(base) + 1):
            for ch in self.LETTERS:
                probe = base[:pos] + ch + base[pos:]
                if probe in self.vocab:
                    return probe
                for k in range(len(probe)):
                    for x, y in self.PAIRS:
                        if probe[k] == x:
                            cand = probe[:k] + y + probe[k + 1:]
                            if cand in self.vocab:
                                return cand
        return None

    def _polish(self, text: str) -> str:
        """После бригадира: редактор по словарю и контролёр мусора."""
        words = self._tokens(text)
        out = []
        for w in words:
            if self.is_junk and self.is_junk(w):
                continue
            w = self.fix(w) if self.fix else w
            w = self._repair_to_dict(w)
            out.append(w)
        if self.JOIN:
            out = self._join_broken(out)
        return ' '.join(out)
