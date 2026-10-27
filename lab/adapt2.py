"""Адаптивность на уровне фрагмента: каждый кусок текста читается двумя
проходами, для каждого берётся более уверенное чтение.

  проход A — ×2, вход детектора 1600 (плотный текст);
  проход B — ×1, вход детектора 960  (мелкий и белый текст).

Фрагменты сопоставляются по геометрии: бокс B считается тем же куском текста,
если он перекрывает бокс A больше чем наполовину (по площади меньшего бокса).
Выбор чтения — по уверенности модели с поправкой на длину: уверенное короткое
чтение не должно выигрывать у чуть менее уверенного полного.
"""
from __future__ import annotations

from pathlib import Path

import experiment as E
import pipeline as P

PASSES = {"A": dict(scale=2.0, side=1600), "B": dict(scale=1.0, side=960)}


def run_pass(models, page: Path, scale: float, side: int):
    img = E.load(page, scale, False)
    boxes = E.detect_with(models, img, side, False)
    return E.recognize(models, img, boxes, "projection", 0.25)


def cover(a: P.Region, b: P.Region) -> float:
    """Доля меньшего бокса, накрытая пересечением."""
    x1, y1 = max(a.left, b.left), max(a.top, b.top)
    x2, y2 = min(a.right, b.right), min(a.bottom, b.bottom)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    small = min((a.right - a.left) * (a.bottom - a.top),
                (b.right - b.left) * (b.bottom - b.top))
    return inter / small if small > 0 else 0.0


def value(region: P.Region) -> float:
    letters = sum(c.isalnum() for c in region.text)
    return region.score * (1 + 0.05 * min(letters, 40))


def fuse(a_regions, b_regions):
    """Один к одному: каждый фрагмент B достаётся не больше чем одному A.

    Раньше один и тот же фрагмент B мог «прилипнуть» к нескольким A, и текст
    размножался («ПОЖАЛУЙСТА… С ХАНОЙ С ХАНОЙ»).
    """
    pairs = []
    for i, a in enumerate(a_regions):
        for j, b in enumerate(b_regions):
            c = cover(a, b)
            if c >= 0.5:
                pairs.append((c, i, j))
    pairs.sort(reverse=True)
    used_a, used_b, choice = set(), set(), {}
    for c, i, j in pairs:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        choice[i] = b_regions[j] if value(b_regions[j]) > value(a_regions[i]) else a_regions[i]
    # Фрагменты B, никак не связанные с A, НЕ добавляем: на всех проверенных
    # страницах каждый фрагмент B перекрывал какой-то фрагмент A (детектор
    # находит те же места), а добавление давало размножение текста — «ПОЧЕМУ
    # ПОЧЕМУ», «СЕБЯ, СЕБЯ», «С ХАНОЙ С ХАНОЙ».
    return [choice[i] if i in choice else a for i, a in enumerate(a_regions)]


def adaptive(models, page: Path):
    a = run_pass(models, page, **PASSES["A"])
    b = run_pass(models, page, **PASSES["B"])
    return fuse(a, b)


if __name__ == "__main__":
    import sys
    models = P.Models()
    pages = [Path(p) for p in sys.argv[1:]] or sorted(Path("pages").glob("*.jpg"))
    for page in pages:
        lines = P.reading_order(adaptive(models, page), True)
        print(f"=== {page.name}: реплик {len(lines)}")
        for line in lines:
            print("   ", line.text)
