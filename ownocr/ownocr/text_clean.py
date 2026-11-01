"""Чистка прочитанного: убрать крякозябры, не тронув настоящие слова.

Откуда они берутся. Модель на 519 классов знает латиницу и греческие буквы, модель
на 111 классов — украинские і/ї/є/ґ. Когда на кропе штриховка или обрезанный край,
чтец выдаёт «ііьг 7яА», «ПОСΛЕ ЗАВТРАКА POCETИT», «хbЮгО». Человеку это читать
нельзя, а странице это стоит ошибок в замере.

Правила ровно две группы:

1. **Похожие знаки → русские буквы.** Λ→Л, P→Р, O→О, і→и (на русской манге
   украинская «і» почти всегда недопрочитанная «и»). Это не выдумка: так же
   поступает человек, читая «POCETИT» как «ПОСЕТИТ».
2. **Мусор выбрасывается.** Слово уходит, если в нём перемешаны буквы и цифры,
   если нет ни одной гласной при длине ≥3, если внутри двойная Ё/Ъ/Ь/Й, или если
   больше трети знаков — не буквы.

Всё, что не подошло под правила, остаётся как есть: чистка не имеет права
«дописывать» за чтеца.
"""
from __future__ import annotations

import re

# Похожие начертания: латиница и греческий → кириллица
LOOKALIKE = {
    'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'K': 'К', 'M': 'М',
    'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х', 'Y': 'У',
    'a': 'а', 'c': 'с', 'e': 'е', 'o': 'о', 'p': 'р', 'x': 'х', 'y': 'у',
    'k': 'к', 'm': 'м', 't': 'т', 'h': 'н', 'b': 'ь',
    'Δ': 'Д', 'Β': 'В',
    'Λ': 'Л', 'Ο': 'О', 'Α': 'А', 'Ε': 'Ε' if False else 'Е', 'Ρ': 'Р', 'Τ': 'Τ', 'Κ': 'Κ',
    'Μ': 'М', 'Η': 'Н', 'Χ': 'Х', 'Ι': 'И', 'Ν': 'Н', 'Ζ': 'З', 'Υ': 'У',
    # украинские, которые на русской манге почти всегда недопрочитаны
    'і': 'и', 'ї': 'и', 'є': 'е', 'ґ': 'г', 'І': 'И', 'Ї': 'И', 'Є': 'Е', 'Ґ': 'Г',
}

# Цифры, которые на манге читаются как буквы: зеркальная «З» рисуется как «3»,
# «О» — как «0», «Ч» — как «4». Внутри слова (рядом с буквами) это ошибка
# чтеца, а не число; отдельное «5» в «5 ЙЕН» остаётся цифрой.
DIGIT_LOOKALIKE = {'3': 'З', '0': 'О', '4': 'Ч', '6': 'Б'}

VOWELS = set('АЕЁИОУЫЭЮЯ')
CONSONANTS = set('БВГДЖЗЙКЛМНПРСТФХЦЧШЩЬЪ')   # без гласных: О и др. сюда не входят
# латиница и греческий, для которых в LOOKALIKE нет пары: их присутствие в слове
# означает, что чтец не разобрал начертание
LATIN_ONLY = set('BDEFGIJLNQRSUVWZ')
EDGE = '.,!?…—«»"():;%'
ALLOWED_EXTRA = set(' .,!?…—-«»"():;0123456789')


def _fix_char(c: str) -> str:
    return LOOKALIKE.get(c, c)


def fix_digits(word: str) -> str:
    """Заменить цифры-двойники на буквы, но только ВНУТРИ слова.

    «3АСАДА» и «И3-ПОД» — это «ЗАСАДА» и «ИЗ-ПОД»; «5 ЙЕН» остаётся числом.
    """
    if not any(c.isdigit() for c in word) or not any(c.isalpha() for c in word):
        return word
    return ''.join(DIGIT_LOOKALIKE.get(c, c) for c in word)


def _word_ok(word: str, vocab: set[str] | None = None) -> tuple[bool, str]:
    """Слово после чистки: (оставить?, как выглядит).

    Если слово есть в словаре, оно остаётся при любой форме: правила ниже ловят
    обрывки штриховки, но настоящие слова с одним гласным («ЗДЕСЬ», «ВЗРЫВ»,
    «ТВОЙ») под них тоже попадали — и вылетали из реплики.
    """
    core = word.strip(EDGE)
    if not core:
        return False, ''
    core = fix_digits(core)
    letters = [c for c in core if c.isalpha()]
    digits = [c for c in core if c.isdigit()]
    if not letters and not digits:
        return False, ''
    if digits and not letters:
        return True, core                            # «5» — не мусор
    mixed = bool(letters) and bool(digits)          # «7яА», «САППО1»
    upper = core.upper()
    no_vowel = not (set(upper) & VOWELS)
    doubled = any(upper[i] == upper[i + 1] and upper[i] in 'ЁЪЬЙ' for i in range(len(upper) - 1))
    junk_share = sum(1 for c in core if not (c.isalpha() or c.isdigit())) / len(core)
    if mixed and len(letters) >= 2:          # цифра не опознана как буква
        return False, ''
    if junk_share > 0.34:
        return False, ''
    if no_vowel and len(core) >= 3:
        return False, ''
    if doubled:
        return False, ''
    # латиница осталась только там, где похожей кириллицы нет (j, q, w, z…) —
    # такое слово на русской странице не слово
    # осталась латиница или греческий, для которых нет похожей кириллицы
    # («хbЮгО», «ЮЧг») — такое слово на русской странице не читается
    if any(c in LATIN_ONLY for c in core):
        return False, ''
    # Перепутанный регистр — не повод выбрасывать слово: у чтеца приложения
    # латиница и кириллица идут вперемешку, и «ЛИ эТО» — это «ЛИ ЭТО», а не
    # мусор. Приводим к тому регистру, которого в слове больше.
    if not (core.isupper() or core.islower() or core.istitle()):
        upper_share = sum(1 for c in core if c.isupper()) / max(1, sum(1 for c in core if c.isalpha()))
        core = core.upper() if upper_share >= 0.6 else core.lower()
    # двойная гласная («ии»), три согласных подряд и слова без опоры на гласные —
    # это обрывки штриховки, а не слова
    if any(upper[i] == upper[i + 1] and upper[i] in VOWELS for i in range(len(upper) - 1)):
        return False, ''
    run = 0
    for c in upper:
        run = run + 1 if c in CONSONANTS else 0
        if run >= 5:            # «ПОЖАЛУЙСТА» и «СКИЙ» — законные скопления
            return False, ''
    if len(core) >= 4 and sum(1 for c in upper if c in VOWELS) <= 1 \
            and sum(1 for c in upper if c in CONSONANTS) >= 3:
        return (True, core) if (vocab and upper in vocab) else (False, '')
    return True, core


def dejunk(text: str, vocab: set[str] | None = None) -> str:
    """Убрать крякозябры из прочитанной строки. Пустая строка — нормальный ответ."""
    if not text:
        return ''
    text = ''.join(_fix_char(c) for c in text)
    out = []
    for word in text.split():
        ok, core = _word_ok(word, vocab)
        if not (ok and core):
            continue
        # знаки по краям слова сохраняем: «ДА,» не должно стать «ДА»
        lead = word[:len(word) - len(word.lstrip(EDGE))]
        trail = word[len(word.rstrip(EDGE)):]
        out.append(lead + core + trail)
    line = ' '.join(out)
    # пробелы перед знаками и после дефиса — обычная беда OCR
    line = re.sub(r'\s+([,.!?…])', r'\1', line)
    line = re.sub(r'([,.!?…]){2,}', r'\1', line)
    # знак в начале строки — это принятая за букву точка/запятая в кропе,
    # а не пунктуация: «,ПОСЛЗЕ» → «ПОСЛЗЕ»
    line = line.lstrip('.,!?…-')
    return line.strip()


def is_garbage(line: str, vocab: set[str] | None = None) -> bool:
    """Строка — мусор целиком (ни одного слова, похожего на слово)."""
    words = [w for w in line.split() if len(w.strip(EDGE)) >= 2]
    if not words:
        return True
    if vocab:
        known = sum(1 for w in words if w.strip(EDGE).upper() in vocab)
        if known == 0 and len(words) <= 2:
            return True
    return False


def plausible(line: str, vocab: set[str] | None = None) -> bool:
    """Есть ли в строке хоть одно слово, похожее на русское.

    Нужно как последний фильтр: после чистки иногда остаётся «хьЮгО» — по форме
    не придраться, а слова нет. Строка без единого словарного слова и без слова
    правдоподобной формы — это мусор, а не реплика.
    """
    for raw in line.split():
        w = raw.strip(EDGE)
        if len(w) < 2:
            continue
        up = w.upper()
        if vocab and up in vocab:
            return True
        vowels = sum(1 for c in up if c in VOWELS)
        if len(w) >= 3 and vowels >= 2:
            return True
    return False
