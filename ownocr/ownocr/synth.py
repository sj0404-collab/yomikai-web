"""Синтетические строки для дообучения CTC-модели: то, чего не хватает в «эславе».

Чужая модель обучена на чистом печатном тексте. На страницах манги буквы мелкие
(кегль ~12 px), смазанные, с неровным нажимом, часто на сером фоне растровой
сетки. Здесь генерируются строки именно такими: шрифт, кегль, размытие, шум,
перекос, обрезка краёв букв, фон-сетка.

Важно: текст берём из словаря русских слов и из настоящих реплик манги, чтобы
модель видела те же буквосочетания (Й, Ё, Ь) и те же слова, что на странице.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONTS = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-BoldOblique.ttf',
]

# Дополнительные шрифты (скачиваются `scripts/01_fetch_fonts.py`): чем их
# больше, тем ближе синтетика к настоящему набору на странице. С 8 шрифтами
# DejaVu модель переобучалась на их начертание.
import glob as _glob
import os as _os
_D = _os.environ.get('FONTS_DIR', '')
EXTRA = sorted(_glob.glob(_D + '/*.ttf') if _D else [])
EXTRA += sorted(_glob.glob('/home/user/fonts/*.ttf'))
EXTRA += sorted(_glob.glob('/var/tmp/ownocr/fonts/*.ttf'))
FONTS = (EXTRA or []) + FONTS

_cache: dict = {}


def _font(path: str, size: int):
    key = (path, size)
    if key not in _cache:
        if len(_cache) > 400:
            _cache.clear()
        _cache[key] = ImageFont.truetype(path, size)
    return _cache[key]


def render_line(text: str, rng: np.random.Generator, *, size: int | None = None,
                font: str | None = None) -> np.ndarray:
    """Одна строка как серая картинка 32 px по высоте (готово для модели)."""
    size = int(size or rng.integers(10, 26))
    path = font or FONTS[rng.integers(len(FONTS))]
    f = _font(path, size)
    # межбуквенный интервал: на манге буквы часто разрежены
    spacing = float(rng.uniform(-0.5, 1.6))
    widths = [f.getlength(ch) + spacing for ch in text]
    W = int(max(8, sum(widths) + rng.integers(4, 18)))
    H = int(size * 1.9)
    bg = int(rng.integers(235, 256))
    canvas = Image.new('L', (W, H), bg)
    d = ImageDraw.Draw(canvas)
    x = float(rng.uniform(0, 6))
    y = float(rng.uniform(0, max(1, H - size * 1.25)))
    ink = int(rng.integers(0, 70))
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=f, fill=ink)
        x += w
    img = canvas

    # размытие и шум скана
    if rng.random() < 0.8:
        img = img.filter(ImageFilter.GaussianBlur(float(rng.uniform(0.3, 1.1))))
    arr = np.asarray(img, np.float32)
    if rng.random() < 0.6:
        arr += rng.normal(0, float(rng.uniform(2, 12)), arr.shape)
    # растр-сетка фона, как на сканах манги
    if rng.random() < 0.35:
        yy, xx = np.mgrid[0:arr.shape[0], 0:arr.shape[1]]
        arr -= 12 * ((yy + xx) % 3 == 0)
    arr = np.clip(arr, 0, 255)

    # перекос строки и обрезка краёв (модель должна видеть буквы у самого края)
    if rng.random() < 0.4:
        shear = float(rng.uniform(-0.06, 0.06))
        M = np.array([[1, shear, 0], [0, 1, 0]], np.float32)
        import cv2
        arr = cv2.warpAffine(arr, M, (arr.shape[1], arr.shape[0]),
                             flags=cv2.INTER_LINEAR, borderValue=255)
    if rng.random() < 0.3:
        cut = int(rng.integers(0, 3))
        arr = arr[:, cut:max(cut + 8, arr.shape[1] - int(rng.integers(0, 3)))]

    # привести к 32 px по высоте с сохранением пропорций
    import cv2
    w = max(8, int(round(arr.shape[1] * 32 / arr.shape[0])))
    arr = cv2.resize(arr, (w, 32), interpolation=cv2.INTER_AREA)
    return np.clip(arr, 0, 255).astype(np.uint8)


def elastic(gray: np.ndarray, rng: np.random.Generator, alpha: float = 1.6,
            sigma: float = 6.0) -> np.ndarray:
    """Упругая деформация: имитирует неровную руку и изгиб строки.

    Настоящего рукописного шрифта у нас нет, а без него модель не видит
    «пляшущих» букв манхвы. Упругая деформация печатного шрифта — дешёвый
    способ дать ей такие примеры.
    """
    import cv2
    h, w = gray.shape
    dx = cv2.GaussianBlur((rng.random((h, w)) * 2 - 1).astype(np.float32), (0, 0), sigma) * alpha
    dy = cv2.GaussianBlur((rng.random((h, w)) * 2 - 1).astype(np.float32), (0, 0), sigma) * alpha
    xx, yy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return cv2.remap(gray, xx + dx, yy + dy, cv2.INTER_LINEAR, borderValue=255)


def augment_real(gray: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Тяжёлая аугментация настоящей строки: масштаб, контраст, размытие, шум."""
    import cv2
    g = gray
    if rng.random() < 0.7:                      # масштаб: от 0,6 до 1,4
        k = float(rng.uniform(0.6, 1.4))
        g = cv2.resize(g, None, fx=k, fy=k,
                       interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC)
    if rng.random() < 0.5:
        g = elastic(g, rng, alpha=float(rng.uniform(0.6, 2.0)))
    if rng.random() < 0.8:
        g = cv2.GaussianBlur(g, (3, 3), float(rng.uniform(0.0, 1.0)))
    if rng.random() < 0.5:                      # контраст и яркость
        lo, hi = np.percentile(g, 2), np.percentile(g, 98)
        g = np.clip((g.astype(np.float32) - lo) * 255.0 / max(1.0, hi - lo) *
                    float(rng.uniform(0.7, 1.3)) + float(rng.uniform(-20, 20)), 0, 255)
    if rng.random() < 0.5:
        g = g + rng.normal(0, float(rng.uniform(2, 14)), g.shape)
    return np.clip(g, 0, 255).astype(np.uint8)


def random_text(rng: np.random.Generator, words: list[str], lines: list[str]) -> str:
    """Текст строки: настоящая реплика манги (чаще) или случайные слова."""
    if rng.random() < 0.55 and lines:
        base = lines[int(rng.integers(len(lines)))].upper()
        toks = base.split()
        if len(toks) > 2:
            i = int(rng.integers(0, len(toks) - 1))
            j = int(rng.integers(i + 2, len(toks) + 1))
            return ' '.join(toks[i:j])
        return base
    n = int(rng.integers(1, 5))
    return ' '.join(words[int(rng.integers(len(words)))] for _ in range(n))
