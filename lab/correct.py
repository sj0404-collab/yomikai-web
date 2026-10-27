"""Послемодельная коррекция слов: словарь + правдоподобие буквосочетаний.

Модель распознавания путает похожие буквы: «ПОШЕВЕАИТЬСЯ» вместо
«ПОШЕВЕЛИТЬСЯ», «СЮОДА» вместо «СЮДА», «ИУВСТВУЮ» вместо «ЧУВСТВУЮ»,
«ВЕСЕАО» вместо «ВЕСЕЛО», «ТРУ» вместо «ТРИ». Это не лечится ни масштабом, ни
предобработкой — только языковой моделью.

Важно не перестараться: имена («ХАНЫ», «ХАНОЙ») в словаре отсутствуют, и
наивная «починка по расстоянию» превращала «ХАНЫ» в «РАНЫ». Поэтому правим
слово, только если:

  * его нет в словаре, И
  * его правдоподобие (по триграммам частотного словаря) заметно хуже, чем у
    кандидата: правка должна давать выигрыш не меньше DELTA.

Так «ПОШЕВЕАИТЬСЯ» правится (триграмма «еаи» в языке не встречается), а
«ХАНЫ» остаётся как есть: все его триграммы обычные.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
ALPHABET = "абвгдежзийклмнопрстуфхцчшщъыьэюяё"
DELTA = 6.0             # насколько правдоподобие должно вырасти
TWO_EDITS_MIN = 6
SPLIT_MIN = 6
SPLIT_DELTA = 8.0
KNOWN_RANK = 300_000    # слово реже этого в частотном списке считаем незнакомым:
                        # полный список содержит и склейки-опечатки («эташтука»),
                        # и по ним нельзя решать, что слово настоящее
COMMON_RANK = 100_000   # слово-замена должно встречаться в языке заметно часто
BIG_GAIN = 15.0         # или выигрыш по правдоподобию должен быть очень большим

_WORD = re.compile(r"[А-Яа-яЁё]+")


def load_known(path: Path) -> set[str]:
    """Чистый список частых слов (ru_50k) — по нему решаем, «слово уже верное»."""
    words: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isalpha():
            words.add(parts[0].lower().replace("ё", "е"))
    return words


def load_dictionary(path: Path | None = None) -> dict[str, int]:
    """Частотный словарь: ru_full.txt (1,4 млн слов) → ru_250k.txt → ru_50k.txt.

    Полный список нужен потому, что в 50 тысячах нет многих обычных слов:
    «сосредоточить» там отсутствует, и строка «СОСРЕДОТОУИТЬ» оставалась с
    ошибкой. Для приложения словарь придётся урезать — 28 МБ в APK не влезут.
    """
    if path is None:
        for name in ("ru_full.txt", "ru_250k.txt", "ru_50k.txt"):
            path = ROOT / name
            if path.exists():
                break
    words: dict[str, int] = {}
    for rank, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        parts = line.split()
        if len(parts) != 2:
            continue
        word = parts[0].lower().replace("ё", "е")
        if word.isalpha():
            words.setdefault(word, rank)
    return words


DICT = load_dictionary()
# Чистый частотный список: полный список (ru_full) содержит и опечатки-склейки,
# поэтому «слово уже верное» проверяем по нему, а варианты замены ищем в DICT.
KNOWN = load_known(ROOT / "ru_50k.txt") if (ROOT / "ru_50k.txt").exists() else set(DICT)

# Триграммы, взвешенные частотой слова: по ним видно, бывает ли такое
# буквосочетание в русском вообще.
_TRIGRAM: dict[str, float] = {}
for _word, _rank in DICT.items():
    _weight = 1.0 / (1.0 + _rank)
    _padded = f"#{_word}#"
    for _i in range(len(_padded) - 2):
        _gram = _padded[_i:_i + 3]
        _TRIGRAM[_gram] = _TRIGRAM.get(_gram, 0.0) + _weight
_TOTAL = sum(_TRIGRAM.values()) or 1.0
_FLOOR = math.log(1e-4)


def plausibility(word: str) -> float:
    padded = f"#{word}#"
    score = 0.0
    for i in range(len(padded) - 2):
        gram = padded[i:i + 3]
        score += math.log(max(_TRIGRAM.get(gram, 0.0), 1e-4) / _TOTAL) - _FLOOR
    return score


def _edits1(word: str):
    for i in range(len(word) + 1):
        left, right = word[:i], word[i:]
        if right:
            yield left + right[1:]
        if len(right) > 1:
            yield left + right[1] + right[0] + right[2:]
        for ch in ALPHABET:
            if right:
                yield left + ch + right[1:]
            yield left + ch + right


def _known_edits1(word: str):
    for candidate in _edits1(word):
        if candidate in DICT:
            yield candidate


def _match_case(source: str, target: str) -> str:
    if source.isupper():
        return target.upper()
    if source[:1].isupper():
        return target[:1].upper() + target[1:]
    return target


def correct_word(word: str) -> str:
    if len(word) < 3:
        return word
    low = word.lower().replace("ё", "е")
    if low in KNOWN:
        return word
    base = plausibility(low)
    best: tuple[tuple[float, float], str] | None = None
    if len(low) >= SPLIT_MIN:
        # Слипшиеся слова проверяем ПЕРВЫМИ: выигрыш от разделения обычно больше,
        # чем от правки одной буквы, иначе «ИЗПОКОЛЕНИЯ» чинилось во что-то
        # постороннее одной заменой.
        for cut in range(2, len(low) - 1):
            first, second_word = low[:cut], low[cut:]
            if first in KNOWN and second_word in KNOWN:
                gain = plausibility(first) + plausibility(second_word) - base
                key = (-(DICT[first] + DICT[second_word]), gain)
                # Порог 6 (а не 8): «ЭТАШТУКА» даёт выигрыш 7.6 — оба куска
                # очень частые, а склейка в языке не встречается.
                if (gain > SPLIT_DELTA or (gain > 6.0 and DICT[first] < 20000
                                           and DICT[second_word] < 20000)) \
                        and (best is None or key > best[0]):
                    best = (key, first + " " + second_word)
        if best is not None:
            return _match_case(word, best[1])
    for candidate in _known_edits1(low):
        gain = plausibility(candidate) - base
        rank = DICT[candidate]
        # Правим, если правка заметно улучшает правдоподобие ИЛИ если кандидат
        # входит в самую частотную сотню-четыре сотни слов языка: «ТРУ» → «ТРИ»
        # правдоподобие почти не меняет, но «три» — одно из самых частых слов,
        # а «тру» в языке нет вовсе.
        # Из прошедших правило берём самое ЧАСТОЕ слово, а не самое
        # правдоподобное: «ТРВ» одинаково правдоподобно чинится в «ТОВ» и
        # «ТРИ», но «три» в сотни раз чаще.
        # Обычную ошибку берём, только если слово-замена само по себе частое
        # (иначе «ДРЕГЕР» превращался в «ПРЕВЕР»); редкие, но очень
        # правдоподобные замены принимаем по большому выигрышу.
        if (gain > DELTA and rank < COMMON_RANK) or gain > BIG_GAIN or rank < 400:
            key = (-rank, gain)
            if best is None or key > best[0]:
                best = (key, candidate)
    if best is None and len(low) >= TWO_EDITS_MIN:
        second = set()
        for one in _known_edits1(low):
            second.update(_known_edits1(one))
        for candidate in second:
            gain = plausibility(candidate) - base
            key = (-DICT[candidate], gain)
            if gain > BIG_GAIN and DICT[candidate] < COMMON_RANK and (best is None or key > best[0]):
                best = (key, candidate)
    if best is None and len(low) >= SPLIT_MIN:
        # слипшиеся слова: «ЭТАШТУКА» → «ЭТА ШТУКА»
        for cut in range(2, len(low) - 1):
            first, second_word = low[:cut], low[cut:]
            if first in KNOWN and second_word in KNOWN:
                gain = plausibility(first) + plausibility(second_word) - base
                key = (-(DICT[first] + DICT[second_word]), gain)
                # Порог 6 (а не 8): «ЭТАШТУКА» даёт выигрыш 7.6 — оба куска
                # очень частые, а склейка в языке не встречается.
                if (gain > SPLIT_DELTA or (gain > 6.0 and DICT[first] < 20000
                                           and DICT[second_word] < 20000)) \
                        and (best is None or key > best[0]):
                    best = (key, first + " " + second_word)
    if best is None:
        return word
    return _match_case(word, best[1])


# Частицы, которые в русском всегда пишутся через дефис. Модель часто «съедает»
# дефис («ЧТОТО», «КАКОЕНИБУДЬ»), и слово перестаёт быть словом.
_TAILS = ("нибудь", "либо", "то")
_HEAD = {"что", "кто", "где", "когда", "куда", "откуда", "почему", "отчего",
         "зачем", "как", "какой", "какая", "какое", "какие", "каков", "какова",
         "чей", "чья", "чьё", "чьи", "сколько", "чем", "кому", "кого", "кем"}


def restore_hyphens(text: str) -> str:
    """«ЧТОТО» → «ЧТО-ТО», «КАКОЕНИБУДЬ» → «КАКОЕ-НИБУДЬ», «ГДЕТО» → «ГДЕ-ТО»."""
    def fix(match: re.Match) -> str:
        word = match.group(0)
        low = word.lower()
        if "-" in word or len(low) < 5:
            return word
        for tail in _TAILS:
            if not low.endswith(tail):
                continue
            head = low[: -len(tail)]
            # Частотный список сам содержит склейки («чтото»), поэтому на
            # словарь здесь не опираемся — только на закрытый список основ.
            if head not in _HEAD:
                continue
            return word[: len(head)] + "-" + word[len(head):]
        return word
    return _WORD.sub(fix, text)


def balance_quotes(text: str) -> str:
    """Нечётное число кавычек — реплика обрезана краем кадра: закрываем."""
    if text.count('"') % 2 == 1:
        return text.rstrip() + '"'
    return text


def repair_split_words(text: str) -> str:
    """Склеивает слово, разорванное на две строки бокса: «РАССЧИ ТВВАЮ».

    Детектор режет облачко по проекции, и одно слово может оказаться в двух
    кусках. Соединяем соседние незнакомые слова, если склейка чинится в
    настоящее слово словаря.
    """
    words = text.split(" ")
    out: list[str] = []
    i = 0
    while i < len(words):
        if i + 1 < len(words):
            a, b = words[i], words[i + 1]
            la = a.strip(".,!?…—\"-").lower()
            lb = b.strip(".,!?…—\"-").lower()
            if la and lb and la not in KNOWN and lb not in KNOWN:
                merged = la + lb
                fixed = correct_word(merged).lower()
                if fixed != merged and " " not in fixed and fixed in KNOWN:
                    out.append(_match_case(a, fixed) if a.isupper() else fixed.title()
                               + b[len(b.rstrip(".,!?…—\"-")):])
                    i += 2
                    continue
        out.append(words[i])
        i += 1
    return " ".join(out)


def correct_line(text: str) -> str:
    fixed = _WORD.sub(lambda m: correct_word(m.group(0)), text)
    return balance_quotes(restore_hyphens(repair_split_words(fixed)))


if __name__ == "__main__":
    for sample in sys.argv[1:]:
        print(f"{sample}\n   → {correct_line(sample)}")
