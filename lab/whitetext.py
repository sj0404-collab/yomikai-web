"""Поиск подхода к «плотному» тексту: декоративный шрифт на растровом фоне.

Проблема: в пузыре «ТРИ РАЗА.» буквы набраны жирным декоративным шрифтом поверх
растра «в точку». Модель отдаёт «РAA» / «PA»: точки фона она принимает за штрихи.
Обычные медианы и инверсии не помогают, потому что точки и штрихи букв близки по
толщине. Пробуем локальное (адаптивное) пороговое преобразование: фон оценивается
локально, буква — это то, что заметно темнее своего окружения.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

import pipeline as P


def _box_blur(arr: np.ndarray, radius: int) -> np.ndarray:
    """Среднее в окне (2r+1) через интегральное изображение."""
    pad = np.pad(arr, radius, mode="edge")
    integral = pad.cumsum(0).cumsum(1)
    integral = np.pad(integral, ((1, 0), (1, 0)))
    h, w = arr.shape
    k = 2 * radius + 1
    s = (integral[k:k + h, k:k + w] - integral[0:h, k:k + w]
         - integral[k:k + h, 0:w] + integral[0:h, 0:w])
    return s / (k * k)


def adaptive(gray: Image.Image, radius: int, delta: float, invert_out: bool = False) -> Image.Image:
    arr = np.asarray(gray, dtype=np.float32)
    bg = _box_blur(arr, radius)
    dark = (arr < bg - delta).astype(np.float32) * 255.0
    out = Image.fromarray(dark.astype(np.uint8))
    return Image.eval(out, lambda v: 255 - v) if invert_out else out


def high_pass(gray: Image.Image, radius: int) -> Image.Image:
    arr = np.asarray(gray, dtype=np.float32)
    hp = np.clip(_box_blur(arr, radius) - arr, 0, None)
    peak = hp.max() or 1.0
    return Image.fromarray((255 * hp / peak).astype(np.uint8))


def read(models: P.Models, img: Image.Image, height: int = 48):
    arr = np.array(img.convert("RGB"))
    h, w = arr.shape[:2]
    if h > w * 1.8:
        arr = np.rot90(arr, k=-1)
        h, w = arr.shape[:2]
    width = int(np.clip(round(height * w / h), 8, 1200))
    canvas = np.full((height, max(320, width), 3), 128, dtype=np.uint8)
    canvas[:, :width] = P.resize_to(arr, width, height)
    return models.recognize(canvas)


def candidates(gray: Image.Image) -> dict[str, Image.Image]:
    out: dict[str, Image.Image] = {"как есть": gray}
    for radius in (5, 9, 15, 25):
        for delta in (10, 20, 35):
            out[f"адаптив r{radius} d{delta}"] = adaptive(gray, radius, delta)
            out[f"адаптив-инв r{radius} d{delta}"] = adaptive(gray, radius, delta, invert_out=True)
    for radius in (9, 25):
        out[f"высокие частоты r{radius}"] = high_pass(gray, radius)
    return out


def scan(models: P.Models, crop: Image.Image, scale: float = 1.0, heights=(48,)):
    base = crop.convert("L")
    if scale != 1.0:
        base = base.resize((int(base.width * scale), int(base.height * scale)), Image.LANCZOS)
    results = {}
    for name, image in candidates(base).items():
        best = ("", 0.0, None)
        for height in heights:
            text, score = read(models, image.convert("RGB"), height)
            if score > best[1]:
                best = (text, score, height)
        results[name] = best
    return results
