"""Вторая попытка чтения «трудной» строки.

Зачем: декоративный шрифт на растровом фоне («ТРИ РАЗА») обычным путём не
читается — модель отдаёт пустоту или латиницу («PABA»). Если после медианы
(давит точки растра) сделать локальный адаптивный порог (буква = то, что темнее
своего окружения), та же модель читает эти строки уверенно:

    «ТРИ»  → TPu / TPU  → после починки двойников → ТРИ   (0.70)
    «РАЗА» → PA3A       → после починки двойников → РАЗА  (0.92)

Вторую попытку делаем только для строк, которые обычным путём получились
пустыми или целиком из двойников: иначе она удорожает распознавание и может
перечитать нормальные строки хуже.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

import pipeline as P

VARIANTS = (
    ("med5 r25 d45", 5, 25, 45),
    ("med7 r25 d45", 7, 25, 45),
    ("raw r15 d35", None, 15, 35),
    ("med5 r35 d45", 5, 35, 45),
)


def _box_blur(arr: np.ndarray, radius: int) -> np.ndarray:
    pad = np.pad(arr, radius, mode="edge")
    integral = np.pad(pad.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    h, w = arr.shape
    k = 2 * radius + 1
    s = (integral[k:k + h, k:k + w] - integral[0:h, k:k + w]
         - integral[k:k + h, 0:w] + integral[0:h, 0:w])
    return s / (k * k)


def adaptive(gray: Image.Image, radius: int, delta: float) -> Image.Image:
    arr = np.asarray(gray, dtype=np.float32)
    bg = _box_blur(arr, radius)
    return Image.fromarray(((arr < bg - delta).astype(np.float32) * 255).astype(np.uint8))


def _read(models: P.Models, image: Image.Image) -> tuple[str, float]:
    arr = np.array(image.convert("RGB"))
    h, w = arr.shape[:2]
    if h > w * 1.8:
        arr = np.rot90(arr, k=-1)
        h, w = arr.shape[:2]
    width = int(np.clip(round(48 * w / h), 8, 960))
    canvas = np.full((48, max(320, width), 3), 128, dtype=np.uint8)
    canvas[:, :width] = P.resize_to(arr, width, 48)
    return models.recognize(canvas)


PAD = 0.1           # поля вокруг строки: без них обрезка срезает края букв
MIN_SCORE = 0.6     # ниже этого вторая попытка считается неудачной


def attempt(models: P.Models, crop: np.ndarray) -> tuple[str, float]:
    """Лучшее чтение строки среди предобработанных вариантов."""
    h, w = crop.shape[:2]
    py, px = int(h * PAD), int(w * PAD)
    if py or px:
        crop = np.pad(crop, ((py, py), (px, px), (0, 0)), mode="edge")
    gray = Image.fromarray(crop).convert("L")
    # Согласие вариантов: настоящий текст читается одинаково большинством
    # предобработок, а мусор у каждого варианта свой («ИТО?», «4TO», «ЗТО»).
    votes: dict[str, list[float]] = {}
    for _, median, radius, delta in VARIANTS:
        base = gray if median is None else gray.filter(ImageFilter.MedianFilter(median))
        image = adaptive(base, radius, delta)
        for candidate in (image, Image.eval(image, lambda v: 255 - v)):
            text, score = _read(models, candidate)
            key = "".join(c for c in text.upper() if c.isalnum())
            if not key:
                continue
            votes.setdefault(key, []).append(score)
    if not votes:
        return ("", 0.0)
    key, scores = max(votes.items(), key=lambda kv: (len(kv[1]), sum(kv[1]) / len(kv[1])))
    if len(scores) < 2:
        return ("", 0.0)
    best_score = sum(scores) / len(scores)
    return (key, best_score) if best_score >= MIN_SCORE else ("", 0.0)
