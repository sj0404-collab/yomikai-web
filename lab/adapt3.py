"""Адаптивные условия со страховкой: основной проход + добор потерянного.

Основной проход A — ×2, вход детектора 1600 (плотный текст; на нём лучший
результат на страницах 2 и 4). Страховочный проход B — ×1, вход 960 (мелкий и
белый текст; на нём находится «ЧТО?..» на странице 15, который A читает как
«4TO.» и выбрасывает фильтром языка).

Из страховочного прохода берутся ТОЛЬКО те куски, чьё место не покрыто ни одним
годным куском основного прохода. Тогда текст не размножается («ПОЧЕМУ ПОЧЕМУ»),
но потерянные реплики возвращаются.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

import experiment as E
import pipeline as P

PASSES = {"A": dict(scale=2.0, side=1600), "B": dict(scale=1.0, side=960)}
GRID = 400          # сетка покрытия: 400×400 по странице
COVER_MIN = 0.6     # кусок считается «уже прочитанным», если его место покрыто на 60 %
MIN_LETTERS = 3     # меньше трёх букв добирать бессмысленно
MIN_CLEAN = 0.6     # доля кириллицы в добранном куске


def usable(regions) -> list[P.Region]:
    """То же, что делает reading_order перед фильтром по языку."""
    out = []
    for r in regions:
        text = P.fix_lookalikes(P.clean_speech(r.text))
        if sum(c.isalnum() for c in text) < 2:
            continue
        if not P._is_cyrillic(text):
            continue
        out.append(P.Region(text, r.left, r.top, r.right, r.bottom, r.score))
    return out


def mask(regions) -> np.ndarray:
    m = np.zeros((GRID, GRID), dtype=bool)
    for r in regions:
        y1, y2 = int(r.top * GRID), max(int(r.top * GRID) + 1, int(r.bottom * GRID))
        x1, x2 = int(r.left * GRID), max(int(r.left * GRID) + 1, int(r.right * GRID))
        m[y1:y2, x1:x2] = True
    return m


def covered(region: P.Region, m: np.ndarray) -> float:
    y1, y2 = int(region.top * GRID), max(int(region.top * GRID) + 1, int(region.bottom * GRID))
    x1, x2 = int(region.left * GRID), max(int(region.left * GRID) + 1, int(region.right * GRID))
    patch = m[y1:y2, x1:x2]
    return float(patch.mean()) if patch.size else 0.0


def adaptive(models, page: Path, verbose=False):
    img_a = E.load(page, PASSES["A"]["scale"], False)
    a_all = E.recognize(models, img_a, E.detect_with(models, img_a, PASSES["A"]["side"], False), "projection", 0.25)
    img_b = E.load(page, PASSES["B"]["scale"], False)
    b_all = E.recognize(models, img_b, E.detect_with(models, img_b, PASSES["B"]["side"], False), "projection", 0.25)
    # Добор делается на уровне РЕПЛИК, а не отдельных кусков. Иначе из второго
    # прохода в текст попадали обрывки, налезающие на уже прочитанное
    # («со ПРЯМО» рядом с «ПРЯМО СЕЙЧАС»).
    lines_a = P.reading_order(a_all, True, correct=False)
    lines_b = P.reading_order(b_all, True, correct=False)

    def overlaps(x, y) -> float:
        ix = min(x.right, y.right) - max(x.left, y.left)
        iy = min(x.bottom, y.bottom) - max(x.top, y.top)
        if ix <= 0 or iy <= 0:
            return 0.0
        inter = ix * iy
        small = min((x.right - x.left) * (x.bottom - x.top),
                    (y.right - y.left) * (y.bottom - y.top))
        return inter / small if small > 0 else 0.0

    for line in lines_a + lines_b:
        line.text = P.normalize_case(P.correct_line(line.text))

    def cleanliness(text: str) -> float:
        """Качество строки ДО коррекции: буквы в словарных словах против прочих.

        Считаем буквы, а не слова: «ГОРА МИЯ С ПЛЕЧ» и «ГОРА УПАЛА С ПЛЕЧ» дают
        одинаковое число словарных слов, но второе явно лучше.
        """
        score = 0.0
        for raw in text.split():
            word = raw.strip(".,!?…—-").lower()
            if len(word) < 3:
                continue
            score += len(word) if word in P.DICT_WORDS else -len(word) * 0.5
        return score

    def has_real_word(text: str) -> bool:
        """Есть ли в строке ЧАСТОЕ русское слово (ранг < 20 000).

        Порог важен: «ито» формально лежит в частотном списке на 37-м месте с
        конца, и без порога мусорная строка считалась бы осмысленной.
        """
        for raw in text.split():
            word = raw.strip(".,!?…—-").lower()
            if len(word) >= 3 and P.DICT_WORDS.get(word, 10 ** 9) < 20_000:
                return True
        return False

    keep = []
    replace = []
    for line in lines_b:
        twins = [other for other in lines_a if overlaps(line, other) >= 0.1]
        if twins:
            # Заменяем только совсем нечитаемое: если у основного прохода в
            # этой реплике ни одного настоящего слова («ИТО»), а у
            # страховочного есть («ЧТО?») — берём страховочный. В остальных
            # случаях основной проход остаётся: у него крупнее масштаб.
            if has_real_word(line.text) and not any(has_real_word(t.text) for t in twins):
                replace.extend(twins)
                keep.append(line)
            continue
        if not (P.good_words(P.correct_line(line.text))
                or len(line.text.strip(" .,!?…—-")) <= 4):
            continue
        keep.append(line)
    def in_line(region, line) -> bool:
        return (line.left - 0.01 <= region.left <= line.right + 0.01
                and line.top - 0.01 <= region.top <= line.bottom + 0.01)

    dropped = [r for r in a_all if any(in_line(r, line) for line in replace)]
    kept_regions = [r for r in b_all if any(in_line(r, line) for line in keep)]
    if verbose:
        print(f"    A реплик {len(lines_a)}, B реплик {len(lines_b)}, "
              f"добрано {len(keep)}, заменено {len(replace)}: {[l.text for l in keep]}")
    return a_all, [r for r in a_all if r not in dropped] + kept_regions


def dedupe_text(lines):
    """Убирает удвоенные слова, которые появляются на стыке двух проходов."""
    for line in lines:
        words = line.text.split()
        out = []
        for word in words:
            if out and out[-1].lower().strip(".,!?…—-") == word.lower().strip(".,!?…—-"):
                continue
            if len(out) >= 2 and [w.lower() for w in out[-2:]] == [word.lower(), word.lower()]:
                continue
            out.append(word)
        line.text = " ".join(out)
    return lines


if __name__ == "__main__":
    import sys
    models = P.Models()
    pages = [Path(p) for p in sys.argv[1:]] or sorted(Path("pages").glob("*.jpg"))
    for page in pages:
        _, regions = adaptive(models, page, verbose=True)
        lines = dedupe_text(P.reading_order(regions, True))
        print(f"=== {page.name}: реплик {len(lines)}")
        for line in lines:
            print("   ", line.text)
