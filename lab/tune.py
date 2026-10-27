"""Подбор параметров склейки строк в реплику (облачко) по двум страницам-эталонам."""
from __future__ import annotations

import itertools
import re
from pathlib import Path

import numpy as np

import experiment as E
import pipeline as P

PAGES = {
    "page2.jpg": [
        "НО", "ЗАЧЕМ МЫ ПРИШЛИ В ХРАМ",
        "Я ПОДУМАЛА ЧТО БЫЛО БЫ НЕПЛОХО ПРОГУЛЯТЬСЯ В КАКОЕ-НИБУДЬ СВЯЩЕННОЕ МЕСТО",
        "ВАУ ЭТО ЗВУЧИТ ОЧЕНЬ ВЕСЕЛО", "ПРЯМО СЕЙЧАС",
    ],
    "page4_v297.jpg": [
        "ЕЙ НЕ ПОМОЖЕТ ДАЖЕ ПОЛНОЧНОЧНИЦА",
        "ДА ПОЧЕМУ ВЫ И НЕТ",
        "ПОЖАЛУЙСТА ПОЗВОЛЬ МНЕ ДО ОТВАЛА ПОЕСТЬ ВКУСНОЙ ЕДЫ",
        "ПОЖАЛУЙСТА СДЕЛАЙ ЧТО-НИБУДЬ С ЭТОЙ СТРАШНОЙ ШТУКОЙ КОТОРАЯ СТОИТ РЯДОМ С ХАНОЙ",
        "ПОЖАЛУЙСТА Я СДЕЛАЮ ЧТО УГОДНО ЧТОБЫ ЭТА ШТУКА ОТЦЕПИЛАСЬ ОТ ХАНЫ",
        "ПОЖАЛУЙСТА СНИМИ С ХАНЫ ЭТО ПРОКЛЯТИЕ И ПОМОГИ МНЕ",
        "ОНА ВСЁ ЕЩЁ ШЕПЧЕТ",
        "ГОТОВО НЕ ЗНАЮ ПОМОЖЕТ ЛИ ЭТО НО",
        "Я РАССЧИТЫВАЮ НА ВАС ДУХИ",
    ],
}


def norm(text: str) -> str:
    text = text.upper().replace("Ё", "Е")
    text = re.sub(r"[^А-ЯA-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def evaluate(texts: list[str], truth: list[str]) -> tuple[int, float]:
    got = [norm(t) for t in texts]
    found, quality, last = 0, 0.0, -1
    for target in truth:
        words = [w for w in norm(target).split() if len(w) > 1]
        best_index, best_hit = -1, 0
        for index, text in enumerate(got):
            hit = sum(1 for word in words if word in text)
            if hit > best_hit:
                best_hit, best_index = hit, index
        if words and best_hit >= max(1, int(len(words) * 0.6)):
            found += 1
            quality += best_hit / len(words)
            if best_index > last:
                last = best_index
    return found, quality / len(truth)


def same_bubble(a, b, center_factor, gap_factor, back_factor):
    aw, bw = a.right - a.left, b.right - b.left
    ah, bh = a.bottom - a.top, b.bottom - b.top
    if min(aw, bw) <= 0 or min(ah, bh) <= 0:
        return False
    overlap = min(a.right, b.right) - max(a.left, b.left)
    if overlap <= 0 or overlap / min(aw, bw) < 0.30:
        return False
    if abs((a.left + a.right) / 2 - (b.left + b.right) / 2) > max(aw, bw) * center_factor:
        return False
    gap = b.top - a.bottom
    if gap < -ah * back_factor or gap > max(ah, bh) * gap_factor:
        return False
    if ah > aw * 3 or bh > bw * 3:
        return False
    return True


def merge_bubbles(lines, compare_all, center_factor, gap_factor, back_factor):
    result = []
    for line in sorted(lines, key=lambda x: (x.top, x.left)):
        target, best_gap = -1, float("inf")
        candidates = result if compare_all else result[-1:]
        for index, bubble in enumerate(candidates):
            real_index = result.index(bubble) if compare_all else len(result) - 1
            if not same_bubble(bubble, line, center_factor, gap_factor, back_factor):
                continue
            gap = line.top - bubble.bottom
            if gap < best_gap:
                best_gap, target = gap, real_index
        if target >= 0:
            bubble = result[target]
            result[target] = P.Line(P._join(bubble.text, line.text),
                                    min(bubble.left, line.left), min(bubble.top, line.top),
                                    max(bubble.right, line.right), max(bubble.bottom, line.bottom))
        else:
            result.append(P.Line(line.text, line.left, line.top, line.right, line.bottom))
    return result


def bubbles_with(regions, rtl, params):
    """Тот же порядок, что в pipeline.bubbles_of, но со своими параметрами склейки."""
    source = [P.Region(P.fix_lookalikes(P.clean_speech(r.text)), r.left, r.top, r.right, r.bottom, r.score)
              for r in regions if any(c.isalnum() for c in r.text)]
    source = [r for r in source if P._is_cyrillic(r.text)]
    out = []
    for panel in P.split_panels(source, rtl):
        blocks = []
        for region in sorted(panel, key=lambda r: (r.top, r.left)):
            target, best_gap = None, float("inf")
            for block in blocks:
                head = block[-1]
                lh = max(head.bottom - head.top, 0.01)
                if min(head.bottom, region.bottom) - max(head.top, region.top) <= lh * 0.35:
                    continue
                bl, br = min(b.left for b in block), max(b.right for b in block)
                gap = region.left - br if region.left > br else (region.right - bl if region.right < bl else 0.0)
                if gap > lh * 1.6 or gap < -lh * 0.9:
                    continue
                if gap < best_gap:
                    best_gap, target = gap, block
            if target is not None:
                target.append(region)
            else:
                blocks.append([region])
        lines = []
        for block in blocks:
            ordered = sorted(block, key=lambda r: -r.left if rtl else r.left)
            text = ""
            for i, part in enumerate(ordered):
                if i:
                    previous = ordered[i - 1].text
                    if text.endswith(("-", "\u00ad")):
                        text = text[:-1]
                    elif len(part.text) <= 2 and previous[-1:].isalpha() and part.text[:1].isalpha():
                        pass
                    else:
                        text += " "
                text += part.text
            lines.append(P.Line(text, min(p.left for p in ordered), min(p.top for p in ordered),
                                max(p.right for p in ordered), max(p.bottom for p in ordered)))
        merged = merge_bubbles(lines, *params)
        merged.sort(key=lambda x: (int(x.top * 200), -x.left if rtl else x.left))
        out += merged
    return out


def main() -> None:
    models = P.Models()
    cache = {}
    for name in PAGES:
        img = E.load(Path("pages") / name, 2.0, False)
        boxes = E.detect_with(models, img, 1600, False)
        cache[name] = E.recognize(models, img, boxes, "projection", 0.25)

    rows = []
    for compare_all, center_factor, gap_factor, back_factor in itertools.product(
            [False, True], [0.8, 1.0, 1.3], [1.2, 1.8, 2.5], [0.6, 1.0]):
        params = (compare_all, center_factor, gap_factor, back_factor)
        total_found, total_quality, lines_total = 0, 0.0, 0
        details = {}
        for name, truth in PAGES.items():
            lines = bubbles_with(cache[name], True, params)
            texts = [line.text for line in lines]
            found, quality = evaluate(texts, truth)
            total_found += found
            total_quality += quality
            lines_total += abs(len(texts) - len(truth))
            details[name] = (found, len(truth), round(quality, 2), texts)
        rows.append((total_found, -lines_total, total_quality, params, details))

    rows.sort(key=lambda r: (-r[0], -r[1], -r[2]))
    print(f"эталонов: {sum(len(v) for v in PAGES.values())} реплик на двух страницах\n")
    for found, neg_extra, quality, params, details in rows[:6]:
        compare_all, center, gap, back = params
        print(f"перебор всех={compare_all} сдвиг<{center} зазор<{gap} назад<{back}: "
              f"найдено {found}/14, лишних строк {abs(neg_extra)}, точность {quality / 2:.2f}")
        for name, (found_page, total, quality_page, texts) in details.items():
            print(f"    {name}: {found_page}/{total} реплик, строк {len(texts)}")
        for name, (_, _, _, texts) in details.items():
            print(f"      {name}: " + " | ".join(t[:60] for t in texts))
        print()


if __name__ == "__main__":
    main()
