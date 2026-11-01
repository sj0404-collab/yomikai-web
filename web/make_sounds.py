#!/usr/bin/env python3
"""Звуки для звуковых эффектов манги — синтезом, без чужих файлов.

Зачем синтезом: у нас нет прав на звуковые библиотеки, а короткий «гонг» или
«удар» — это несколько синусоид и шум с огибающей. 22 050 Гц, моно, 16 бит:
каждый файл 20–60 КБ, все шесть вместе — меньше 0,3 МБ, едут внутрь html
data-URI как и модели.

    python3 web-ocr/make_sounds.py      → web-ocr/data/sfx/*.wav
"""
import os
import struct
import wave

import numpy as np

SR = 22050
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'sfx')


def env(n, attack=0.005, decay=6.0):
    t = np.linspace(0, 1, n, endpoint=False)
    a = np.clip(t / max(attack, 1e-4), 0, 1)
    return a * np.exp(-decay * t)


def gong(dur=1.6):
    n = int(SR * dur)
    t = np.arange(n) / SR
    f0 = 110 * (1 + 0.06 * np.exp(-8 * t))          # лёгкое понижение тона
    y = np.zeros(n)
    for k, (ratio, amp, dec) in enumerate([(1, 1.0, 2.2), (2.76, .55, 3.4), (5.4, .3, 4.6),
                                          (8.9, .18, 6.0), (13.3, .1, 7.5)]):
        y += amp * np.sin(2 * np.pi * f0 * ratio * t) * np.exp(-dec * t)
    y += 0.25 * np.random.default_rng(1).normal(0, 1, n) * np.exp(-25 * t)   # удар молота
    return y * env(n, 0.002, 0.4)


def hit(dur=0.5, pitch=70):
    n = int(SR * dur)
    rng = np.random.default_rng(2)
    t = np.arange(n) / SR
    thump = np.sin(2 * np.pi * pitch * (1 + 0.5 * np.exp(-30 * t)) * t) * np.exp(-14 * t)
    slap = rng.normal(0, 1, n) * np.exp(-45 * t)
    y = 1.0 * thump + 0.6 * slap
    return np.tanh(2.2 * y) * 0.9


def boom(dur=1.2):
    n = int(SR * dur)
    rng = np.random.default_rng(3)
    t = np.arange(n) / SR
    y = np.sin(2 * np.pi * 45 * (1 + 0.4 * np.exp(-12 * t)) * t) * np.exp(-5 * t)
    y += 0.5 * rng.normal(0, 1, n) * np.exp(-9 * t)
    y = np.convolve(y, np.ones(24) / 24, mode='same')       # глухость взрыва
    return np.tanh(1.6 * y)


def whoosh(dur=0.7):
    n = int(SR * dur)
    rng = np.random.default_rng(4)
    t = np.linspace(0, 1, n, endpoint=False)
    noise = rng.normal(0, 1, n)
    # полосовой «свист»: перемножаем шум на быстро меняющуюся синусоиду
    sweep = np.sin(2 * np.pi * (300 + 1800 * t ** 1.6) * t)
    y = noise * 0.5 + sweep * 0.5
    y = np.convolve(y, np.ones(8) / 8, mode='same')
    return y * np.sin(np.pi * t) ** 1.4


def laugh(dur=1.1):
    """«Ха-ха-ха» — серия коротких выдохов с формантой, не голос."""
    n = int(SR * dur)
    y = np.zeros(n)
    rng = np.random.default_rng(5)
    f = 160 + 40 * np.sin(2 * np.pi * 3 * np.arange(n) / SR)
    base = np.sin(2 * np.pi * f * np.arange(n) / SR) * 0.6
    base += np.sin(2 * np.pi * f * 2.4 * np.arange(n) / SR) * 0.3
    base += rng.normal(0, 1, n) * 0.12
    pulses = 5
    for i in range(pulses):
        start = int(n * (i / pulses) * 0.92)
        ln = int(SR * 0.09)
        seg = base[start:start + ln]
        if len(seg) == 0:
            continue
        e = np.exp(-np.linspace(0, 4.5, len(seg)))
        y[start:start + len(seg)] += seg * e
    return np.tanh(1.5 * y)


def slap(dur=0.35):
    n = int(SR * dur)
    rng = np.random.default_rng(6)
    t = np.arange(n) / SR
    y = rng.normal(0, 1, n) * np.exp(-60 * t)
    y += np.sin(2 * np.pi * 190 * t) * np.exp(-28 * t) * 0.6
    y = np.diff(y, prepend=0)          # «щёлк» — высокие частоты
    return y * 0.8


SOUNDS = {'gong': gong(), 'hit': hit(), 'boom': boom(), 'whoosh': whoosh(),
          'laugh': laugh(), 'slap': slap()}


def write_wav(path, y):
    y = np.asarray(y, dtype=np.float64)
    peak = float(np.max(np.abs(y))) or 1.0
    y = y / peak * 0.85
    data = (y * 32767).astype('<i2').tobytes()
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for name, y in SOUNDS.items():
        p = os.path.join(OUT, name + '.wav')
        write_wav(p, y)
        print(f'{name:8s} {len(y) / SR:.2f} с · {os.path.getsize(p) // 1024} КБ · {p}')
    total = sum(os.path.getsize(os.path.join(OUT, n + '.wav')) for n in SOUNDS)
    print(f'всего {total / 1024:.0f} КБ')
