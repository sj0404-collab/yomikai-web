#!/usr/bin/env python3
"""Чтец под один жанр: обучаем отдельно на вебтуне (манхва+маньхуа) и на комиксе.

Зачем отдельный скрипт: у жанров разные шрифты, и замер это уже показал — чтец,
обученный на манге, на манхве даёт 29,8 % (хуже приложения), а на манге 1,1 %.
Значит нужен свой чтец на жанр, а не один на всё.

    python3 scripts/29_finetune_genre.py --name webtoon \
        --train tyrant-p1,manhua1,manhua2,manhua4 --eval manhua5,reader-p1 --epochs 6
"""
import argparse
import json
import os
import sys
import time

import cv2
import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ownocr.eslav as E                                     # noqa: E402
from ownocr.pair import cer, clean                            # noqa: E402
from ownocr.synth import augment_real, elastic, random_text, render_line  # noqa: E402

OUT = os.path.join(ROOT, 'out')
DIRS = ['data-real', 'data-pages', 'data-manhua', 'data-comic']


def load_all():
    rows = []
    for d in DIRS:
        path = os.path.join(ROOT, d, 'labels.tsv')
        if not os.path.exists(path):
            continue
        for line in open(path, encoding='utf-8'):
            p = line.rstrip('\n').split('\t')
            img = cv2.imread(os.path.join(ROOT, d, p[0]), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                rows.append({'page': p[2] if len(p) > 2 else d, 'text': p[1], 'gray': img})
    return rows


def ctc_target(text: str):
    # 0-based: иначе CTC получает метки со сдвигом и модель разваливается
    return torch.tensor([E.LETTERS.index(c) for c in text.upper() if c in E.CHAR_TO_IDX],
                        dtype=torch.long)


def evaluate(net, rows):
    net.eval()
    per = {}
    for r in rows:
        x = E.prepare(r['gray'])
        with torch.no_grad():
            out = net(torch.from_numpy(x)).numpy()
        got = E.decode_logits(out.reshape(-1, out.shape[-1]))
        d = per.setdefault(r['page'], {'cers': [], 'exact': 0, 'n': 0, 'rows': []})
        c = cer(clean(r['text']), clean(got))
        d['cers'].append(c)
        d['exact'] += int(clean(r['text']) == clean(got))
        d['n'] += 1
        if len(d['rows']) < 3:
            d['rows'].append({'ref': r['text'], 'got': got})
    allc = []
    for d in per.values():
        d['cer'] = float(np.mean(d['cers']))
        allc += d['cers']
    return float(np.mean(allc)), per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', required=True, help='манхва/вебтун/комикс — для имён файлов')
    ap.add_argument('--train', required=True, help='страницы обучения через запятую')
    ap.add_argument('--eval', required=True, help='страницы проверки через запятую')
    ap.add_argument('--epochs', type=int, default=6)
    ap.add_argument('--steps', type=int, default=120)
    ap.add_argument('--batch', type=int, default=16)
    ap.add_argument('--lr', type=float, default=2e-4)
    ap.add_argument('--seed', type=int, default=5)
    ap.add_argument('--init-pt', default=os.path.join(ROOT, 'model/eslav/eslav-ft-all.pt'),
                    help='с чего начинать: .pt общего чтеца (перенос знаний по жанрам)')
    ap.add_argument('--real-share', type=float, default=0.7)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    torch.set_num_threads(max(1, (os.cpu_count() or 4)))

    rows = load_all()
    train_pages = a.train.split(',')
    eval_pages = a.eval.split(',')
    train = [r for r in rows if r['page'] in train_pages]
    held = [r for r in rows if r['page'] in eval_pages]
    start = os.path.basename(a.init_pt) if os.path.exists(a.init_pt) else 'base.onnx (без переноса)'
    print(f'{a.name}: обучение {len(train)} строк ({train_pages}) · проверка {len(held)} '
          f'({eval_pages}) · старт: {start}', flush=True)

    words = sorted(w for w in open(os.path.join(ROOT, 'ownocr', 'vocab-ru.txt'),
                                   encoding='utf-8').read().split() if len(w) >= 3)
    lines = [r['text'] for r in rows]

    net = E.build_torch()                      # всегда из base.onnx: имена весов совпадают
    if os.path.exists(a.init_pt):
        net.load_state_dict(torch.load(a.init_pt, map_location='cpu'))
    net.train()
    opt = torch.optim.Adam([p for p in net.parameters() if p.requires_grad], lr=a.lr)
    ctc = torch.nn.CTCLoss(blank=E.BLANK, zero_infinity=True)

    base_cer, base_pages = evaluate(net, held)
    print(f'ДО: {100 * base_cer:.1f} % · ' + ' · '.join(
        f'{p} {100 * d["cer"]:.1f} %' for p, d in base_pages.items()), flush=True)
    best, history = base_cer, []
    tag = f'eslav-{a.name}'
    for ep in range(1, a.epochs + 1):
        net.train()
        t0, total = time.time(), 0.0
        for g in opt.param_groups:
            g['lr'] = a.lr * 0.5 * (1 + np.cos(np.pi * (ep - 1) / max(1, a.epochs)))
        for _ in range(a.steps):
            imgs, texts = [], []
            for _ in range(a.batch):
                if train and rng.random() < a.real_share:
                    r = train[int(rng.integers(len(train)))]
                    gimg = augment_real(r['gray'], rng)
                    if rng.random() < 0.5:
                        gimg = cv2.bitwise_not(gimg)   # вебтун часто светлым по тёмному
                    imgs.append(E.prepare(gimg))
                    texts.append(r['text'])
                else:
                    text = random_text(rng, words, lines)
                    imgs.append(E.prepare(render_line(text, rng)))
                    texts.append(text)
            width = max(i.shape[-1] for i in imgs)
            batch = np.full((len(imgs), 1, 32, width), -1.0, np.float32)
            for i, im in enumerate(imgs):
                batch[i, :, :, :im.shape[-1]] = im
            logits = net(torch.from_numpy(batch)).log_softmax(2)
            tg = [ctc_target(t) for t in texts]
            loss = ctc(logits, torch.cat(tg),
                       torch.full((len(imgs),), logits.shape[0], dtype=torch.long),
                       torch.tensor([len(t) for t in tg], dtype=torch.long))
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
            opt.step()
            total += float(loss.detach())
        cer_all, per = evaluate(net, held)
        history.append({'epoch': ep, 'loss': total / a.steps, 'cer': cer_all,
                        'pages': {p: d['cer'] for p, d in per.items()}})
        print(f'  эпоха {ep}: loss {total / a.steps:.3f} · ' + ' · '.join(
            f'{p} {100 * d["cer"]:.1f} %' for p, d in per.items())
            + f' · среднее {100 * cer_all:.1f} % · {time.time() - t0:.0f} с', flush=True)
        if cer_all < best - 0.002:
            best = cer_all
            torch.save(net.state_dict(), os.path.join(OUT, tag + '.pt'))
            print('   сохранено', flush=True)

    json.dump({'жанр': a.name, 'обучение': train_pages, 'проверка': eval_pages,
               'строк': {'обучение': len(train), 'проверка': len(held)},
               'старт': start, 'база_cer': base_cer, 'лучший_cer': best,
               'история': history}, open(os.path.join(OUT, tag + '.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(f'ИТОГ {a.name}: было {100 * base_cer:.1f} % → стало {100 * best:.1f} %')


if __name__ == '__main__':
    main()
