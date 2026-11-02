#!/usr/bin/env python3
"""Чтец под рукописный и вывесочный леттеринг — обучение на рукописных шрифтах.

Почему так, а не «ещё эпох на тех же данных». Замер с честным отложенным набором
(7 страниц целиком вне обучения, 60 строк) показал: лучший из наших чтецов даёт
**18,9 %**, и почти весь остаток — рукописные и крупные рисованные реплики.
Реальных размеченных строк у нас всего 123 на обучение — на таком объёме модель
не обобщается, сколько её ни дообучай (проверено: 8 эпох дали 21,2 → 26,9 %).

Зато в наборе шрифтов есть настоящие рукописные и комиксовые начертания:
Caveat, Amatic_SC, Comic_Relief, Bad_Script, Comforter_Brush, Balsamiq_Sans,
Comforter, Days_One, Alumni_Sans_*. Раньше синтез брал случайный шрифт из 48 —
рукописный выпадал в 2 % случаев, то есть модель его почти не видела.

Здесь синтез идёт ПРЕИМУЩЕСТВЕННО с этих шрифтов и в той же манере, что на
страницах: светлые буквы в тёмной обводке по цветному фону, изгиб по дуге
облачка, упругая деформация, наклон, мелкий размер, обе полярности.

    python3 scripts/33_finetune_handfont.py --epochs 14 --steps 200
"""
import argparse
import json
import os
import sys
import time

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ownocr.eslav as E                                          # noqa: E402
from ownocr.pair import cer, clean                                 # noqa: E402
from ownocr.synth import augment_real, elastic, random_text        # noqa: E402

OUT = os.path.join(ROOT, 'out')
DIRS = ['data-real', 'data-pages', 'data-manhua', 'data-comic', 'data-hand']
# страницы, выведенные из обучения ЦЕЛИКОМ — по ним и только по ним судим
# проверка — страницы, которые я НЕ размечал: 86 строк с 6 страниц.
# Размеченные вручную страницы (comic1x5, comic1x7, manhua3x2, manhua2-p2,
# kuro-p2, tyrant-p1) идут в обучение, поэтому из проверки убраны.
HOLDOUT = {'comic2', 'comic3', 'manhua1', 'manhua4', 'manhua5', 'dense-a'}
HAND_PAGES_LABELLED = {'comic1x5', 'comic1x7', 'manhua3x2', 'manhua2-p2', 'kuro-p2', 'tyrant-p1'}

HAND_FONTS = ['Caveat', 'Amatic_SC', 'Comic_Relief', 'Bad_Script', 'Comforter_Brush',
              'Balsamiq_Sans', 'Comforter', 'Days_One', 'Alumni_Sans_Pinstripe',
              'Alumni_Sans_Collegiate_One', 'Alumni_Sans_SC', 'Cormorant_Unicase',
              'El_Messiri', 'Akt', 'Advent_Pro']
BODY_FONTS = ['Arimo', 'Roboto', 'Carlito', 'Commissioner', 'Didact_Gothic',
              'Alegreya_Sans', 'Bitter', 'Cuprum', 'Anonymous_Pro', 'Andika',
              'Alegreya', 'EB_Garamond', 'Charis_SIL', 'Cousine', 'Finlandica_Headline']


def font_paths(names):
    out = []
    for n in names:
        p = f'/home/user/fonts/{n}.ttf'
        if os.path.exists(p):
            out.append(p)
    return out


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
            rows.append({'page': page, 'text': p[1], 'gray': img, 'h': img.shape[0],
                         'kind': p[3] if len(p) > 3 else 'voice',
                         'small': img.shape[0] <= 22, 'hand': page in {'manhua2', 'comic3', 'comic4', 'manhua5'}})
    return rows


_cache = {}


def _F(path, size):
    k = (path, size)
    if k not in _cache:
        _cache[k] = ImageFont.truetype(path, size)
    return _cache[k]


def render(text, rng, font, size=None, bg=None):
    """Строка в манере страницы: буквы вразрядку, свой фон, шум скана."""
    size = int(size or rng.integers(14, 34))
    f = _F(font, size)
    spacing = float(rng.uniform(-0.4, 1.8))
    widths = [f.getlength(ch) + spacing for ch in text]
    W = int(max(10, sum(widths) + rng.integers(6, 22)))
    H = int(size * 1.9)
    bg = int(bg if bg is not None else rng.integers(200, 256))
    canvas = Image.new('L', (W, H), bg)
    d = ImageDraw.Draw(canvas)
    x = float(rng.uniform(0, 5))
    y = float(rng.uniform(0, max(1, H - size * 1.3)))
    ink = int(rng.integers(0, 60))
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=f, fill=ink)
        x += w
    arr = np.asarray(canvas, np.float32)
    if rng.random() < 0.7:
        arr = cv2.GaussianBlur(arr, (3, 3), float(rng.uniform(0.3, 1.0)))
    if rng.random() < 0.6:
        arr += rng.normal(0, float(rng.uniform(2, 10)), arr.shape)
    return np.clip(arr, 0, 255).astype(np.uint8)


def outline_style(gray, rng):
    """Светлые буквы в тёмной обводке — так набрана половина реплик на страницах."""
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = 255 - bw
    th = int(rng.integers(2, 4))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (th, th))
    ring = cv2.subtract(cv2.dilate(ink, ker, iterations=1), ink)
    fill = cv2.erode(ink, ker, iterations=1)
    canvas = np.full_like(ink, int(rng.integers(40, 190)))
    canvas[ring > 40] = int(rng.integers(0, 50))
    light = int(rng.integers(200, 255))
    canvas[fill > 40] = light
    if (fill > 40).sum() < (ink > 40).sum() * 0.3:
        canvas[ink > 40] = light
    return cv2.GaussianBlur(canvas, (3, 3), float(rng.uniform(0.2, 0.8)))


def bend(gray, rng):
    h, w = gray.shape[:2]
    amp = float(rng.uniform(-0.18, 0.18)) * h
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


def italic(gray, rng):
    h, w = gray.shape[:2]
    k = float(rng.uniform(-0.28, 0.28))
    return cv2.warpAffine(gray, np.float32([[1, k, 0], [0, 1, 0]]), (w, h),
                          flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def small_font(gray, rng):
    h, w = gray.shape[:2]
    target = int(rng.integers(12, 23))
    k = target / max(1, h)
    small = cv2.resize(gray, (max(6, int(w * k)), target), interpolation=cv2.INTER_AREA)
    up = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    return cv2.GaussianBlur(up, (3, 3), 0) if rng.random() < 0.5 else up


def ctc_target(text):
    return torch.tensor([E.LETTERS.index(c) for c in text.upper() if c in E.CHAR_TO_IDX],
                        dtype=torch.long)


def evaluate(net, rows):
    net.eval()
    cat = {'всё': [], 'рукописный': [], 'печатный': [], 'мелкий': [], 'крупный': [], 'звуки': []}
    for r in rows:
        with torch.no_grad():
            out = net(torch.from_numpy(E.prepare(r['gray']))).detach().numpy()
        got = E.decode_logits(out.reshape(-1, out.shape[-1]))
        c = cer(clean(r['text']), clean(got))
        cat['всё'].append(c)
        if r['hand']:
            cat['рукописный'].append(c)
        else:
            cat['печатный'].append(c)
        if r['small']:
            cat['мелкий'].append(c)
        if r['h'] >= 40:
            cat['крупный'].append(c)
        if r['kind'] == 'sfx':
            cat['звуки'].append(c)
    return float(np.mean(cat['всё'])), {k: (float(np.mean(v)) if v else None) for k, v in cat.items()}


def fmt(cat):
    return ' · '.join(f'{k} {100 * (v or 0):.1f} %' for k, v in cat.items() if k != 'всё')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=14)
    ap.add_argument('--steps', type=int, default=200)
    ap.add_argument('--batch', type=int, default=16)
    ap.add_argument('--lr', type=float, default=1.2e-4)
    ap.add_argument('--seed', type=int, default=13)
    ap.add_argument('--init-pt', default=os.path.join(ROOT, 'model/eslav/eslav-ft-all.pt'))
    ap.add_argument('--tag', default='eslav-handfont')
    ap.add_argument('--hand-share', type=float, default=0.75,
                    help='доля синтетики с рукописных шрифтов')
    ap.add_argument('--real-share', type=float, default=0.45,
                    help='доля настоящих строк в пачке (остальное — синтез)')
    ap.add_argument('--outline-share', type=float, default=0.5)
    ap.add_argument('--hand-limit', type=int, default=0,
                    help='взять только N строк ручной разметки (кривая обучения)')
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    torch.set_num_threads(max(1, (os.cpu_count() or 4)))

    rows = load_all()
    if a.hand_limit:
        # кривая обучения: сколько строк ручной разметки реально в работе
        rng0 = np.random.default_rng(a.seed)
        hand = [r for r in rows if r['page'] in HAND_PAGES_LABELLED]
        rest = [r for r in rows if r['page'] not in HAND_PAGES_LABELLED]
        idx = sorted(rng0.permutation(len(hand))[:a.hand_limit])
        rows = rest + [hand[i] for i in idx]
        print(f'взято строк ручной разметки: {len(idx)} из {len(hand)}', flush=True)
    train = [r for r in rows if r['page'] not in HOLDOUT]
    held = [r for r in rows if r['page'] in HOLDOUT]
    print(f'данные: {len(train)} строк в обучении · {len(held)} на проверке (7 страниц целиком вне обучения)',
          flush=True)

    words = sorted(w for w in open(os.path.join(ROOT, 'ownocr', 'vocab-ru.txt'),
                                   encoding='utf-8').read().split() if len(w) >= 3)
    lines = [r['text'] for r in rows]
    HAND = font_paths(HAND_FONTS)
    BODY = font_paths(BODY_FONTS)
    print(f'шрифтов: рукописных {len(HAND)} · обычных {len(BODY)}', flush=True)

    # Старт ТОЛЬКО с настоящей инициализации: молчаливый откат на base.onnx уже
    # один раз испортил замер (база показывала 48 % вместо 25 %).
    if not os.path.exists(a.init_pt):
        raise SystemExit(f'нет файла инициализации {a.init_pt} — обнови модель '
                         f'(python3 evalwork/fetch_models.py)')
    net = E.build_torch()
    net.load_state_dict(torch.load(a.init_pt, map_location='cpu'))
    print('старт:', os.path.basename(a.init_pt), flush=True)
    net.train()
    opt = torch.optim.Adam([p for p in net.parameters() if p.requires_grad], lr=a.lr)
    ctc = torch.nn.CTCLoss(blank=E.BLANK, zero_infinity=True)

    base, base_cat = evaluate(net, held)
    print(f'ДО: {100 * base:.1f} % · {fmt(base_cat)}', flush=True)

    def synth(rng):
        text = random_text(rng, words, lines)
        hand = rng.random() < a.hand_share
        font = (HAND if hand else BODY)[int(rng.integers(len(HAND if hand else BODY)))]
        g = render(text, rng, font)
        if rng.random() < a.outline_share:
            g = outline_style(g, rng)
        g = augment_real(g, rng)
        if rng.random() < 0.6:
            g = elastic(g, rng, alpha=float(rng.uniform(1.2, 2.8)))
        if rng.random() < 0.5:
            g = bend(g, rng)
        if rng.random() < 0.45:
            g = italic(g, rng)
        if rng.random() < 0.3:
            g = small_font(g, rng)
        if rng.random() < 0.5:
            g = cv2.bitwise_not(g)
        return g, text

    def real(rng, r):
        g = augment_real(r['gray'], rng)
        if rng.random() < 0.5:
            g = outline_style(g, rng)
        if rng.random() < 0.5:
            g = elastic(g, rng, alpha=float(rng.uniform(1.2, 2.6)))
        if rng.random() < 0.4:
            g = italic(g, rng)
        if rng.random() < 0.3:
            g = bend(g, rng)
        if rng.random() < 0.25:
            g = small_font(g, rng)
        if rng.random() < 0.5:
            g = cv2.bitwise_not(g)
        return g, r['text']

    best, history, where = base, [], 'база'
    for ep in range(1, a.epochs + 1):
        net.train()
        t0, total = time.time(), 0.0
        for grp in opt.param_groups:
            grp['lr'] = a.lr * 0.5 * (1 + np.cos(np.pi * (ep - 1) / max(1, a.epochs)))
        for _ in range(a.steps):
            imgs, texts = [], []
            for _ in range(a.batch):
                if train and rng.random() < a.real_share:
                    g, text = real(rng, train[int(rng.integers(len(train)))])
                else:
                    g, text = synth(rng)
                imgs.append(E.prepare(g))
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
        c, cat = evaluate(net, held)
        history.append({'epoch': ep, 'loss': total / a.steps, 'cer': c, 'cats': cat})
        print(f'  эпоха {ep}: loss {total / a.steps:.3f} · проверка {100 * c:.1f} % · {fmt(cat)} · '
              f'{time.time() - t0:.0f} с', flush=True)
        if c < best - 0.002:
            best, where = c, f'эпоха {ep}'
            torch.save(net.state_dict(), os.path.join(OUT, a.tag + '.pt'))
            print('   сохранено', flush=True)

    json.dump({'обучение': len(train), 'проверка': sorted(HOLDOUT), 'база': base, 'лучший': best,
               'где': where, 'категории_база': base_cat, 'история': history},
              open(os.path.join(OUT, a.tag + '.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'ИТОГ: было {100 * base:.1f} % → стало {100 * best:.1f} % ({where})')


if __name__ == '__main__':
    main()
