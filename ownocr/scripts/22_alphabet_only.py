#!/usr/bin/env python3
"""Чтец, обученный ТОЛЬКО алфавиту: проверка на шрифтах, которых он не видел.

Вопрос из постановки: можно ли научить «как применять алфавит к незнакомому
шрифту», а не «читать этот конкретный шрифт». Проверка честная: часть шрифтов в
обучение не попадает вообще, и на них меряется точность по буквам.

Три подхода на одних и тех же отложенных шрифтах:

  1. **шаблоны** (`ownocr/archaeologist.py`) — сравнение формы глифа с
     библиотекой начертаний, без обучения: 26 %;
  2. **вложение** — маленькая свёрточная сеть, обученная на 109 буквах в 50
     начертаниях, применяется к незнакомым;
  3. **сравнение с обученным чтецом** — сколько даёт уже имеющаяся модель,
     дообученная на домене.

    python3 scripts/22_alphabet_only.py --epochs 8 --holdout-fonts 6
"""
import argparse
import glob
import os
import sys
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ownocr.eslav as E                                        # noqa: E402
import ownocr.archaeologist as A                                # noqa: E402

S = 32


def render(ch: str, font, px: int) -> np.ndarray | None:
    from PIL import Image, ImageDraw, ImageFont
    try:
        f = ImageFont.truetype(font, px)
    except Exception:
        return None
    img = Image.new('L', (px * 3, px * 3), 255)
    ImageDraw.Draw(img).text((px // 2, px // 2), ch, font=f, fill=0)
    arr = np.asarray(img)
    ink = arr < 200
    if ink.sum() < 10:
        return None
    ys, xs = np.where(ink)
    crop = arr[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    # в квадрат с сохранением пропорций мышления не берём: у букв важна ширина
    h, w = crop.shape
    k = min(S / h, S / w)
    im = cv2.resize(crop, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
    canvas = np.full((S, S), 255, np.uint8)
    canvas[(S - im.shape[0]) // 2:(S - im.shape[0]) // 2 + im.shape[0],
           (S - im.shape[1]) // 2:(S - im.shape[1]) // 2 + im.shape[1]] = im
    return canvas


def augment(img: np.ndarray, rng) -> np.ndarray:
    g = img.astype(np.float32)
    if rng.random() < 0.7:                       # размытие — как на манге
        g = cv2.GaussianBlur(g, (0, 0), float(rng.uniform(0.4, 1.3)))
    if rng.random() < 0.5:                       # жирнее/тоньше
        k = int(rng.integers(1, 3))
        g = cv2.erode(g if rng.random() < 0.5 else 255 - g, np.ones((k, k), np.uint8))
        if not np.issubdtype(g.dtype, np.floating):
            g = g.astype(np.float32)
    if rng.random() < 0.6:                       # сдвиг и лёгкий поворот
        M = cv2.getRotationMatrix2D((S / 2, S / 2), float(rng.uniform(-8, 8)), 1.0)
        M[0, 2] += rng.uniform(-2, 2); M[1, 2] += rng.uniform(-2, 2)
        g = cv2.warpAffine(g, M, (S, S), borderValue=255)
    if rng.random() < 0.5:                       # контраст
        g = np.clip((g - 127.5) * float(rng.uniform(0.7, 1.4)) + 127.5, 0, 255)
    g = g + rng.normal(0, float(rng.uniform(0, 8)), g.shape)
    return np.clip(g, 0, 255)


def build_dataset(fonts, letters, rng, copies=12, pxs=(18, 24, 30, 38)):
    X, y = [], []
    for path in fonts:
        for ch in letters:
            for px in pxs:
                base = render(ch, path, px)
                if base is None:
                    continue
                for _ in range(copies):
                    X.append(augment(base, rng))
                    y.append(E.LETTERS.index(ch))
    X = np.stack(X)[:, None].astype(np.float32) / 255.0
    return X, np.array(y, np.int64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=8)
    ap.add_argument('--holdout-fonts', type=int, default=6)
    ap.add_argument('--copies', type=int, default=12)
    ap.add_argument('--out', default=os.path.join(ROOT, 'out', 'alphabet-only.pt'))
    a = ap.parse_args()

    import torch
    import torch.nn as nn
    torch.manual_seed(1)
    rng = np.random.default_rng(1)

    allf = A.font_paths()
    held = allf[:a.holdout_fonts]
    train_f = [p for p in allf if p not in held]
    print(f'начертаний в обучении {len(train_f)} · отложено {len(held)}: '
          f'{[os.path.basename(p) for p in held]}')

    t0 = time.time()
    X, y = build_dataset(train_f, E.LETTERS, rng, copies=a.copies)
    print(f'примеров {X.shape[0]} за {time.time() - t0:.0f} с')

    class Net(nn.Module):
        def __init__(self, n):
            super().__init__()
            self.f = nn.Sequential(
                nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2),
                nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(), nn.MaxPool2d(2),
                nn.Flatten(),
                nn.Linear(128 * 4 * 4, 256), nn.ReLU(), nn.Dropout(0.3),
                nn.Linear(256, n),
            )

        def forward(self, x):
            return self.f(x)

    net = Net(len(E.LETTERS))
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=a.epochs)
    lossf = nn.CrossEntropyLoss()
    Xt = torch.from_numpy(X)
    yt = torch.from_numpy(y)
    n = len(Xt)
    for ep in range(a.epochs):
        net.train()
        perm = torch.randperm(n)
        tot = 0.0
        for i in range(0, n, 256):
            idx = perm[i:i + 256]
            opt.zero_grad()
            out = net(Xt[idx])
            loss = lossf(out, yt[idx])
            loss.backward()
            opt.step()
            tot += float(loss) * len(idx)
        sch.step()
        print(f'эпоха {ep + 1}: loss {tot / n:.3f}', flush=True)

    torch.save(net.state_dict(), a.out)

    # ── замер на незнакомых шрифтах ───────────────────────────────────────────
    net.eval()
    right = total = 0
    per_font = {}
    with torch.no_grad():
        for path in held:
            r_ = t_ = 0
            for ch in E.LETTERS:
                for px in (22, 28):
                    img = render(ch, path, px)
                    if img is None:
                        continue
                    x = torch.from_numpy(img[None, None].astype(np.float32) / 255.0)
                    pred = int(net(x).argmax())
                    t_ += 1
                    r_ += int(E.LETTERS[pred] == ch)
            per_font[os.path.basename(path)] = (r_, t_)
            right += r_
            total += t_
    print(f'\nна незнакомых начертаниях точность по буквам: '
          f'{100 * right / max(1, total):.1f} % ({right}/{total})')
    for f, (r, t) in per_font.items():
        print(f'  {f:28s} {100 * r / max(1, t):5.1f} %')


if __name__ == '__main__':
    main()
