"""Финальная проверка условий в лаборатории — до переноса в приложение.

Условия: увеличение ×2, вход детектора 1600, нарезка на строки, починка
двойников, склейка со всеми облачками (сдвиг < 0.8 ширины).

  python3 lab/verify.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image, ImageDraw

import experiment as E
import pipeline as P

ROOT = Path(__file__).parent
OUT = ROOT / "reports"

TRUTH = {
    "page2.jpg": [
        "НО", "ЗАЧЕМ МЫ ПРИШЛИ В ХРАМ",
        "Я ПОДУМАЛА ЧТО БЫЛО БЫ НЕПЛОХО ПРОГУЛЯТЬСЯ В КАКОЕ-НИБУДЬ СВЯЩЕННОЕ МЕСТО",
        "ВАУ ЭТО ЗВУЧИТ ОЧЕНЬ ВЕСЕЛО", "ПРЯМО СЕЙЧАС",
    ],
    "page4_v297.jpg": [
        "ЕЙ НЕ ПОМОЖЕТ ДАЖЕ ПОЛНОЧНИЦА", "ДА ПОЧЕМУ ВЫ И НЕТ",
        "ПОЖАЛУЙСТА ПОЗВОЛЬ МНЕ ДО ОТВАЛА ПОЕСТЬ ВКУСНОЙ ЕДЫ",
        "ПОЖАЛУЙСТА СДЕЛАЙ ЧТО-НИБУДЬ С ЭТОЙ СТРАШНОЙ ШТУКОЙ КОТОРАЯ СТОИТ РЯДОМ С ХАНОЙ",
        "ПОЖАЛУЙСТА Я СДЕЛАЮ ЧТО УГОДНО ЧТОБЫ ЭТА ШТУКА ОТЦЕПИЛАСЬ ОТ ХАНЫ",
        "ПОЖАЛУЙСТА СНИМИ С ХАНЫ ЭТО ПРОКЛЯТИЕ И ПОМОГИ МНЕ",
        "ОНА ВСЁ ЕЩЁ ШЕПЧЕТ", "ГОТОВО НЕ ЗНАЮ ПОМОЖЕТ ЛИ ЭТО НО", "Я РАССЧИТЫВАЮ НА ВАС ДУХИ",
    ],
    "page12_v299.jpg": ["ВЫГЛЯДИТ ОТЛИЧНО"],
}


def norm(text: str) -> str:
    text = text.upper().replace("Ё", "Е")
    text = re.sub(r"[^А-ЯA-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compare(texts, truth):
    got = [norm(t) for t in texts]
    found, last = 0, -1
    details = []
    for target in truth:
        words = [w for w in norm(target).split() if len(w) > 1]
        best_index, best_hit = -1, 0
        for index, text in enumerate(got):
            hit = sum(1 for word in words if word in text)
            if hit > best_hit:
                best_hit, best_index = hit, index
        ok = bool(words) and best_hit >= max(1, int(len(words) * 0.6))
        ordered = ok and best_index > last
        if ordered:
            last = best_index
        if ok:
            found += 1
        details.append((target, best_hit, len(words), ordered))
    return found, details


def main() -> None:
    models = P.Models()
    summary = {"scale": 2.0, "detector": 1600, "pages": {}}
    for name, truth in TRUTH.items():
        page = ROOT / "pages" / name
        img = E.load(page, 2.0, False)
        boxes = E.detect_with(models, img, 1600, False)
        regions = E.recognize(models, img, boxes, "projection", 0.25)
        lines = P.reading_order(regions, True)
        texts = [line.text for line in lines]
        found, details = compare(texts, truth)
        in_order = sum(1 for _, _, _, ordered in details if ordered)
        summary["pages"][name] = {
            "size": list(Image.open(page).size),
            "regions": len(regions),
            "lines": len(lines),
            "found": found,
            "in_order": in_order,
            "truth": len(truth),
            "texts": texts,
        }
        print(f"{name}: фрагментов {len(regions)}, реплик {len(lines)} (эталон {len(truth)}), "
              f"текст совпал {found}/{len(truth)}, по порядку {in_order}/{len(truth)}")
        for index, text in enumerate(texts, 1):
            print(f"   {index}. {text}")

    (OUT / "verify_result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    total_truth = sum(v["truth"] for v in summary["pages"].values())
    total_found = sum(v["found"] for v in summary["pages"].values())
    print(f"\nИТОГО: текст совпал {total_found}/{total_truth}, "
          f"реплик ровно столько же: "
          f"{all(v['lines'] == v['truth'] for v in summary['pages'].values())}")


if __name__ == "__main__":
    main()
