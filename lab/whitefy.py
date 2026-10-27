"""Белый текст на тёмном: предобработка вырезки перед распознаванием.

Модель обучена на тёмном тексте по светлому. Когда текст белый на тёмном или на
растре (пузырь «ТРИ РАЗА.»), она отдаёт латиницу («PABA») или ничего. Пробуем
инверсию, медиану, растяжку контраста и бинаризацию.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps

import pipeline as P


def variants(crop: Image.Image) -> dict[str, Image.Image]:
    gray = crop.convert("L")
    return {
        "как есть": gray,
        "инверсия": ImageOps.invert(gray),
        "медиана+инверсия": ImageOps.invert(gray.filter(ImageFilter.MedianFilter(3))),
        "контраст+инверсия": ImageOps.invert(ImageOps.autocontrast(gray, cutoff=2)),
        "бинаризация": gray.point(lambda v: 255 if v > 110 else 0),
        "инверсия+бинаризация": ImageOps.invert(gray).point(lambda v: 255 if v > 140 else 0),
    }


def read(models: P.Models, crop: Image.Image, scale: float = 1.0) -> tuple[str, float]:
    arr = np.array(crop.convert("RGB"))
    if scale != 1.0:
        arr = P.resize_to(arr, int(arr.shape[1] * scale), int(arr.shape[0] * scale))
    h, w = arr.shape[:2]
    if h > w * 1.8:
        arr = np.rot90(arr, k=-1)
        h, w = arr.shape[:2]
    width = int(np.clip(round(48 * w / h), 8, 960))
    canvas = np.full((48, max(320, width), 3), 128, dtype=np.uint8)
    canvas[:, :width] = P.resize_to(arr, width, 48)
    return models.recognize(canvas)
