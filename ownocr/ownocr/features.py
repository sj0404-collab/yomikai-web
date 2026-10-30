"""Своё описание глифа — без свёрточных сетей и без готовых библиотек признаков.

Идея: буква — это пятно краски. Чтобы отличить «В» от «Ь», «О» от «С», «Ш» от
«Щ», достаточно трёх вещей:

  1) ГДЕ краска — плотность чернил по сетке 6×6 (36 чисел);
  2) КУДА идут штрихи — 8 направлений в каждой из 9 клеток (72 числа);
  3) ГДЕ крайние точки — профили по вертикали и горизонтали (24 числа);
     плюс три формы: пропорция, заполненность, число дырок внутри.

Всё это считается целочисленной арифметикой и сравнениями — ни одной обученной
матрицы. Модель учат уже поверх этих чисел (model.py).

Нормализация важна: буква приводится к рамке 24×24 с сохранением пропорций,
поэтому признаки не зависят от кегля и шрифта.
"""
from __future__ import annotations

import cv2
import numpy as np

SIDE = 24          # рабочий квадрат
GRID = 6           # сетка плотности 6×6
ORIENT = 8         # направлений штриха
HOG_CELLS = 3      # 3×3 клетки для направлений
PROJ = 12          # отсчётов в каждом профиле

DIM = GRID * GRID + HOG_CELLS * HOG_CELLS * ORIENT + 2 * PROJ + 3   # 135


def _normalize(gray: np.ndarray) -> np.ndarray | None:
    """Обрезать по чернилам и вписать в квадрат 24×24, сохранив пропорции."""
    ink = gray < 128
    ys, xs = np.where(ink)
    if len(ys) < 2:
        return None
    crop = gray[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = crop.shape
    k = (SIDE - 2) / max(h, w)
    nw, nh = max(1, int(round(w * k))), max(1, int(round(h * k)))
    small = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas = np.full((SIDE, SIDE), 255, np.uint8)
    ox, oy = (SIDE - nw) // 2, (SIDE - nh) // 2
    canvas[oy:oy + nh, ox:ox + nw] = small
    return canvas


def features(gray: np.ndarray) -> np.ndarray | None:
    """135 чисел на глиф. None — если чернил нет (пустой кроп)."""
    canvas = _normalize(gray)
    if canvas is None:
        return None
    ink = (255.0 - canvas.astype(np.float32)) / 255.0      # 1 = краска

    # 1) где краска: средняя плотность по клеткам 6×6
    cell = SIDE // GRID
    density = ink[:cell * GRID, :cell * GRID].reshape(GRID, cell, GRID, cell).mean(axis=(1, 3)).ravel()
    density /= (np.linalg.norm(density) + 1e-6)

    # 2) куда идут штрихи: magnitude/направление Собеля, 8 корзин, 3×3 клетки
    gx = cv2.Sobel(canvas, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(canvas, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy)
    ang = (np.arctan2(gy, gx) + np.pi) % np.pi            # 0..π — направление штриха
    bins = np.minimum((ang / (np.pi / ORIENT)).astype(int), ORIENT - 1)
    hog = np.zeros((HOG_CELLS, HOG_CELLS, ORIENT), np.float32)
    step = SIDE // HOG_CELLS
    for cy in range(HOG_CELLS):
        for cx in range(HOG_CELLS):
            sl = (slice(cy * step, (cy + 1) * step), slice(cx * step, (cx + 1) * step))
            m, b = mag[sl].ravel(), bins[sl].ravel()
            for k in range(ORIENT):
                hog[cy, cx, k] = m[b == k].sum()
    hog = hog.ravel()
    hog /= (np.linalg.norm(hog) + 1e-6)

    # 3) профили: сколько краски в каждом столбце/строке (сжато до 12 отсчётов)
    rows = ink.sum(axis=1)
    cols = ink.sum(axis=0)
    rows = cv2.resize(rows[None, :], (PROJ, 1), interpolation=cv2.INTER_AREA).ravel()
    cols = cv2.resize(cols[None, :], (PROJ, 1), interpolation=cv2.INTER_AREA).ravel()
    prof = np.concatenate([rows, cols])
    prof /= (prof.max() + 1e-6)

    # 4) три формы: пропорция, заполненность, дырки внутри
    ys, xs = np.where(ink > 0.5)
    h = int(ys.max() - ys.min()) + 1 if len(ys) else 1
    w = int(xs.max() - xs.min()) + 1 if len(xs) else 1
    aspect = min(2.0, w / max(1, h)) / 2.0
    fill = ink.mean()
    holes = cv2.connectedComponents((canvas > 128).astype(np.uint8), 4)[0] - 1
    holes = min(3, max(0, holes)) / 3.0

    return np.concatenate([density, hog, prof, np.array([aspect, fill, holes], np.float32)]).astype(np.float32)


def describe(gray: np.ndarray) -> str:
    """Человекочитаемая расшифровка вектора — чтобы «учитель» видел, что видит ученик."""
    f = features(gray)
    if f is None:
        return 'пусто'
    dens = f[:36].reshape(6, 6)
    hog = f[36:36 + 72].reshape(3, 3, 8)
    asp, fill, holes = f[-3:]
    return (f'плотность {dens.mean():.2f}±{dens.std():.2f} · '
            f'штрих по X {hog[..., 0].sum():.2f} по Y {hog[..., 2].sum():.2f} · '
            f'пропорция {asp * 2:.2f} · заливка {fill:.2f} · дырок {int(round(holes * 3))}')
