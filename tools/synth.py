"""Синтетические строки для обучения распознавателя: рисуем текст шрифтом и
портим его так, как это делает манга (наклон, размытие, шум, заливка, обрезка).

Зачем синтетика. Размеченных кропов строк у нас нет: в репозитории лежат только
модели. Поэтому тренировочная площадка берёт слова из ВШИТОГО словаря
(part0-dict.js — 487 247 слов, ровно те, что приложение знает), рисует из них
строки системными шрифтами с кириллицей и портит их. Это не замена настоящей
разметке: на настоящей манге цифры будут другими. Но это честный, воспроизводимый
прогон «данные → обучение → ONNX → приложение», и его можно повторить на своей
разметке (--crops, см. README).

Важное для совместимости: ширина дополняется СЕРЫМ (128), как это делает
приложение (recProbs заливает нулями float-массив, а 0 в нормировке = серый).
Отступы строки — 20 % высоты, как в decodeLine32.
"""
from __future__ import annotations

import base64
import gzip
import os
import random
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

H = 48                      # высота входа модели
W_MAX = 320                 # ширина, к которой приложение дополняет кроп
GRAY_PAD = 128              # чем приложение дополняет: 0 в нормировке = 128/255
PAD_CHOICES = (128, 160, 192, 256, 320)   # ширина холста; кратна 8, как ждёт модель

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def available_fonts() -> list:
    return [p for p in FONT_CANDIDATES if os.path.exists(p)]


def load_words(limit: int = 60000, min_len: int = 2, max_len: int = 12) -> list:
    """Слова из вшитого словаря в порядке частоты (part0-dict.js → gzip → текст).

    Так тренировочная выборка состоит из тех же слов, что знает приложение, —
    иначе словарный декодер будет «исправлять» модель в другую сторону.
    """
    path = os.path.join(REPO, "part0-dict.js")
    if os.path.exists(path):
        src = open(path, "r", encoding="utf-8").read()
        m = re.search(r"const DICT_GZ_B64 = '([^']+)'", src)
        if not m:
            raise SystemExit("part0-dict.js: не нашёл DICT_GZ_B64")
        text = gzip.decompress(base64.b64decode(m.group(1))).decode("utf-8")
        words = [line.split()[0] for line in text.split("\n") if line.strip()]
    else:                                   # запасной путь: любой список по частоте
        alt = os.path.join(REPO, "tools", "words_ru.txt")
        words = [w.strip() for w in open(alt, encoding="utf-8") if w.strip()]
    cyr = re.compile(r"^[а-яё]+$")
    out = [w for w in words[:limit] if cyr.match(w) and min_len <= len(w) <= max_len]
    if not out:
        raise SystemExit("не нашлось слов — проверь part0-dict.js")
    return out


class LineRenderer:
    """Рисует строку текста в картинку 48×320 и портит её."""

    def __init__(self, words: list, charset: str, hard: float = 0.35, max_chars: int = 16,
                 pad_choices=None, strength: float = 1.0):
        self.words = words
        self.max_chars = max_chars
        # ширины холста (кратны 8). Учёба идёт по ступеням: сначала узкие строки
        # на 2–4 буквы (быстро, T=8–16), потом обычные. См. tools/README.md.
        self.pad_choices = tuple(pad_choices) if pad_choices else PAD_CHOICES
        # strength — общая сила порчи (0…1). Учёба идёт по ступеням: с 0,25
        # модель сначала выучивает буквы, потом порог поднимается до 1,0.
        # Замер 27.10: при полной порче с нуля потеря стоит на 3,6 и не движется
        # (модель выучивает «всегда blank»), при 0,25 те же шаги дают читаемый текст.
        self.strength = max(0.0, min(1.0, strength))
        self.alphabet = set(charset)
        self.fonts = available_fonts()
        if not self.fonts:
            raise SystemExit(
                "нет шрифтов с кириллицей. Поставь пакет: apt-get install fonts-dejavu-core"
            )
        self.hard = hard
        self._cache = {}

    def _font(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        key = (path, size)
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(path, size)
        return self._cache[key]

    def random_text(self, rng: random.Random, max_chars: int) -> str:
        while True:
            n = rng.choice([1, 1, 2, 2, 3, 3, 4])
            text = " ".join(rng.choice(self.words) for _ in range(n)).upper()
            if 3 <= len(text) <= max_chars and all(c in self.alphabet for c in text):
                if rng.random() < 0.22:                       # знаки, как в манге
                    text += rng.choice(["!", "?", "…", "!!", "?!", "."])
                return text

    def render(self, rng: random.Random, text: str = None, degrade: bool = True):
        # 1) подбираем кегль так, чтобы строка заняла 40…300 px по ширине
        font_path = rng.choice(self.fonts)
        cap_w = max(self.pad_choices)
        target_w = rng.randint(max(40, cap_w // 2), cap_w - 24)
        size = rng.randint(22, 40)
        if text is None:
            text = self.random_text(rng, max_chars=max(3, min(self.max_chars, target_w // 11)))
        for _ in range(12):
            f = self._font(font_path, size)
            box = ImageDraw.Draw(Image.new("L", (8, 8))).textbbox((0, 0), text, font=f)
            tw, th = box[2] - box[0], box[3] - box[1]
            if th <= H - 10 and tw <= cap_w - 20:
                break
            size = max(14, int(size * 0.85))
        tw, th = max(1, tw), max(1, th)
        cw = int(min(cap_w, max(tw + 12, min(64, cap_w), tw + 12 + rng.randint(0, 60))))
        cw = (cw + 7) // 8 * 8

        # 2) холст: белый или чёрный (инверсия), текст поверх
        dark = degrade and rng.random() < 0.18 * self.strength
        bg = rng.randint(0, 40) if dark else rng.randint(215, 255)
        fg = rng.randint(215, 255) if dark else rng.randint(0, 45)
        img = Image.new("L", (cw, H), bg)
        d = ImageDraw.Draw(img)
        x = rng.randint(2, max(3, 10))
        y = (H - th) // 2 - box[1] + rng.randint(-3, 3)
        d.text((x, y), text, font=f, fill=fg)

        # 3) наклон: манга почти всегда наклоняет строку
        tan = rng.uniform(-0.32, 0.32) * self.strength if degrade else 0.0
        if abs(tan) > 0.03:
            img = img.transform((cw, H), Image.AFFINE, (1, tan, -tan * H / 2, 0, 1, 0),
                                resample=Image.BICUBIC, fillcolor=bg)

        # 4) порча: размытие, шум, обрезание части букв, блики
        if degrade and rng.random() < 0.6 * self.strength:
            img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.2) * self.strength))
        arr = np.asarray(img, dtype=np.float32)
        if degrade and rng.random() < 0.5 * self.strength:
            arr += np.random.normal(0, rng.uniform(2, 14) * self.strength, arr.shape)
        if degrade and rng.random() < self.hard * self.strength:                          # блик/заплатка
            w0 = rng.randint(6, 40)
            h0 = rng.randint(6, H)
            x0 = rng.randint(0, max(0, cw - w0))
            y0 = rng.randint(0, max(0, H - h0))
            arr[y0:y0 + h0, x0:x0 + w0] = bg + rng.randint(-25, 25)
        if degrade and rng.random() < 0.25 * self.strength:   # жёсткое обрезание края
            cut = rng.randint(4, 12)
            if rng.random() < 0.5:
                arr[:, :cut] = bg
            else:
                arr[:, -cut:] = bg
        # контраст/яркость: мягкий сдвиг точки чёрного и растяжка диапазона.
        # ВАЖНО: за точкой чёрного всё становится 0, поэтому lo не может быть
        # больше ~0,3 — иначе белый текст на тёмной заливке выжигается в ноль
        # (на этом сломался первый прогон обучения 27.10).
        if degrade:
            lo = rng.uniform(0.0, 0.25) * self.strength
            hi = 1.0 - (1.0 - rng.uniform(0.80, 1.0)) * self.strength
            arr = np.clip((arr / 255.0 - lo) / max(1e-3, hi - lo) * 255.0, 0, 255)

        # 5) дополняем серым до ширины из набора — приложение дополняет так же
        #    (0 в нормировке = серый 128). Ширины разные, чтобы модель не привыкала
        #    к одной и чтобы батч считался быстрее.
        pad_w = next((w for w in self.pad_choices if w >= cw), max(self.pad_choices))
        full = np.full((H, pad_w), float(GRAY_PAD), dtype=np.float32)
        full[:, :cw] = arr
        x3 = np.repeat(full[None, :, :], 3, axis=0)
        x3 = (x3 / 255.0 - 0.5) / 0.5
        # ровно то же, что у приложения: за пределами width — нули float-массива
        x3[:, :, cw:] = 0.0
        return x3.astype(np.float32), text

    def sample(self, rng: random.Random):
        return self.render(rng)


def fake_batch(renderer: LineRenderer, n: int = 2, seed: int = 0):
    """Пара картинок для быстрых проверок (тесты, контракт ONNX)."""
    rng = random.Random(seed)
    xs, ys = [], []
    for _ in range(n):
        x, t = renderer.sample(rng)
        xs.append(x)
        ys.append(t)
    return np.stack(xs), ys


if __name__ == "__main__":
    rng = random.Random(1)
    r = LineRenderer(load_words(5000), open(os.path.join(HERE, "rec_charset.txt"),
                                            encoding="utf-8").read().replace("\n", ""))
    x, text = r.sample(rng)
    print("картинка", x.shape, x.dtype, "· минимум", round(float(x.min()), 2),
          "· максимум", round(float(x.max()), 2), "· текст:", text)
    print("шрифтов:", len(r.fonts), "· слов:", len(r.words))
