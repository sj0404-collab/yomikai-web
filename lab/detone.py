"""Чистка растрового фона (screen tone) перед распознаванием.

В манге пузыри часто залиты растром «в точку». Модель видит точки как штрихи и
читает «ТРИ РАЗА» как «РAA». Варианты чистки:
  медиана — давит мелкие точки, сохраняет толстые штрихи букв;
  уменьшение-увеличение — размывает растр;
  закрытие/открытие — убирает точки по отдельности.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps

import pipeline as P


def clean(gray: Image.Image, kind: str) -> Image.Image:
    if kind == "медиана3":
        return gray.filter(ImageFilter.MedianFilter(3))
    if kind == "медиана5":
        return gray.filter(ImageFilter.MedianFilter(5))
    if kind == "сжать-разжать":
        small = gray.resize((max(8, gray.width // 2), max(8, gray.height // 2)), Image.LANCZOS)
        return small.resize(gray.size, Image.LANCZOS)
    if kind == "мин-макс":
        return gray.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    if kind == "макс-мин":
        return gray.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
    if kind == "порог140":
        return gray.point(lambda v: 255 if v > 140 else 0)
    if kind == "медиана3+порог":
        return gray.filter(ImageFilter.MedianFilter(3)).point(lambda v: 255 if v > 120 else 0)
    return gray


KINDS = ["без чистки", "медиана3", "медиана5", "сжать-разжать", "мин-макс",
         "макс-мин", "порог140", "медиана3+порог"]


def read(models: P.Models, img: Image.Image, scale: float = 1.0):
    arr = np.array(img.convert("RGB"))
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
