"""Обучение распознавателя строк (CTC) — на синтетике или на своей разметке.

Примеры:
  # тренировочная площадка: 6 эпох по 800 строк, ~5 минут на 2 ядрах CPU
  python3 tools/train_rec.py --steps 800 --epochs 6 --out runs/bench.pt

  # на своей разметке (кропы строк из манги): каталог + labels.tsv «путь<TAB>текст»
  python3 tools/train_rec.py --crops data/lines --labels data/labels.tsv \\
      --steps 2000 --epochs 20 --out runs/manga.pt

Чего здесь НЕТ и почему: GPU-обучения. В песочнице и на раннере GitHub Actions
только CPU; большая модель koma_rec (7,9 МБ) на CPU учится сутками. Эта модель
(≈1,0 млн параметров) за минуты доходит до читаемых строк — её и тренируем.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import Dataset

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from charset import cer, char_to_class, classes_to_text, load_charset, num_classes  # noqa: E402
from model import RecCTC, apply_class_prior                                                                  # noqa: E402
import synth                                                                              # noqa: E402

H = 48
MAX_W = 640


# ── данные ───────────────────────────────────────────────────────────────────
class SynthLines(Dataset):
    """Бесконечная синтетика: одна строка = один seed, поэтому выборка воспроизводима."""

    def __init__(self, length: int, seed: int, words: list, charset: str,
                 hard: float = 0.35, max_chars: int = 16, pad_choices=None,
                 strength: float = 1.0):
        self.length = length
        self.seed = seed
        self.renderer = synth.LineRenderer(words, charset, hard=hard, max_chars=max_chars,
                                           pad_choices=pad_choices, strength=strength)
        self.epoch = 0

    def __len__(self):
        return self.length

    def __getitem__(self, i):
        rng = random.Random(self.seed * 1_000_003 + self.epoch * 7919 + i)
        x, text = self.renderer.sample(rng)
        return torch.from_numpy(x), text


class CropLines(Dataset):
    """Настоящие кропы строк: images/*.png + labels.tsv «путь<TAB>текст»."""

    def __init__(self, root: str, labels: str, charset: str, keep=None):
        self.root = root
        self.items = []
        with open(labels, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or "\t" not in line:
                    continue
                p, t = line.split("\t", 1)
                self.items.append((os.path.join(root, p), t))
        if keep is not None:                 # делим разметку: train / val
            self.items = [it for i, it in enumerate(self.items) if keep(i)]
        if not self.items:
            raise SystemExit(f"{labels}: пусто, нужен формат «путь<TAB>текст»")
        self.allowed = set(charset)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        path, text = self.items[i]
        im = Image.open(path).convert("L")
        w = max(8, round(im.width * H / im.height))
        w = min(MAX_W, max(32, (w + 7) // 8 * 8))
        im = im.resize((w, H), Image.BICUBIC)
        arr = np.asarray(im, dtype=np.float32)
        canvas = np.full((H, MAX_W), synth.GRAY_PAD, dtype=np.float32)
        canvas[:, :w] = arr
        x = np.repeat(canvas[None], 3, axis=0)
        x = ((x / 255.0 - 0.5) / 0.5).astype(np.float32)
        return torch.from_numpy(x), text


def collate(batch, c2c: dict):
    """Батч: картинки дополняются серым до самой широкой, цели — в плоский список."""
    xs = [b[0] for b in batch]
    w = max(x.shape[2] for x in xs)
    w = (w + 7) // 8 * 8
    out = torch.full((len(xs), 3, H, w), 0.0)      # 0.0 в нормировке = серый 128
    for i, x in enumerate(xs):
        out[i, :, :, :x.shape[2]] = x
    targets, lengths = [], []
    for _, text in batch:
        ids = [c2c[c] for c in text.upper() if c in c2c]
        targets.extend(ids)
        lengths.append(len(ids))
    return out, torch.tensor(targets, dtype=torch.long), torch.tensor(lengths, dtype=torch.long), [b[1] for b in batch]


# ── оценка ───────────────────────────────────────────────────────────────────
@torch.no_grad()
def evaluate(model, loader, charset, c2c):
    model.eval()
    total, n = 0.0, 0
    for x, tgt, tl, texts in loader:
        p = model(x, probabilities=True)
        idx = p.argmax(-1).numpy()
        for row, ref in zip(idx, texts):
            hyp = classes_to_text(charset, row)
            total += cer(ref, hyp) * max(1, len(ref))
            n += max(1, len(ref))
    model.train()
    return total / max(1, n)


# ── обучение ─────────────────────────────────────────────────────────────────
def main(argv=None):
    ap = argparse.ArgumentParser(description="CTC-обучение распознавателя строк")
    ap.add_argument("--steps", type=int, default=800, help="строк за эпоху (синтетика)")
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--val", type=int, default=120, help="строк в проверке")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--threads", type=int, default=0, help="0 — сколько даёт машина")
    ap.add_argument("--hard", type=float, default=0.35, help="доля строк с бликом/заплаткой")
    ap.add_argument("--max-chars", type=int, default=16, help="потолок длины строки")
    ap.add_argument("--pad-choices", default="",
                    help="ширины холста через запятую, напр. 64,96 — для первой ступени")
    ap.add_argument("--strength", type=float, default=1.0,
                    help="сила порчи 0…1 (ступени: 0,25 → 0,6 → 1,0)")
    ap.add_argument("--words", type=int, default=60000, help="сколько слов словаря брать")
    ap.add_argument("--crops", default=None, help="каталог с кропами (вместо синтетики)")
    ap.add_argument("--labels", default=None, help="labels.tsv к --crops")
    ap.add_argument("--out", default="runs/rec.pt")
    ap.add_argument("--resume", default=None)
    ap.add_argument("--no-prior", action="store_true",
                    help="не приглушать классы, которых нет в данных (по умолчанию приглушаем)")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.threads:
        torch.set_num_threads(a.threads)
    torch.manual_seed(a.seed)
    random.seed(a.seed)
    np.random.seed(a.seed)

    charset = load_charset()
    c2c = char_to_class(charset)
    n_cls = num_classes(charset)
    log = (lambda *x: None) if a.quiet else (lambda *x: print(*x, flush=True))

    if a.crops:
        if not a.labels:
            raise SystemExit("--crops требует --labels")
        train = CropLines(a.crops, a.labels, charset, keep=lambda i: i % 10 != 0)
        val = CropLines(a.crops, a.labels, charset, keep=lambda i: i % 10 == 0)
        log(f"данные: настоящие кропы — учу на {len(train)}, проверяю на {len(val)}")
    else:
        words = synth.load_words(a.words)
        pads = [int(v) for v in a.pad_choices.split(",") if v.strip()] or None
        train = SynthLines(a.steps, a.seed, words, charset, hard=a.hard,
                           max_chars=a.max_chars, pad_choices=pads, strength=a.strength)
        val = SynthLines(max(24, a.val), a.seed + 10_000, words, charset,
                         hard=a.hard, max_chars=a.max_chars, pad_choices=pads,
                         strength=a.strength)
        log(f"данные: синтетика из {len(words)} слов словаря")

    from torch.utils.data import DataLoader
    dl = DataLoader(train, batch_size=a.batch, shuffle=False, num_workers=0,
                    collate_fn=lambda b: collate(b, c2c), drop_last=True)
    vdl = DataLoader(val, batch_size=a.batch, shuffle=False, num_workers=0,
                     collate_fn=lambda b: collate(b, c2c))

    model = RecCTC(n_cls)
    used = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ" \
           ".,!?…-—:;()\"0123456789 "         # что вообще бывает в строках
    if not a.no_prior:
        apply_class_prior(model, charset, used)
    opt = torch.optim.AdamW(model.parameters(), lr=a.lr, weight_decay=1e-4)
    ctc = nn.CTCLoss(blank=0, zero_infinity=True)
    start_ep = 0
    if a.resume and os.path.exists(a.resume):
        ck = torch.load(a.resume, map_location="cpu", weights_only=False)
        model.load_state_dict(ck["model"])
        if "opt" in ck:
            opt.load_state_dict(ck["opt"])
            for g in opt.param_groups:      # скорость берём из аргументов, не из файла
                g["lr"] = a.lr
        start_ep = ck.get("epoch", 0)
        log(f"продолжаю с {a.resume}, эпоха {start_ep}")

    n_par = sum(p.numel() for p in model.parameters())
    log(f"модель: {n_par/1e6:.2f} млн параметров · классов {n_cls} · потоков {torch.get_num_threads()}")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    history, best = [], 1e9
    t0 = time.time()

    for ep in range(start_ep, a.epochs):
        if hasattr(train, "epoch"):
            train.epoch = ep          # каждая эпоха — другие порчи тех же слов
        model.train()
        run, seen, t_ep = 0.0, 0, time.time()
        for step, (x, tgt, tl, texts) in enumerate(dl):
            p = model(x, probabilities=False)                     # [N,T,C] логарифмы
            T = p.shape[1]
            in_len = torch.full((x.shape[0],), T, dtype=torch.long)
            loss = ctc(p.transpose(0, 1), tgt, in_len, tl)
            opt.zero_grad()
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            run += float(loss)
            seen += x.shape[0]
            if step % 20 == 19:
                log(f"  эпоха {ep+1} шаг {step+1}: CTC {run/20:.3f} "
                    f"({seen/(time.time()-t_ep):.1f} строк/с)")
                run = 0.0
        vcer = evaluate(model, vdl, charset, c2c)
        history.append({"epoch": ep + 1, "val_cer": round(vcer, 4),
                        "sec": round(time.time() - t_ep, 1)})
        log(f"эпоха {ep+1}: проверка CER {vcer*100:.1f} % · {time.time()-t_ep:.0f} с")
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(),
                    "epoch": ep + 1, "charset": charset, "n_classes": n_cls,
                    "val_cer": vcer, "history": history}, a.out)
        if vcer < best:
            best = vcer
    log(f"готово за {(time.time()-t0)/60:.1f} мин · лучший CER {best*100:.1f} % → {a.out}")
    with open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump({"val_cer": best, "history": history, "params": n_par,
                   "charset": len(charset), "classes": n_cls}, f, ensure_ascii=False, indent=1)
    return best


if __name__ == "__main__":
    main()
