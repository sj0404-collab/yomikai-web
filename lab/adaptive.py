"""Адаптивные условия: страница прогоняется несколькими проходами, результаты
сливаются по тексту, а не по геометрии.

Зачем: перебор на страницах 2/15/16 показал, что нет одних условий на всё —
×2 + детектор 1600 выигрывают на плотном тексте (страница 2), но теряют мелкий
белый текст (страница 15, «ЧТО?..»). Поэтому:

  проход A — ×2, вход детектора 1600 (плотный текст);
  проход B — ×1, вход детектора 960  (мелкий и белый текст);

и слияние: два фрагмента считаются одним и тем же куском текста, если их центры
рядом И текст похож (а не только по IoU — в разных масштабах боксы одного текста
сильно разного размера, и IoU-склейка давала «ОНИ. ОНИ»).

  python3 lab/adaptive.py [страницы...]
"""
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

import experiment as E
import pipeline as P

ROOT = Path(__file__).parent
OUT = ROOT / "reports"

PASSES = {
    "A": dict(scale=2.0, side=1600),
    "B": dict(scale=1.0, side=960),
    "C": dict(scale=3.0, side=1600),
}


def run_pass(models, page: Path, scale: float, side: int) -> list[P.Region]:
    img = E.load(page, scale, False)
    boxes = E.detect_with(models, img, side, False)
    return E.recognize(models, img, boxes, "projection", 0.25)


def letters(text: str) -> int:
    return sum(c.isalnum() for c in text)


def similar(a: P.Region, b: P.Region) -> bool:
    """Один и тот же кусок текста: центры рядом и текст похож."""
    aw, ah = a.right - a.left, a.bottom - a.top
    bw, bh = b.right - b.left, b.bottom - b.top
    dx = abs((a.left + a.right) - (b.left + b.right)) / 2
    dy = abs((a.top + a.bottom) - (b.top + b.bottom)) / 2
    near = dx < 0.6 * min(aw, bw) + 0.008 and dy < 0.6 * min(ah, bh) + 0.008
    if not near:
        return False
    ratio = difflib.SequenceMatcher(None, a.text.lower(), b.text.lower()).ratio()
    return ratio >= 0.5


def fuse(base: list[P.Region], extra: list[P.Region]) -> list[P.Region]:
    """Добавляет из extra только те фрагменты, которых в base нет или которые
    прочитаны лучше; дубликаты по тексту не размножаются."""
    out = list(base)
    for region in extra:
        twin = next((i for i, o in enumerate(out) if similar(o, region)), None)
        if twin is None:
            out.append(region)
        elif letters(region.text) > letters(out[twin].text):
            out[twin] = region
    return out


def adaptive(models, page: Path, whose: tuple[str, ...] = ("A", "B")) -> tuple[list[P.Region], list[str]]:
    per = {key: run_pass(models, page, **PASSES[key]) for key in whose}
    merged = per[whose[0]]
    for key in whose[1:]:
        merged = fuse(merged, per[key])
    return merged, list(whose)


def quality(lines: list[P.Line]) -> tuple[int, float]:
    """Оценка без эталона: сколько слов прочитано и насколько уверенно."""
    words = sum(len(line.text.split()) for line in lines)
    return words, 0.0


if __name__ == "__main__":
    truth = json.loads((ROOT / "truth.json").read_text()) if (ROOT / "truth.json").exists() else {}
    pages = [Path(p) for p in sys.argv[1:]] or sorted((ROOT / "pages").glob("*.jpg"))
    models = P.Models()
    report = {}
    for page in pages:
        row = {}
        for key in PASSES:
            row[key] = [l.text for l in P.reading_order(run_pass(models, page, **PASSES[key]), True)]
        row["A+B"] = [l.text for l in P.reading_order(adaptive(models, page)[0], True)]
        row["A+C"] = [l.text for l in P.reading_order(adaptive(models, page, ("A", "C"))[0], True)]
        report[page.name] = row
        print(f"=== {page.name}")
        for key, texts in row.items():
            print(f"  {key:5} {len(texts):2}: " + " | ".join(t[:30] for t in texts))
    (OUT / "adaptive_result.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
