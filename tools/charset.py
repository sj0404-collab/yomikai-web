"""Азбука распознавателя и раскладка классов — ровно как у модели koma_rec.onnx.

Контракт основного распознавателя (проверено на koma_models/koma_rec.onnx и по
коду part3.js, функции recProbs/decodeCrop/beamDecode):

  вход : float32 [1, 3, 48, W]   (CHW, значение = (пиксель/255 - 0.5)/0.5,
                                  ширина W приводится к max(320, 48*w/h) и
                                  дополняется НУЛЯМИ, то есть серым 127.5)
  выход: float32 [1, T, 519]     T = W/8, значения — ВЕРОЯТНОСТИ (сумма по
                                 519 классам = 1), не логиты

  класс 0            — CTC blank
  классы 1..517      — символы из tools/rec_charset.txt по порядку (517 штук)
  класс 518          — ПРОБЕЛ (part3.js собирает раскладку как
                       `[''].concat(строки cyrillic.txt).concat([' '])`)

Любая обученная здесь модель обязана повторять этот контракт: тогда файл
подкладывается в приложение через ⚙ → Модели и работает со словарным
beam-декодером без правок кода.
"""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))
CHARSET_PATH = os.path.join(HERE, "rec_charset.txt")

N_EXTRA = 1          # пробел последним классом — как в part3.js
BLANK = 0
SPACE = " "


def load_charset(path: str = CHARSET_PATH) -> str:
    with open(path, "r", encoding="utf-8") as f:
        chars = [line for line in f.read().split("\n") if line != ""]
    s = "".join(chars)
    if len(s) != len(chars):
        raise SystemExit(f"{path}: строка не однобуквенная — так нельзя")
    return s


def num_classes(charset: str) -> int:
    """519 для штатной азбуки: 1 blank + 517 символов + 1 «неизвестно»."""
    return 1 + len(charset) + N_EXTRA


def space_class(charset: str) -> int:
    """Класс пробела: последний (518 при штатной азбуке)."""
    return 1 + len(charset)


def char_to_class(charset: str) -> dict:
    m = {ch: i + 1 for i, ch in enumerate(charset)}
    m[SPACE] = space_class(charset)          # пробела в азбуке нет, он последним классом
    return m


def classes_to_text(charset: str, idx) -> str:
    """Жадный разбор (как decodeCrop в part3.js): blank=0, повторы схлопываются."""
    out, prev = [], 0
    for c in idx:
        c = int(c)
        if c != 0 and c != prev:
            if 1 <= c <= len(charset):
                out.append(charset[c - 1])
            elif c == space_class(charset):
                out.append(SPACE)
            # всё, чего нет в раскладке, — пропускаем
        prev = c
    return "".join(out)


def cer(ref: str, hyp: str) -> float:
    """Доля правок (Левенштейн / длина эталона) — та же метрика, что в отчётах."""
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, a in enumerate(ref, 1):
        cur = [i]
        for j, b in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1] / len(ref)


if __name__ == "__main__":
    cs = load_charset()
    print(f"символов {len(cs)} · классов {num_classes(cs)}")
    print("первые:", "".join(cs[:20]))
    print("кириллица с класса", char_to_class(cs)["А"], "·", "АБВ" , "…")
