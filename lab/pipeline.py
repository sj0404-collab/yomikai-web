"""KOMA-распознавание в чистом Python: эталон для лаборатории.

Повторяет 1:1 то, что делает приложение версии v2.9.7 (последняя рабочая):
тайлы 1800/160 → детектор 960/(32) → компоненты BFS → резка бокса на строки по
проекции тёмных пикселей → отдельное распознавание каждой строки → порядок
чтения (панели разрезами, облачка, полосы).

Зачем: гонять страницы без сборки APK и сравнивать варианты разбора.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from correct import DICT as DICT_WORDS, correct_line
import onnxruntime as ort
from PIL import Image

ROOT = Path(__file__).parent

# Подобрано перебором (lab/tune.py) на страницах 2 и 4: сдвиг центров строк
# внутри одного облачка не больше 0.8 его ширины.
BUBBLE_SHIFT = 0.8
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class Models:
    def __init__(self, root: Path = ROOT):
        self.det = ort.InferenceSession(str(root / "koma_det.onnx"), providers=["CPUExecutionProvider"])
        self.rec = ort.InferenceSession(str(root / "koma_rec.onnx"), providers=["CPUExecutionProvider"])
        # как в приложении: пустой символ, словарь, пробел в конце
        self.dictionary = [""] + (root / "koma_dict.txt").read_text(encoding="utf-8").splitlines() + [" "]

    def detect(self, arr: np.ndarray, normalize: bool = False) -> np.ndarray:
        """Карта вероятностей детектора.

        По умолчанию — просто /255: именно так результат совпадает с тем, что
        показывает приложение. Флаг normalize включает ImageNet-нормализацию
        (как в Kotlin) — на этой модели она даёт нулевую карту, поэтому её и
        проверяем отдельно как гипотезу о причине слабых боксов.
        """
        x = arr.astype(np.float32) / 255.0
        if normalize:
            x = (x - MEAN) / STD
        x = np.transpose(x, (2, 0, 1))[None]
        return self.det.run(None, {self.det.get_inputs()[0].name: x})[0]

    def recognize(self, arr: np.ndarray) -> tuple[str, float]:
        x = np.transpose((arr.astype(np.float32) / 255.0 - 0.5) / 0.5, (2, 0, 1))[None]
        logits = self.rec.run(None, {self.rec.get_inputs()[0].name: x})[0][0]
        text, score, count, prev = [], 0.0, 0, 0
        for row in logits:
            best = int(np.argmax(row))
            if best != 0 and best != prev:
                text.append(self.dictionary[best] if best < len(self.dictionary) else "")
                score += float(row[best])
                count += 1
            prev = best
        return "".join(text), (score / count if count else 0.0)


# ── шаги пайплайна ────────────────────────────────────────────────────────────

def resize_to(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    return np.array(Image.fromarray(arr).resize((w, h), Image.BILINEAR))


def components(prob: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Связные области карты детектора (4 соседства), порог 0.3 — как в Kotlin."""
    h, w = prob.shape
    seen = np.zeros((h, w), dtype=bool)
    boxes = []
    ys, xs = np.where(prob >= 0.3)
    for sy, sx in zip(ys, xs):
        if seen[sy, sx]:
            continue
        stack = [(sy, sx)]
        seen[sy, sx] = True
        minx = maxx = sx
        miny = maxy = sy
        n = 0
        score = 0.0
        while stack:
            y, x = stack.pop()
            n += 1
            score += prob[y, x]
            minx, maxx = min(minx, x), max(maxx, x)
            miny, maxy = min(miny, y), max(maxy, y)
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx] and prob[ny, nx] >= 0.3:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if n < 6 or score / n < 0.5 or maxx - minx < 2 or maxy - miny < 2:
            continue
        expand = max(2, round((maxx - minx) * (maxy - miny) * 1.5 / (2 * ((maxx - minx) + (maxy - miny)))))
        boxes.append((max(0, minx - expand), max(0, miny - expand), min(w, maxx + expand + 1), min(h, maxy + expand + 1)))
    return sorted(boxes, key=lambda b: b[1])


def detect_tile(models: Models, tile: np.ndarray) -> list[tuple[int, int, int, int]]:
    th, tw = tile.shape[:2]
    ratio = min(1.0, 960.0 / max(tw, th))
    w = max(32, round(tw * ratio / 32) * 32)
    h = max(32, round(th * ratio / 32) * 32)
    scaled = resize_to(tile, w, h)
    prob = models.detect(scaled)[0, 0]
    ph, pw = prob.shape
    out = []
    for x1, y1, x2, y2 in components(prob):
        out.append((int(x1 / pw * tw), int(y1 / ph * th), int(x2 / pw * tw), int(y2 / ph * th)))
    return out


def detect_page(models: Models, img: np.ndarray) -> list[tuple[int, int, int, int]]:
    H, W = img.shape[:2]
    tile_h = 1800 if H > 2800 else H
    boxes, y = [], 0
    while True:
        h = min(tile_h, H - y)
        for x1, y1, x2, y2 in detect_tile(models, img[y:y + h]):
            boxes.append((x1, y1 + y, x2, y2 + y))
        if y + h >= H:
            break
        y += tile_h - 160
    return boxes


def text_lines(img: np.ndarray, box: tuple[int, int, int, int]) -> list[tuple[int, int, int, int]]:
    """Резка бокса детектора на строки по проекции тёмных пикселей (v2.9.7)."""
    H, W = img.shape[:2]
    x1, y1, x2, y2 = box
    pad = max(2, int((y2 - y1) * 0.12))
    left, right = max(0, x1 - pad), min(W, x2 + pad)
    top, bottom = max(0, y1 - pad), min(H, y2 + pad)
    if right - left < 4 or bottom - top < 4:
        return []
    scale = min(1.0, 400.0 / (right - left))
    w, h = max(4, round((right - left) * scale)), max(4, round((bottom - top) * scale))
    small = resize_to(img[top:bottom, left:right], w, h).astype(np.float32)
    luma = (299 * small[:, :, 0] + 587 * small[:, :, 1] + 114 * small[:, :, 2]) / 1000

    def row_has_ink(y: int) -> bool:
        return int((luma[y] < 150).sum()) >= max(1, w // 60)

    runs, y = [], 0
    while y < h:
        if not row_has_ink(y):
            y += 1
            continue
        end = y
        while end < h and row_has_ink(end):
            end += 1
        runs.append([y, end])
        y = max(end, y + 1)
    if not runs:
        return [(left, top, right, bottom)]
    median = int(np.median([r[1] - r[0] for r in runs]))
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= max(1, int(median * 0.35)):
            merged[-1][1] = run[1]
        else:
            merged.append(run[:])
    lines = []
    for a, b in merged:
        if b - a < max(2, int(median * 0.4)):
            continue
        cols = np.where((luma[a:b] < 150).any(axis=0))[0]
        if not cols.size:
            continue
        px0 = int(np.clip(left + cols[0] / scale, left, right - 1))
        px1 = int(np.clip(left + (cols[-1] + 1) / scale, px0 + 1, right))
        py0 = int(np.clip(top + a / scale, top, bottom - 1))
        py1 = int(np.clip(top + b / scale, py0 + 1, bottom))
        lines.append((px0, py0, px1, py1))
    return lines or [(left, top, right, bottom)]


@dataclass
class Region:
    text: str
    left: float
    top: float
    right: float
    bottom: float
    score: float


VARIANTS = ("2.9.7", "2.9.4")


def recognize_page(models: Models, path: str | Path, variant: str = "2.9.7") -> list[Region]:
    """Распознаёт страницу.

    variant="2.9.7" — бокс детектора режется на строки по проекции пикселей;
    variant="2.9.4" — каждый бокс распознаётся целиком (как в 2.9.4 и раньше).
    """
    img = np.array(Image.open(path).convert("RGB"))
    H, W = img.shape[:2]
    out: list[Region] = []
    for box in detect_page(models, img)[:400]:
        pieces = text_lines(img, box) if variant == "2.9.7" else [box]
        for line in pieces:
            crop = img[line[1]:line[3], line[0]:line[2]]
            if crop.size == 0:
                continue
            if crop.shape[0] > crop.shape[1] * 1.8:
                crop = np.rot90(crop, k=-1)
            ch, cw = crop.shape[:2]
            width = int(np.clip(round(48 * cw / ch), 8, 960))
            padded = max(320, width)
            canvas = np.full((48, padded, 3), 128, dtype=np.uint8)
            canvas[:, :width] = resize_to(crop, width, 48)
            text, score = models.recognize(canvas)
            if text.strip() and score > 0.25:
                out.append(Region(text, line[0] / W, line[1] / H, line[2] / W, line[3] / H, score))
    return out


# ── порядок чтения (KomaReadingOrder) ────────────────────────────────────────


# ── починка двойников (как fixLookalikes/cleanSpeech в KomaAutoRead) ────────
LOOKALIKES = {
    'a': 'а', 'e': 'е', 'o': 'о', 'c': 'с', 'p': 'р', 'x': 'х', 'y': 'у',
    'k': 'к', 'm': 'м', 't': 'т', 'b': 'в', 'h': 'н', 'u': 'и', 'n': 'п',
    'A': 'А', 'E': 'Е', 'O': 'О', 'C': 'С', 'P': 'Р', 'X': 'Х', 'Y': 'У',
    'K': 'К', 'M': 'М', 'T': 'Т', 'B': 'В', 'H': 'Н', 'U': 'И', 'V': 'В', 'R': 'Р', 'r': 'г',
    # греческие заглавные, которыми модель пишет русские буквы
    'Λ': 'Л', 'Δ': 'Д', 'Α': 'А', 'Β': 'В', 'Ε': 'Е', 'Ζ': 'З', 'Η': 'Н',
    'Ι': 'И', 'Κ': 'К', 'Μ': 'М', 'Ν': 'Н', 'Ο': 'О', 'Ρ': 'Р', 'Τ': 'Т',
    'Υ': 'У', 'Χ': 'Х',
    # цифры-двойники: модель пишет «3ВУ4ИТ» вместо «ЗВУЧИТ»
    '3': 'з', '4': 'ч', '0': 'о', '6': 'б', '8': 'в',
}


def fix_lookalikes(text: str) -> str:
    """Латинские и греческие двойники внутри русских слов → кириллица.

    Модель регулярно отдаёт «HETΛOXO ПPO-» вместо «НЕПЛОХО ПРО-». Без починки
    такая строка не проходила фильтр «есть кириллица» и пропадала из реплики
    целиком — слова терялись.
    """
    is_ru = lambda c: "а" <= c.lower() <= "я" or c.lower() == "ё"
    greek = set("ΛΔΑΒΕΖΗΙΚΜΝΟΡΤΥΧ")

    def russianish(c: str) -> bool:
        return is_ru(c) or c in greek

    # Решение принимается по СТРОКЕ: если в ней есть русские буквы (пусть и с
    # греческими вкраплениями), то все слова из подозрительных символов
    # переводятся в кириллицу. Иначе «HETΛOXO», «ПРО-» и «BECEΛO» оставались
    # латиницей, строка не проходила фильтр языка и исчезала целиком.
    line_is_russian = any(is_ru(c) or c in greek for c in text)
    out = []
    for word in text.split(" "):
        letters = [c for c in word if c.isalnum()]
        convertible = bool(letters) and all(c in LOOKALIKES for c in letters)
        if line_is_russian and (any(is_ru(c) for c in word) or convertible):
            out.append("".join(LOOKALIKES.get(c, c) for c in word))
        else:
            out.append(word)
    return " ".join(out)


def clean_speech(text: str) -> str:
    """Убирает переносы внутри слова и склеивает разорванные одиночные буквы."""
    import re
    text = re.sub(r"(?<=\w)\s*-\s*(?=\w)", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _merge_by_axis(group, by_y: bool, cut: float):
    key = (lambda r: r.top) if by_y else (lambda r: r.left)
    end = (lambda r: r.bottom) if by_y else (lambda r: r.right)
    bands = []
    for region in sorted(group, key=key):
        s, e = key(region), end(region)
        if bands and s - bands[-1][1] <= cut:
            bands[-1][1] = max(bands[-1][1], e)
            bands[-1][2].append(region)
        else:
            bands.append([s, e, [region]])
    return [b[2] for b in bands] if len(bands) > 1 else [group]


def split_panels(group, rtl: bool, depth: int = 0):
    if len(group) <= 1 or depth > 12:
        return [group]
    heights = sorted(r.bottom - r.top for r in group)
    lh = max(0.008, heights[len(heights) // 2])
    y_cut, x_cut = max(0.022, lh * 0.9), max(0.035, lh * 0.9)
    rows = _merge_by_axis(group, True, y_cut)
    if len(rows) > 1:
        return [p for part in rows for p in split_panels(part, rtl, depth + 1)]
    cols = _merge_by_axis(group, False, x_cut)
    if len(cols) > 1:
        if rtl:
            cols = cols[::-1]
        return [p for part in cols for p in split_panels(part, rtl, depth + 1)]
    return [group]


@dataclass
class Line:
    text: str
    left: float
    top: float
    right: float
    bottom: float


def _join(a: str, b: str) -> str:
    a, b = a.strip(), b.strip()
    if not a:
        return b
    if not b:
        return a
    return a[:-1] + b if a.endswith(("-", "\u2010", "\u2011", "\u2013", "\u2014")) else a + " " + b


def _same_bubble(a: Line, b: Line) -> bool:
    aw, bw = a.right - a.left, b.right - b.left
    ah, bh = a.bottom - a.top, b.bottom - b.top
    if min(aw, bw) <= 0 or min(ah, bh) <= 0:
        return False
    ov = min(a.right, b.right) - max(a.left, b.left)
    if ov <= 0 or ov / min(aw, bw) < 0.30:
        return False
    if abs((a.left + a.right) / 2 - (b.left + b.right) / 2) > max(aw, bw) * BUBBLE_SHIFT:
        return False
    gap = b.top - a.bottom
    if gap < -ah * 0.6 or gap > max(ah, bh) * 1.2:
        return False
    if ah > aw * 3 or bh > bw * 3:
        return False
    return True


def bubbles_of(group, rtl: bool) -> list[Line]:
    blocks: list[list[Region]] = []
    for region in sorted(group, key=lambda r: (r.top, r.left)):
        target, best_gap = None, float("inf")
        for block in blocks:
            head = block[-1]
            lh = max(head.bottom - head.top, 0.01)
            if min(head.bottom, region.bottom) - max(head.top, region.top) <= lh * 0.35:
                continue
            bl, br = min(b.left for b in block), max(b.right for b in block)
            if region.left > br:
                gap = region.left - br
            elif region.right < bl:
                gap = region.right - bl
            else:
                gap = 0.0
            if gap > lh * 1.6 or gap < -lh * 0.9:
                continue
            if gap < best_gap:
                best_gap, target = gap, block
        if target is not None:
            target.append(region)
        else:
            blocks.append([region])

    lines: list[Line] = []
    for block in blocks:
        ordered = sorted(block, key=lambda r: -r.left if rtl else r.left)
        text = ""
        for i, part in enumerate(ordered):
            if i:
                prev = ordered[i - 1].text
                if text.endswith(("-", "\u00ad")):
                    text = text[:-1]
                elif len(part.text) <= 2 and prev[-1:].isalpha() and part.text[:1].isalpha():
                    pass
                else:
                    text += " "
            text += part.text
        lines.append(Line(text, min(p.left for p in ordered), min(p.top for p in ordered),
                          max(p.right for p in ordered), max(p.bottom for p in ordered)))

    # Строка сравнивается со ВСЕМИ собранными облачками и приклеивается к
    # ближайшему по зазору. Раньше сравнивалась только с последним: когда
    # облачка стоят рядом по горизонтали, их строки идут по высоте вперемешку,
    # и половина строк уходила в новое облачко — реплика рвалась.
    result: list[Line] = []
    for line in sorted(lines, key=lambda x: (x.top, x.left)):
        target, best_gap = -1, float("inf")
        for index, bubble in enumerate(result):
            if not _same_bubble(bubble, line):
                continue
            gap = line.top - bubble.bottom
            if gap < best_gap:
                best_gap, target = gap, index
        if target >= 0:
            bubble = result[target]
            result[target] = Line(_join(bubble.text, line.text), min(bubble.left, line.left),
                                  min(bubble.top, line.top), max(bubble.right, line.right),
                                  max(bubble.bottom, line.bottom))
        else:
            result.append(line)
    return sorted(result, key=lambda x: (int(x.top * 200), -x.left if rtl else x.left))


def reading_order(regions: list[Region], rtl: bool = True, correct: bool = True) -> list[Line]:
    # Починка двойников ДО фильтра по языку: иначе строка из латиницы и
    # греческих «Λ», «Δ» отбрасывалась целиком и слова пропадали.
    # Одиночные буквы — это шум: детектор цепляет случайные штрихи и значки
    # интерфейса («е» на скриншоте плеера попадала в список реплик). Обрывки из
    # двух символов («НО», «ДА») нужны: это настоящие реплики.
    fixed = [Region(fix_lookalikes(clean_speech(r.text)), r.left, r.top, r.right, r.bottom, r.score)
             for r in regions
             if sum(c.isalnum() for c in r.text) >= 2]
    fixed = _rescue_lookalike_lines(fixed)
    src = [r for r in fixed if _is_cyrillic(r.text)]
    lines = [line for panel in split_panels(src, rtl) for line in bubbles_of(panel, rtl)]
    # Языковая коррекция — уже на собранной реплике, а не на обрывке: модель
    # путает буквы в словах, и словарь это чинит («ПОШЕВЕАИТЬСЯ» →
    # «ПОШЕВЕЛИТЬСЯ», «СЮОДА» → «СЮДА», «ТРУ» → «ТРИ»).
    if correct:
        for line in lines:
            line.text = normalize_case(correct_line(line.text))
    return lines


def convert(text: str) -> str:
    """Перевод двойников: строку из одних двойников переводим целиком."""
    if _lookalike_only(text):
        return "".join(LOOKALIKES.get(c, c) for c in text)
    return fix_lookalikes(text)


def _lookalike_only(text: str) -> bool:
    letters = [c for c in text if c.isalnum()]
    return bool(letters) and all(c in LOOKALIKES for c in letters)


VOWELS = set("аеиоуыэюяёАЕИОУЫЭЮЯЁ")


def good_words(text: str) -> bool:
    """Все слова строки — настоящие русские слова (или короткие предлоги)."""
    words = [w.lower() for w in text.replace("-", " ").split() if w.strip(".,!?…—") ]
    if not words:
        return False
    words = [w.strip(".,!?…—") for w in words]
    known = [w for w in words if len(w) >= 3 and w in DICT_WORDS]
    return len(known) == len(words) and bool(words)


def normalize_case(text: str) -> str:
    """Реплики в манге набраны заглавными, но модель выдаёт «СЕбЯ».

    Если заглавных букв заметно больше, чем строчных, приводим всю строку к
    заглавным: так реплика выглядит как в книге.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return text
    upper = sum(1 for c in letters if c.isupper())
    # Порог раньше был 75 % — и строка «господи БОЖЕ МОЙ!» (ровно половина
    # заглавных) оставалась со строчной буквой в начале.
    return text.upper() if upper * 2 >= len(letters) else text


def _rescue_lookalike_lines(regions: list[Region]) -> list[Region]:
    """Спасает строки, целиком набранные латинскими двойниками («OHO»).

    Починка двойников решает по строке: если в строке нет ни одной русской
    буквы, строка считается латинской и выбрасывается фильтром языка. На
    странице 16 из-за этого пропадало слово «ОНО» в подписи — модель отдала
    «OHO», то есть латиницей. Спасаем такую строку, если рядом (вплотную по
    вертикали и с перекрытием по горизонтали) есть настоящая русская строка:
    значит, это часть той же реплики, а не латинская надпись.
    """
    cyr = [r for r in regions if _is_cyrillic(r.text)]
    if not cyr:
        return regions
    heights = sorted(r.bottom - r.top for r in regions)
    line_h = heights[len(heights) // 2] if heights else 0.02
    out = []
    for r in regions:
        if _is_cyrillic(r.text) or not _lookalike_only(r.text):
            out.append(r)
            continue
        rescued = "".join(LOOKALIKES.get(c, c) for c in r.text)
        if not _is_cyrillic(rescued):
            out.append(r)
            continue
        letters = sum(c.isalnum() for c in rescued)
        real_word = good_words(correct_line(rescued))
        # Короткие строки («ТРВ» → «ТРИ») спасаем только если получается
        # настоящее слово: иначе в текст лезло «ИТО» из «UTO».
        if letters <= 4 and not real_word:
            out.append(r)
            continue
        if letters > 4 and not (set(rescued) & VOWELS):
            out.append(r)
            continue
        neighbors = [
            c for c in cyr
            if min(r.right, c.right) - max(r.left, c.left) > 0.2 * (r.right - r.left)
            and -4.0 * line_h < (r.top - c.bottom) < 4.0 * line_h
        ]
        # Одиночный пузырь может стоять вдали от любого русского текста
        # («ТРИ РАЗА» в правом верхнем углу). Тогда спасаем по словарю: если
        # после перевода получаются настоящие слова, это русский текст.
        plausible = good_words(correct_line(rescued))
        out.append(Region(rescued, r.left, r.top, r.right, r.bottom, r.score)
                   if neighbors or plausible else r)
    return out


def _is_cyrillic(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    ru = [c for c in letters if "а" <= c.lower() <= "я" or c.lower() == "ё"]
    return bool(ru) and len(ru) * 2 >= len(letters)


if __name__ == "__main__":
    import sys
    import time

    models = Models()
    for path in sys.argv[1:] or sorted((ROOT / "pages").glob("*.jpg")):
        t0 = time.time()
        regions = recognize_page(models, path)
        lines = reading_order(regions)
        print(f"\n=== {Path(path).name} · фрагментов {len(regions)} · {time.time() - t0:.1f} с")
        for i, line in enumerate(lines, 1):
            print(f"{i:2}. {line.text}")
