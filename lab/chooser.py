"""Адаптивные условия: какие настройки выбрать для конкретной страницы.

Лаборатория показала, что одних условий на всё нет:
  ×2 + детектор 1600 — выигрывают на плотном тексте (страница 2), но теряют
    мелкий белый текст (страница 15: пропадает «ЧТО?..»);
  ×1 + детектор 960  — наоборот, находит мелкое, но путает буквы в плотном.

Поэтому страница распознаётся двумя проходами, и выбирается тот, у которого
текст чище. Критерий не требует эталона и работает на любом языке:

  1) сколько реплик прочитано «чисто» (доля не-кириллических букв < 0.25);
  2) сколько всего букв и цифр прочитано;
  3) средняя уверенность модели.

  python3 lab/chooser.py [страницы...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import experiment as E
import pipeline as P

ROOT = Path(__file__).parent

PASSES = {
    "A": dict(scale=2.0, side=1600),   # плотный текст
    "B": dict(scale=1.0, side=960),    # мелкий и белый текст
}


def russian(ch: str) -> bool:
    low = ch.lower()
    return "а" <= low <= "я" or low == "ё"


def run_pass(models, page: Path, scale: float, side: int):
    img = E.load(page, scale, False)
    boxes = E.detect_with(models, img, side, False)
    regions = E.recognize(models, img, boxes, "projection", 0.25)
    return regions, P.reading_order(regions, True)


def line_cleanliness(text: str) -> float:
    letters = [c for c in text if c.isalnum()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if russian(c)) / len(letters)


def score(lines) -> tuple[int, int]:
    """Сколько букв прочитано в чистых репликах и сколько — в грязных.

    Считаем именно буквы, а не число реплик: иначе проход, который режет одну
    реплику на две короткие, выглядит лучше (страница 4: «Я РАССЧИ» + «ДУХИ»
    против одной «Я РАССЧИТЫВАЮ НА ВАС, ДУХИ.»).
    """
    clean, dirty = 0, 0
    for line in lines:
        letters = sum(c.isalnum() for c in line.text)
        if line_cleanliness(line.text) >= 0.75:
            clean += letters
        else:
            dirty += letters
    return clean - 2 * dirty, clean


def choose(models, page: Path, verbose: bool = True):
    """Возвращает (ключ лучшего прохода, реплики, отчёт по проходам)."""
    table = {}
    for key, cfg in PASSES.items():
        regions, lines = run_pass(models, page, **cfg)
        conf = [r.score for r in regions] or [0.0]
        table[key] = dict(lines=lines, key=score(lines), conf=sum(conf) / len(conf),
                          regions=len(regions), cfg=cfg)
    best = max(table, key=lambda k: (*table[k]["key"], round(table[k]["conf"], 3)))
    if verbose:
        for key, row in table.items():
            print(f'  {key} ×{row["cfg"]["scale"]:g}/{row["cfg"]["side"]}: '
                  f'фрагментов {row["regions"]}, реплик {len(row["lines"])}, '
                  f'оценка {row["key"][0]}, чистых букв {row["key"][1]}, '
                  f'уверенность {row["conf"]:.3f}' + ('  ← выбран' if key == best else ''))
    return best, table[best]["lines"], table


if __name__ == "__main__":
    pages = [Path(p) for p in sys.argv[1:]] or sorted((ROOT / "pages").glob("*.jpg"))
    models = P.Models()
    result = {}
    for page in pages:
        print(f"=== {page.name}")
        best, lines, table = choose(models, page)
        result[page.name] = {"pass": best, "lines": [l.text for l in lines]}
        for line in lines:
            print(f"     {line.text}")
    (ROOT / "reports" / "chooser_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1))
