"""Подбор условий, при которых страница читается полностью и в верном порядке.

Гоняет одну и ту же страницу через разные варианты подготовки картинки и разбора
и сравнивает результат с эталоном (что написано в облачках).

  python3 lab/experiment.py lab/pages/page2.jpg
"""
from __future__ import annotations

import itertools
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

import pipeline as P
import retry as R

# Эталон: реплики страницы 2 в порядке чтения (справа налево, панель за панелью).
TRUTH = [
    "НО",
    "ЗАЧЕМ МЫ ПРИШЛИ В ХРАМ",
    "Я ПОДУМАЛА ЧТО БЫЛО БЫ НЕПЛОХО ПРОГУЛЯТЬСЯ В КАКОЕ-НИБУДЬ СВЯЩЕННОЕ МЕСТО",
    "ВАУ ЭТО ЗВУЧИТ ОЧЕНЬ ВЕСЕЛО",
    "ПРЯМО СЕЙЧАС",
]


def normalize(text: str) -> str:
    text = text.upper().replace("Ё", "Е")
    text = re.sub(r"[^А-ЯA-Z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def score(texts: list[str]) -> tuple[int, float]:
    """Сколько эталонных реплик найдено и насколько точно, с учётом порядка."""
    found = 0
    order_ok = 0
    last_index = -1
    quality = 0.0
    joined = [normalize(t) for t in texts]
    for truth in TRUTH:
        words = [w for w in normalize(truth).split() if len(w) > 1]
        best_index, best_hit = -1, 0
        for index, text in enumerate(joined):
            hit = sum(1 for word in words if word in text)
            if hit > best_hit:
                best_hit, best_index = hit, index
        if words and best_hit >= max(1, int(len(words) * 0.6)):
            found += 1
            quality += best_hit / len(words)
            if best_index > last_index:
                order_ok += 1
                last_index = best_index
    return found, (quality / len(TRUTH)) if TRUTH else 0.0


def load(path: Path, scale: float, gray: bool) -> np.ndarray:
    image = Image.open(path).convert("RGB")
    if scale != 1:
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    array = np.array(image)
    if gray:
        value = (0.299 * array[:, :, 0] + 0.587 * array[:, :, 1] + 0.114 * array[:, :, 2]).astype(np.uint8)
        array = np.stack([value] * 3, axis=2)
    return array


def detect_with(models: P.Models, img: np.ndarray, max_side: int, normalize_input: bool) -> list[tuple[int, int, int, int]]:
    """Детектор с настраиваемым размером входа и нормализацией."""
    H, W = img.shape[:2]
    ratio = min(1.0, max_side / max(W, H))
    w = max(32, round(W * ratio / 32) * 32)
    h = max(32, round(H * ratio / 32) * 32)
    scaled = P.resize_to(img, w, h)
    if normalize_input:
        scaled = (scaled.astype(np.float32) / 255 - P.MEAN) / P.STD
    prob = models.detect(scaled)[0, 0]
    ph, pw = prob.shape
    return [(int(x1 / pw * W), int(y1 / ph * H), int(x2 / pw * W), int(y2 / ph * H))
            for x1, y1, x2, y2 in P.components(prob)]


def _plausible(text: str, crop: np.ndarray) -> bool:
    """Похож ли результат второй попытки на настоящий текст."""
    if not text.strip():
        return False
    words = text.split()
    h, w = crop.shape[:2]
    # В узком обрывке не может быть нескольких слов: это захваченный сосед.
    if len(words) > 1 and w < 3.0 * h:
        return False
    # Принимаем только осмысленный результат: «TPV» → «ТРВ» → «ТРИ» и
    # «PA3A» → «РАЗА» — да; «UTO» → «ИТО» — нет, это мусор второй попытки.
    # Двойники переводим ДО коррекции: correct_line работает только с
    # кириллицей и иначе возвращает латиницу как есть.
    fixed = P.correct_line(P.convert(text))
    return P.good_words(fixed)


def _needs_retry(text: str) -> bool:
    letters = [c for c in text if c.isalnum()]
    if not letters:
        return True
    return all(c in P.LOOKALIKES for c in letters)


def recognize(models: P.Models, img: np.ndarray, boxes, slicing: str, min_score: float) -> list[P.Region]:
    H, W = img.shape[:2]
    out = []
    for box in boxes[:400]:
        pieces = P.text_lines(img, box) if slicing == "projection" else [box]
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
            canvas[:, :width] = P.resize_to(crop, width, 48)
            text, confidence = models.recognize(canvas)
            if _needs_retry(text):
                # Пусто или целиком латиница/цифры — возможно, это декоративный
                # шрифт на растре («ТРИ РАЗА» → «PABA»). Пробуем ещё раз и
                # принимаем результат, только если он похож на настоящий текст:
                # иначе вторая попытка тащила в реплику соседние слова.
                better_text, better_score = R.attempt(models, crop)
                if better_score > confidence and _plausible(better_text, crop):
                    text, confidence = better_text, better_score
            if text.strip() and confidence > min_score:
                out.append(P.Region(text, line[0] / W, line[1] / H, line[2] / W, line[3] / H, confidence))
    return out


def main() -> None:
    path = Path(sys.argv[1])
    models = P.Models()
    rows = []
    combos = itertools.product(
        [1.0, 1.5, 2.0],            # масштаб картинки
        [False, True],              # оттенки серого
        [960, 1600],                # длинная сторона входа детектора
        [False, True],              # нормализация входа детектора
        ["projection", "whole"],    # разбор бокса
        [0.25, 0.05],               # порог уверенности
    )
    for scale, gray, max_side, normalize_input, slicing, threshold in combos:
        started = time.time()
        img = load(path, scale, gray)
        boxes = detect_with(models, img, max_side, normalize_input)
        regions = recognize(models, img, boxes, slicing, threshold)
        lines = P.reading_order(regions, True)
        texts = [line.text for line in lines]
        found, quality = score(texts)
        rows.append({
            "scale": scale, "gray": gray, "side": max_side, "norm": normalize_input,
            "slice": slicing, "thr": threshold,
            "boxes": len(boxes), "regions": len(regions), "lines": len(lines),
            "found": found, "quality": quality, "seconds": time.time() - started,
            "texts": texts,
        })
        print(f"×{scale} сер{'ое' if gray else 'ый'} сторона{max_side} норм{int(normalize_input)} "
              f"{slicing:10} порог{threshold}: боксов {len(boxes):3} фрагм {len(regions):3} "
              f"реплик {len(lines):2} найдено {found}/{len(TRUTH)} точность {quality:.2f} "
              f"({rows[-1]['seconds']:.1f} с)", flush=True)

    rows.sort(key=lambda r: (-r["found"], -r["quality"], abs(r["lines"] - len(TRUTH)), r["seconds"]))
    print("\n=== ЛУЧШИЕ ВАРИАНТЫ ===")
    for row in rows[:5]:
        print(f"\n×{row['scale']} серый={row['gray']} сторона={row['side']} норм={row['norm']} "
              f"разбор={row['slice']} порог={row['thr']} → найдено {row['found']}/{len(TRUTH)}, "
              f"точность {row['quality']:.2f}, реплик {row['lines']}")
        for index, text in enumerate(row["texts"], 1):
            print(f"   {index}. {text}")

    best = rows[0]
    Path("experiment_result.json").write_text(
        __import__("json").dumps({"best": best, "all": rows}, ensure_ascii=False, indent=1))
    print("\nполные результаты: lab/experiment_result.json")


if __name__ == "__main__":
    main()
