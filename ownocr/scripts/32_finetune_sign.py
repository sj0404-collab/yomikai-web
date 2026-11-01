#!/usr/bin/env python3
"""Дообучение чтеца на ВЫВЕСОЧНЫЙ и КОНТУРНЫЙ леттеринг (реплики манги/комикса).

Почему отдельный прогон. Замер по 183 размеченным строкам показал, где именно чтец
ломается (CER, чтец приложения, без чистки):

    печатный текст   dense-a 0,0 % · reader-p1 2,5 % · comic2 3,9 %
    рукописный       comic4 52 % · comic3 52 % · manhua2 76,9 % · manhua3 87,5 %

Водяной знак переводчика при этом читается почти без ошибок — он набран обычным
печатным шрифтом. Значит проблема не в размере, а в НАЧЕРТАНИИ: реплики
нарисованы вывесочным/рукописным шрифтом, часто светлым по цветному с тёмной
обводкой. Такого в обучении почти не было.

К `hand` из прошлого прогона добавлены аугментации под именно этот вид:

  * `stroke`  — жирный вывесочный штрих (утолщение буквы + размытие края);
  * `outline` — контурная буква: светлая заливка внутри тёмной обводки
                (главный вид, которого не хватало);
  * `italic`  — наклон −16…+16° (рукописные и «комиксовые» шрифты);
  * `bend`    — изгиб строки по дуге облачка;
  * `hand`    — упругое искажение + поворот + сжатие (как в прошлом прогоне);
  * `small_font` — уменьшение до 12–22 px и обратно;
  * обе полярности (светлое по тёмному и наоборот).

Настоящие кропы (все размеченные страницы) остаются основной массой — иначе
печатный текст, который сейчас читается на 0–3 %, поедет вниз.

    python3 scripts/32_finetune_sign.py --epochs 8 --steps 160 \
        --eval-pages comic3,manhua5 --tag eslav-sign
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
import ownocr.eslav as E                                          # noqa: E402
from ownocr.pair import cer, clean                                 # noqa: E402
from ownocr.synth import augment_real, elastic, random_text, render_line  # noqa: E402

OUT = os.path.join(ROOT, 'out')
DIRS = ['data-real', 'data-pages', 'data-manhua', 'data-comic']
# страницы с рукописным/рисованным шрифтом — по ним видно, помогло ли
HAND_PAGES = {'manhua2', 'comic3', 'comic4', 'manhua5'}


def load_all():
    rows = []
    for d in DIRS:
        path = os.path.join(ROOT, d, 'labels.tsv')
        if not os.path.exists(path):
            continue
        for line in open(path, encoding='utf-8'):
            p = line.rstrip('\n').split('\t')
            img = cv2.imread(os.path.join(ROOT, d, p[0]), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            page = p[2] if len(p) > 2 else d
            kind = p[3] if len(p) > 3 else 'voice'
            rows.append({'page': page, 'text': p[1], 'kind': kind, 'gray': img,
                         'h': img.shape[0],
                         'small': img.shape[0] <= 22,
                         'hand': page in HAND_PAGES})
    return rows


def _binary(gray):
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_RGB2GRAY)
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # чернила = тёмное
    ink = 255 - bw
    return ink


def stroke(gray, rng, k=None):
    """Жирный вывесочный штрих: утолщаем чернила и размываем край."""
    ink = _binary(gray)
    k = int(k or rng.integers(2, 4))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    ink = cv2.dilate(ink, ker, iterations=1)
    out = cv2.GaussianBlur(255 - ink, (3, 3), float(rng.uniform(0.4, 1.1)))
    return out


def outline(gray, rng):
    """Контурная буква: светлая заливка внутри тёмной обводки.

    Именно так набрана половина реплик в комиксе и маньхуа: белый текст с чёрной
    каймой по цветному фону. Раньше чтец видел это впервые на странице.
    """
    ink = _binary(gray)
    th = int(rng.integers(2, 4))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (th, th))
    ring = cv2.subtract(cv2.dilate(ink, ker, iterations=1), ink)   # кайма
    fill = cv2.erode(ink, ker, iterations=1)                       # светлая середина
    bg = int(rng.integers(30, 210))
    canvas = np.full_like(ink, bg, dtype=np.uint8)
    canvas = cv2.addWeighted(canvas, 1.0, ink, 0.0, 0)
    canvas[ring > 40] = int(rng.integers(0, 60))                   # тёмная обводка
    light = int(rng.integers(190, 255))
    canvas[fill > 40] = light                                      # светлая заливка
    # если внутренностей не осталось (тонкий шрифт) — заливаем сами чернила
    if (fill > 40).sum() < (ink > 40).sum() * 0.25:
        canvas[ink > 40] = light
    return cv2.GaussianBlur(canvas, (3, 3), float(rng.uniform(0.3, 0.9)))


def italic(gray, rng):
    """Наклон букв — рукописные и «комиксовые» шрифты."""
    h, w = gray.shape[:2]
    k = float(rng.uniform(-0.30, 0.30))
    m = np.float32([[1, k, 0], [0, 1, 0]])
    out = cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)
    return out


def bend(gray, rng):
    """Изгиб строки по дуге облачка: буквы идут волной."""
    h, w = gray.shape[:2]
    amp = float(rng.uniform(-0.16, 0.16)) * h
    xs = np.arange(w, dtype=np.float32)
    shift = amp * np.sin(np.pi * xs / max(1, w - 1))
    out = np.empty_like(gray)
    for x in range(w):
        d = int(round(shift[x]))
        col = gray[:, x]
        if d > 0:
            out[d:, x] = col[:h - d]
            out[:d, x] = col[0]
        elif d < 0:
            out[:h + d, x] = col[-d:]
            out[h + d:, x] = col[-1]
        else:
            out[:, x] = col
    return out


def hand(gray, rng):
    g = elastic(gray, rng, alpha=float(rng.uniform(1.4, 3.0)))
    h, w = g.shape[:2]
    ang = float(rng.uniform(-7, 7))
    m = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    g = cv2.warpAffine(g, m, (w, h), flags=cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REPLICATE)
    sx = float(rng.uniform(0.75, 1.3))
    return cv2.resize(g, (max(8, int(w * sx)), h), interpolation=cv2.INTER_LINEAR)


def small_font(gray, rng):
    h, w = gray.shape[:2]
    target = int(rng.integers(12, 23))
    k = target / max(1, h)
    small = cv2.resize(gray, (max(6, int(w * k)), target), interpolation=cv2.INTER_AREA)
    up = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    if rng.random() < 0.5:
        up = cv2.GaussianBlur(up, (3, 3), 0)
    return up


def ctc_target(text):
    return torch.tensor([E.LETTERS.index(c) for c in text.upper() if c in E.CHAR_TO_IDX],
                        dtype=torch.long)


def evaluate(net, rows):
    net.eval()
    per, cat = {}, {'всё': [], 'мелкий': [], 'рукописный': [], 'звуки': [], 'печатный': []}
    for r in rows:
        with torch.no_grad():
            out = net(torch.from_numpy(E.prepare(r['gray']))).detach().numpy()
        got = E.decode_logits(out.reshape(-1, out.shape[-1]))
        c = cer(clean(r['text']), clean(got))
        d = per.setdefault(r['page'], {'cers': [], 'exact': 0, 'n': 0, 'rows': []})
        d['cers'].append(c)
        d['exact'] += int(clean(r['text']) == clean(got))
        d['n'] += 1
        if len(d['rows']) < 4:
            d['rows'].append({'ref': r['text'], 'got': got})
        cat['всё'].append(c)
        if r['small']:
            cat['мелкий'].append(c)
        if r['hand']:
            cat['рукописный'].append(c)
        else:
            cat['печатный'].append(c)
        if r['kind'] == 'sfx':
            cat['звуки'].append(c)
    allc = []
    for d in per.values():
        d['cer'] = float(np.mean(d['cers']))
        allc += d['cers']
    summary = {k: {'cer': float(np.mean(v)) if v else None, 'n': len(v)} for k, v in cat.items()}
    return float(np.mean(allc)), per, summary


def fmt(summary):
    return (f'мелкий {100 * (summary["мелкий"]["cer"] or 0):.1f} % · '
            f'рукописный {100 * (summary["рукописный"]["cer"] or 0):.1f} % · '
            f'печатный {100 * (summary["печатный"]["cer"] or 0):.1f} % · '
            f'звуки {100 * (summary["звуки"]["cer"] or 0):.1f} %')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=8)
    ap.add_argument('--steps', type=int, default=160)
    ap.add_argument('--batch', type=int, default=16)
    ap.add_argument('--lr', type=float, default=2.2e-4)
    ap.add_argument('--seed', type=int, default=11)
    ap.add_argument('--eval-pages', default='comic3,manhua5')
    ap.add_argument('--init-pt', default=os.path.join(ROOT, 'model/eslav/eslav-ft-all.pt'))
    ap.add_argument('--tag', default='eslav-sign')
    ap.add_argument('--real-share', type=float, default=0.8)
    ap.add_argument('--sign-share', type=float, default=0.5,
                    help='доля строк, которые показываем вывесочными (контур/жирный)')
    ap.add_argument('--hand-share', type=float, default=0.4)
    ap.add_argument('--small-share', type=float, default=0.3)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    torch.set_num_threads(max(1, (os.cpu_count() or 4)))

    rows = load_all()
    eval_pages = [p for p in a.eval_pages.split(',') if p]
    train = [r for r in rows if r['page'] not in eval_pages]
    held = [r for r in rows if r['page'] in eval_pages]
    print(f'данные: {len(train)} строк в обучении · {len(held)} на проверке {eval_pages}', flush=True)
    print('  в обучении: мелких %d · рукописных %d · звуков %d' % (
        sum(1 for r in train if r['small']), sum(1 for r in train if r['hand']),
        sum(1 for r in train if r['kind'] == 'sfx')), flush=True)

    words = sorted(w for w in open(os.path.join(ROOT, 'ownocr', 'vocab-ru.txt'),
                                   encoding='utf-8').read().split() if len(w) >= 3)
    lines = [r['text'] for r in rows]

    net = E.build_torch()
    if os.path.exists(a.init_pt):
        net.load_state_dict(torch.load(a.init_pt, map_location='cpu'))
        print('старт:', os.path.basename(a.init_pt), flush=True)
    net.train()
    opt = torch.optim.Adam([p for p in net.parameters() if p.requires_grad], lr=a.lr)
    ctc = torch.nn.CTCLoss(blank=E.BLANK, zero_infinity=True)

    base, base_pages, base_cat = evaluate(net, held)
    print(f'ДО: {100 * base:.1f} % · {fmt(base_cat)}', flush=True)

    def make(gray):
        """Одна аугментация под вывесочный/рукописный леттеринг."""
        g = augment_real(gray, rng)
        if rng.random() < a.sign_share:
            g = outline(g, rng) if rng.random() < 0.6 else stroke(g, rng)
        if rng.random() < a.hand_share:
            g = hand(g, rng)
        if rng.random() < 0.45:
            g = italic(g, rng)
        if rng.random() < 0.3:
            g = bend(g, rng)
        if rng.random() < a.small_share:
            g = small_font(g, rng)
        if rng.random() < 0.5:
            g = cv2.bitwise_not(g)
        return g

    best, history, where = base, [], 'база'
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
                    gimg = make(r['gray'])
                    imgs.append(E.prepare(gimg))
                    texts.append(r['text'])
                else:
                    text = random_text(rng, words, lines)
                    img = render_line(text, rng)
                    if rng.random() < 0.6:
                        img = outline(img, rng) if rng.random() < 0.6 else stroke(img, rng)
                    if rng.random() < a.hand_share * 0.7:
                        img = hand(img, rng)
                    if rng.random() < 0.4:
                        img = italic(img, rng)
                    if rng.random() < a.small_share:
                        img = small_font(img, rng)
                    if rng.random() < 0.3:
                        img = cv2.bitwise_not(img)
                    imgs.append(E.prepare(img))
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
        c, per, cat = evaluate(net, held)
        history.append({'epoch': ep, 'loss': total / a.steps, 'cer': c,
                        'cats': {k: v['cer'] for k, v in cat.items()},
                        'pages': {p: d['cer'] for p, d in per.items()}})
        print(f'  эпоха {ep}: loss {total / a.steps:.3f} · среднее {100 * c:.1f} % · '
              f'{fmt(cat)} · {time.time() - t0:.0f} с', flush=True)
        if c < best - 0.002:
            best, where = c, f'эпоха {ep}'
            torch.save(net.state_dict(), os.path.join(OUT, a.tag + '.pt'))
            print('   сохранено', flush=True)

    json.dump({'обучение': len(train), 'проверка': eval_pages, 'база': base, 'лучший': best,
               'где': where, 'категории_база': {k: v['cer'] for k, v in base_cat.items()},
               'история': history}, open(os.path.join(OUT, a.tag + '.json'), 'w'),
              ensure_ascii=False, indent=1)
    print(f'ИТОГ: было {100 * base:.1f} % → стало {100 * best:.1f} % ({where})')


if __name__ == '__main__':
    main()
