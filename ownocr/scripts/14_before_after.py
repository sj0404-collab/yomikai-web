#!/usr/bin/env python3
"""Коллаж «до / после» с эталоном специалиста в каждой реплике.

Для каждой страницы: скрин с номерами реплик, затем по каждой реплике три
строки — эталон, что читала прежняя версия, что читает текущая. Верные слова
зелёные, неверные красные, пропущенные слова показаны отдельно. Внизу — счёт
буквенных ошибок до и после. Ничего не сглаживается: то, что осталось сломано,
видно красным.

    python3 scripts/14_before_after.py --pages dense-a dense-b dense-page \
        --before /tmp/before_texts.json --after /tmp/after_texts.json
"""
import argparse
import difflib
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr.pair import cer, clean, normalize_page                   # noqa: E402

BG, FG, DIM = (16, 18, 26), (240, 242, 248), (140, 148, 168)
GOOD, BAD, REF, ACC = (108, 214, 150), (255, 120, 120), (186, 196, 220), (110, 168, 255)
F = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
W = 820


def font(sz, bold=False):
    return ImageFont.truetype(FB if bold else F, sz)


def wrap(d, text, fnt, width):
    lines, cur = [], ''
    for word in text.split(' '):
        probe = (cur + ' ' + word).strip()
        if d.textlength(probe, font=fnt) <= width:
            cur = probe
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines or ['']


def tokens(text):
    return [t for t in text.split(' ') if t]


def draw_marked(d, xy, text, ref, fnt, width):
    """Строка с подсветкой: зелёное — совпало с эталоном, красное — нет."""
    x, y = xy
    ref_w = [t.upper() for t in tokens(clean_words(ref))]
    hyp = tokens(text)
    hyp_w = [t.upper() for t in tokens(clean_words(text))]
    marks = ['bad'] * len(hyp)
    sm = difflib.SequenceMatcher(None, ref_w, hyp_w)
    missing = []
    for op, a0, a1, b0, b1 in sm.get_opcodes():
        if op == 'equal':
            for i in range(b0, b1):
                marks[i] = 'ok'
        elif op == 'delete':
            missing += ref_w[a0:a1]
    line_x, line_y = x, y
    for word, mark in zip(hyp, marks):
        w = d.textlength(word + ' ', font=fnt)
        if line_x + w > x + width:
            line_x, line_y = x, line_y + fnt.size + 7
        d.text((line_x, line_y), word, font=fnt, fill=GOOD if mark == 'ok' else BAD)
        line_x += w
    if missing:
        tail = ' ⟨пропущено: ' + ' '.join(missing) + '⟩'
        if line_x + d.textlength(tail, font=fnt) > x + width:
            line_x, line_y = x, line_y + fnt.size + 7
        d.text((line_x, line_y), tail, font=fnt, fill=BAD)
    return line_y + fnt.size + 10


def clean_words(text):
    return ' '.join(w.strip('.,!?…—«»"():;%') for w in text.split())


def levenshtein(a, b):
    a, b = clean(a), clean(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def overlay(img, boxes):
    out = np.array(img, dtype=np.uint8).copy()
    h, w = out.shape[:2]
    for i, b in enumerate(boxes, 1):
        p1 = (int(b[0] * w), int(b[1] * h))
        p2 = (int(b[2] * w), int(b[3] * h))
        cv2.rectangle(out, p1, p2, (60, 220, 100), 2)
        cv2.putText(out, str(i), (p1[0] + 2, max(14, p1[1] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 220, 100), 2)
    return Image.fromarray(out)


def build(page, refs, before, after, out_path):
    shot = overlay(normalize_page(np.array(Image.open(f'/home/user/koma-lab/{page}.jpg').convert('RGB'))),
                   [r['box'] for r in after])
    shot.thumbnail((W - 60, 1100), Image.LANCZOS)
    before_t = [r if isinstance(r, str) else r.get('text', '') for r in before]
    after_t = [r['text'] for r in after]

    f_h, f_s, f_x = font(24, True), font(15), font(19)
    meas = ImageDraw.Draw(Image.new('RGB', (10, 10)))

    def errs(hyp):
        n = min(len(refs), len(hyp))
        return sum(levenshtein(refs[i], hyp[i]) for i in range(n)) + \
            40 * abs(len(refs) - len(hyp))

    eb, ea = errs(before_t), errs(after_t)
    cb = 100 * np.mean([cer(clean(refs[i]), clean(before_t[i]))
                        for i in range(min(len(refs), len(before_t)))])
    ca = 100 * np.mean([cer(clean(refs[i]), clean(after_t[i]))
                        for i in range(min(len(refs), len(after_t)))])
    exact_b = sum(1 for i in range(min(len(refs), len(before_t)))
                  if cer(clean(refs[i]), clean(before_t[i])) == 0)
    exact_a = sum(1 for i in range(min(len(refs), len(after_t)))
                  if cer(clean(refs[i]), clean(after_t[i])) == 0)

    stat = (f'буквенных ошибок: до {eb} → после {ea}   ·   CER: до {cb:.1f} % → '
            f'после {ca:.1f} %   ·   целиком верных реплик: до {exact_b} → '
            f'после {exact_a} из {len(refs)}')
    stat_lines = wrap(meas, stat, f_s, W - 44)
    head = 92 + (len(stat_lines) - 1) * 21

    height = head + shot.height + 40
    for ref, bt, at in zip(refs, before_t, after_t):
        for t in (ref, bt, at):
            height += len(wrap(meas, t, f_x, W - 150)) * 26 + 6
        height += 16
    height += 300
    sheet = Image.new('RGB', (W, height), BG)
    d = ImageDraw.Draw(sheet)
    d.text((22, 16), f'{page} — эталон, «до» и «после»', font=f_h, fill=FG)
    y = 50
    for line in stat_lines:
        d.text((22, y), line, font=f_s, fill=ACC)
        y += 21
    d.text((22, y + 2), 'зелёное — слово совпало с эталоном, красное — нет',
           font=f_s, fill=DIM)
    sheet.paste(shot, ((W - shot.width) // 2, head))
    y = head + shot.height + 22

    for i, (ref, bt, at) in enumerate(zip(refs, before_t, after_t), 1):
        d.text((22, y), f'{i}', font=font(20, True), fill=ACC)
        y += 26
        for tag, text, col in (('ЭТАЛОН', ref, REF), ('ДО', bt, None), ('ПОСЛЕ', at, None)):
            d.text((46, y), tag, font=f_s, fill=DIM)
            if col:
                for line in wrap(d, text, f_x, W - 150):
                    d.text((122, y), line, font=f_x, fill=col)
                    y += 26
            else:
                y = draw_marked(d, (122, y), text, ref, f_x, W - 150)
            y += 4
        y += 14
    y += 8
    for line in wrap(d, 'Пропущенные слова показаны как ⟨пропущено: …⟩. Это не '
                        'приглаженный отчёт: красное — по-прежнему сломано.',
                     f_s, W - 44):
        d.text((22, y), line, font=f_s, fill=DIM)
        y += 21
    sheet.save(out_path, quality=86)
    print(f'{out_path}: {sheet.size[0]}×{sheet.size[1]} · {os.path.getsize(out_path) // 1024} КБ · '
          f'ошибок {eb} → {ea}, CER {cb:.1f} → {ca:.1f} %')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pages', nargs='+', default=['dense-a', 'dense-b', 'dense-page'])
    ap.add_argument('--expected', default='/home/user/koma-lab/dense-expected.json')
    ap.add_argument('--before', default='/tmp/before_texts.json')
    ap.add_argument('--after', default='/tmp/after_texts.json')
    ap.add_argument('--prefix', default='/home/user/коллаж-до-после')
    a = ap.parse_args()
    refs_all = json.load(open(a.expected, encoding='utf-8'))
    before, after = json.load(open(a.before, encoding='utf-8')), json.load(open(a.after, encoding='utf-8'))
    for page in a.pages:
        build(page, refs_all, before[page], after[page], f'{a.prefix}-{page}.jpg')


if __name__ == '__main__':
    main()
