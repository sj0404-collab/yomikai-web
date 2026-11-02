"""Разметка по облачкам: строка внутри облачка режется тем же алгоритмом, что в приложении.

Зачем так. Рамки детектора на рукописи лежат «лестницей» и перекрываются на 60–75 %,
поэтому размечать по ним — значит класть в обучение обрезанный текст. Зато облачко
детектор находит надёжно. Поэтому:

  1. скрипт собирает рамки в облачка и делает лист для глаз (крупно, читаемо);
  2. я пишу эталон по облачку, строки через «|»;
  3. скрипт режет облачко на строки (проекция чернил — та же логика, что `cutRows`
     в core.js) и раскладывает эталон по строкам;
  4. если число нарезанных строк не совпало с числом строк в эталоне — облачко
     пропускается с предупреждением (лучше меньше данных, чем мусор в обучении).

    python3 evalwork/mklabel2.py prep <имя> <путь.png>     # листы для чтения
    python3 evalwork/mklabel2.py build <имя>                # читает <имя>.gt.txt
"""
import argparse
import json
import os
import subprocess
import sys

import cv2
import numpy as np

WORK = '/home/user/label-work'
DATA = '/home/user/ownocr'


# ---------- шаг 1: облачка ----------
def bubble_groups(boxes):
    """Собрать рамки в облачка: близкие по вертикали и с общим горизонтальным телом."""
    boxes = [b for b in boxes if 6 <= b[3] - b[1] <= 260 and b[2] - b[0] >= 10]
    boxes.sort(key=lambda b: b[1])
    if not boxes:
        return []
    med = float(np.median([b[3] - b[1] for b in boxes]))
    groups = []
    for b in boxes:
        placed = False
        for g in groups:
            u = [min(x[0] for x in g), min(x[1] for x in g),
                 max(x[2] for x in g), max(x[3] for x in g)]
            ox = min(u[2], b[2]) - max(u[0], b[0])
            if ox < 0.25 * min(u[2] - u[0], b[2] - b[0]):
                continue
            gap = b[1] - u[3]
            if -max(med, b[3] - b[1]) <= gap <= med * 0.9:
                g.append(b)
                placed = True
                break
        if not placed:
            groups.append([b])
    return [g for g in groups if len(g) >= 1]


def union(g):
    return (min(b[0] for b in g), min(b[1] for b in g),
            max(b[2] for b in g), max(b[3] for b in g))


def cut_rows_thr(img, box, frac, ink_luma=150):
    """То же, но с заданной долей от максимума чернил (для подбора порога)."""
    global FORCE_FRAC
    old = FORCE_FRAC
    FORCE_FRAC = frac
    try:
        return cut_rows(img, box, ink_luma)
    finally:
        FORCE_FRAC = old


FORCE_FRAC = None


def cut_rows(img, box, ink_luma=150):
    """Проекция чернил по строкам — та же логика, что cutRows в core.js."""
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    pad = max(2, int((y2 - y1) * 0.06))
    l, t = max(0, x1 - pad), max(0, y1 - pad)
    r, b = min(img.shape[1], x2 + pad), min(img.shape[0], y2 + pad)
    if r - l < 6 or b - t < 6:
        return []
    crop = cv2.cvtColor(img[t:b, l:r], cv2.COLOR_BGR2GRAY)
    scale = min(1.0, 600 / max(1, r - l))
    cw, ch = max(8, int((r - l) * scale)), max(6, int((b - t) * scale))
    small = cv2.resize(crop, (cw, ch), interpolation=cv2.INTER_AREA)
    ink = (small < ink_luma).sum(axis=1)
    # фон бывает тёмный (чёрное окно с белыми буквами, синяя плашка): тогда
    # чернила — светлое, и проекция по тёмному даёт одну слитую строку.
    if ink.mean() > cw * 0.35:
        ink = (small > 255 - ink_luma).sum(axis=1)
    mx = max(1, int(ink.max()))
    need = max(2, int(mx * (FORCE_FRAC if FORCE_FRAC else 0.18)))
    runs, y = [], 0
    while y < ch:
        if ink[y] < need:
            y += 1
            continue
        e = y
        while e < ch and ink[e] >= need:
            e += 1
        runs.append([y, e])
        y = max(e, y + 1)
    merged = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= 1:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    # Тонкие горизонтальные линии фона (штриховка, линейки) дают свои полосы.
    # Отбрасываем полосы короче 0.4 медианной — иначе облачко рвётся на куски.
    lens = sorted(r[1] - r[0] for r in merged) or [1]
    med_run = lens[len(lens) // 2]
    out = []
    for y0, y1 in merged:
        if y1 - y0 < 2 or (y1 - y0) < med_run * 0.4:
            continue
        # Отступ по вертикали — 6 % высоты строки: с 2 px верхушки букв и
        # подчёркивания срезались («ТОЧНО» → «ТОЧНО» без хвостов).
        hh = max(2, int(round((y1 - y0) / scale)))
        vp = max(2, int(round(hh * 0.06)))
        ty = max(0, int(round(y0 / scale)) + t - vp)
        by = min(img.shape[0], int(round(y1 / scale)) + t + vp)
        light = ink.mean() > 0 and (small[y0:y1] > 255 - ink_luma).sum() > (small[y0:y1] < ink_luma).sum()
        colmask = (small[y0:y1] > 255 - ink_luma) if light else (small[y0:y1] < ink_luma)
        xs = np.where(colmask.any(axis=0))[0]
        # Горизонтальный отступ — 10 % высоты строки. С прежними 2 px у строк
        # срезалась первая буква: «Я ХОЧУ БЫТЬ» сохранялось как «1 ХОЧУ БЫТЬ»,
        # и модель училась на обрубках.
        hp = max(3, int(round(hh * 0.10)))
        if len(xs) == 0:
            lx, rx = l, r
        else:
            lx = max(0, int(round(xs[0] / scale)) + l - hp)
            rx = min(img.shape[1], int(round(xs[-1] / scale)) + l + hp)
        out.append([lx, ty, rx, by])
    return out


def cmd_prep(name, png, per_sheet=6):
    img = cv2.imread(png)
    if img is None:
        raise SystemExit(f'нет файла {png}')
    h, w = img.shape[:2]
    os.makedirs(WORK, exist_ok=True)
    cv2.cvtColor(img, cv2.COLOR_BGR2RGB).tofile(f'{WORK}/{name}.rgb')
    json.dump({'w': w, 'h': h}, open(f'{WORK}/{name}.json', 'w'))
    res = subprocess.run(['node', '/home/user/evalwork/boxes.js', name],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(res.stderr[-800:])
    boxes = json.loads(res.stdout)
    groups = bubble_groups(boxes)
    print(f'{name}: рамок {len(boxes)} → облачков {len(groups)}')

    os.makedirs(f'{WORK}/sheets', exist_ok=True)
    tiles, meta = [], []
    for i, g in enumerate(groups):
        u = union(g)
        x1, y1, x2, y2 = [int(round(v)) for v in u]
        pad = 12
        crop = img[max(0, y1 - pad):min(h, y2 + pad), max(0, x1 - pad):min(w, x2 + pad)]
        if crop.size == 0:
            continue
        meta.append({'i': i, 'box': list(u), 'h': crop.shape[0], 'w': crop.shape[1]})
        k = 250 / max(1, crop.shape[0])
        view = cv2.resize(crop, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC) \
            if k > 1 else crop.copy()
        if view.shape[1] > 1200:
            k2 = 1200 / view.shape[1]
            view = cv2.resize(view, None, fx=k2, fy=k2, interpolation=cv2.INTER_AREA)
        view = cv2.copyMakeBorder(view, 8, 8, 70, 10, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(view, f'#{i}', (6, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 220), 2)
        nrows = len(cut_rows(img, u))
        cv2.putText(view, f'{nrows}', (6, view.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (0, 140, 0), 2)
        tiles.append(view)

    for s in range(0, len(tiles), per_sheet):
        part = tiles[s:s + per_sheet]
        H = sum(p.shape[0] for p in part)
        W = max(p.shape[1] for p in part)
        sheet = np.full((H, W, 3), 255, np.uint8)
        y = 0
        for p in part:
            sheet[y:y + p.shape[0], :p.shape[1]] = p
            y += p.shape[0]
        path = f'{WORK}/sheets/{name}-b{s // per_sheet + 1}.png'
        cv2.imwrite(path, sheet)
        print('  лист', path, sheet.shape)
    json.dump(meta, open(f'{WORK}/{name}-bubbles.json', 'w'))


# ---------- шаг 3–4: сборка датасета ----------
def widen_to_gaps(crops, box, shape):
    """Расширить каждую строку до середины промежутка с соседями.

    Так буквы не могут быть обрезаны: сверху и снизу забираем половину пустого
    промежутка, а по бокам — всю ширину облачка (там только поля).
    """
    if not crops:
        return crops
    bx1, by1, bx2, by2 = [int(round(v)) for v in box]
    H, W = shape[:2]
    out = []
    for i, (x1, y1, x2, y2) in enumerate(crops):
        # Берём треть промежутка с соседом, а не половину: половина затаскивала
        # в кроп верхушки соседней строки.
        top = by1 if i == 0 else y1 - max(0, (y1 - crops[i - 1][3]) // 3)
        bot = by2 if i == len(crops) - 1 else y2 + max(0, (crops[i + 1][1] - y2) // 3)
        nx1, ny1 = max(0, min(bx1, x1)), max(0, min(top, y1))
        nx2, ny2 = min(W, max(bx2, x2)), min(H, max(bot, y2))
        if nx2 - nx1 < 4 or ny2 - ny1 < 4:      # расширение съело строку — оставить как было
            nx1, ny1, nx2, ny2 = x1, y1, x2, y2
        out.append([nx1, ny1, nx2, ny2])
    return out


def cmd_build(name):
    png = None
    for cand in os.listdir('/home/user/manhwa-shots/pages'):
        if cand.startswith(name.split('-')[0]):
            png = '/home/user/manhwa-shots/pages/' + cand
            break
    gt_path = f'{WORK}/{name}.gt.txt'
    if not os.path.exists(gt_path):
        raise SystemExit(f'нет файла эталона {gt_path}')
    img = cv2.imread(PAGES[name]) if name in PAGES else cv2.imread(png)
    meta = json.load(open(f'{WORK}/{name}-bubbles.json'))
    lines = {}
    for raw in open(gt_path, encoding='utf-8'):
        raw = raw.rstrip('\n')
        if not raw.strip() or ':' not in raw:
            continue
        key, text = raw.split(':', 1)
        lines[key.strip().lstrip('#')] = text
    out_dir = os.path.join(DATA, 'data-hand')
    os.makedirs(out_dir, exist_ok=True)
    tsv = os.path.join(out_dir, 'labels.tsv')
    # дедупликация по ИМЕНИ ФАЙЛА, а не по тексту: две реплики «ШУХ» на странице —
    # это две разные строки, и раньше вторая молча выпадала
    have = set()
    if os.path.exists(tsv):
        for row in open(tsv, encoding='utf-8'):
            parts = row.split('\t')
            if parts and parts[0]:
                have.add(parts[0])
    rows, skipped = [], 0
    for m in meta:
        key = str(m['i'])
        if key not in lines:
            continue
        texts = [t.strip() for t in lines[key].split('|') if t.strip()]
        # Одна строка в эталоне → берём облачко целиком: крупные звуки нарисованы
        # по диагонали поверх линий фона, и проекция чернил режет их на куски.
        if len(texts) == 1:
            x1, y1, x2, y2 = [int(round(v)) for v in m['box']]
            crops = [[x1, y1, x2, y2]]
        else:
            crops = cut_rows(img, m['box'])
            if len(crops) != len(texts):
                # порог по проекции чернил подбираем под число строк в эталоне:
                # одна и та же доля не работает для разной плотности текста
                for frac in (0.24, 0.30, 0.12, 0.36, 0.09, 0.42):
                    trial = cut_rows_thr(img, m['box'], frac)
                    if len(trial) == len(texts):
                        crops = trial
                        break
        if len(crops) != len(texts):
            print(f'  облачко #{key}: нарезано {len(crops)} строк, в эталоне {len(texts)} — пропуск')
            skipped += 1
            continue
        crops = widen_to_gaps(crops, m['box'], img.shape)
        for j, (c, t) in enumerate(zip(crops, texts)):
            fn = f'{name}-b{key}-{j:02d}.png'
            x1, y1, x2, y2 = c
            cv2.imwrite(os.path.join(out_dir, fn), img[y1:y2, x1:x2])
            rows.append((fn, t, name, 'sfx' if t.startswith('*') else 'voice'))
    with open(tsv, 'a', encoding='utf-8') as f:
        for fn, t, page, kind in rows:
            if fn in have:
                continue
            f.write(f'{fn}\t{t.lstrip("*")}\t{page}\t{kind}\n')
    print(f'{name}: добавлено {len(rows)} строк в {tsv} (пропущено облачков {skipped})')


PAGES = {
    'comic1x5': '/home/user/manhwa-shots/pages/comic1x5-p1.png',
    'manhua3x2': '/home/user/manhwa-shots/pages/manhua3x2-p1.png',
    'manhua2-p2': '/home/user/manhwa-shots/pages/manhua2-p2.png',
    'comic1x7': '/home/user/manhwa-shots/pages/comic1x7-p1.png',
    'kuro-p2': '/home/user/manhwa-shots/pages/kuro-p2.png',
    'tyrant-p1': '/home/user/manhwa-shots/pages/tyrant-p1.png',
    'reader-p1': '/home/user/manhwa-shots/pages/reader-p1-seg8.png',
    'manhua1': '/home/user/manhwa-shots/pages/manhua1-p1.png',
    'tyrant-p2': '/home/user/manhwa-shots/pages/tyrant-p2.png',
    'reader-g5-p1': '/home/user/manhwa-shots/pages/reader-g5-p1.png',
    'tyrant-g5-p1': '/home/user/manhwa-shots/pages/tyrant-g5-p1.png',
    'reader-long': '/home/user/manhwa-shots/manhwa-reader-part1.png',
    'tyrant-long': '/home/user/manhwa-shots/manhwa-tyrant-part4.png',
}

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['prep', 'build'])
    ap.add_argument('name')
    ap.add_argument('png', nargs='?')
    a = ap.parse_args()
    if a.cmd == 'prep':
        cmd_prep(a.name, a.png or PAGES[a.name])
    else:
        cmd_build(a.name)
