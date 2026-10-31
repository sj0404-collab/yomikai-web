#!/usr/bin/env python3
"""Лист одной страницы: скрин с разметкой сверху, текст ученика снизу.

Для страниц, где эталона нет (новые страницы манги и манхвы): видно, что
нашёл детектор, какие реплики собраны и в каком они порядке. Ширина 800 px —
лист не уезжает за край телефона.

    python3 scripts/13_page_sheet.py --page ../lab/pages/page15_shot.jpg \
        --out ../свой-OCR-page15.jpg
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr.page_det import PageDetector                          # noqa: E402
from ownocr.pair import read_page, normalize_page, OwnReader      # noqa: E402

BG, FG, DIM, OK, ACC = (18, 20, 28), (238, 240, 246), (150, 158, 176), \
    (108, 214, 150), (110, 168, 255)
F = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
W = 800


def font(size, bold=False):
    return ImageFont.truetype(FB if bold else F, size)


def wrap(draw, text, fnt, width):
    lines, cur = [], ''
    for word in text.split(' '):
        probe = (cur + ' ' + word).strip()
        if draw.textlength(probe, font=fnt) <= width:
            cur = probe
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def overlay(img, replies):
    out = np.array(img, dtype=np.uint8).copy()
    h, w = out.shape[:2]
    import cv2
    for i, line in enumerate(replies, 1):
        p1 = (int(line.left * w), int(line.top * h))
        p2 = (int(line.right * w), int(line.bottom * h))
        cv2.rectangle(out, p1, p2, OK, 2)
        cv2.putText(out, str(i), (p1[0] + 2, max(14, p1[1] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, OK, 2)
    return Image.fromarray(out)


def build(page, out_path, det, reader):
    rgb = np.array(Image.open(page).convert('RGB'))
    res = read_page(det, reader, rgb)
    reps = res['replies']
    shot = overlay(normalize_page(rgb), reps)
    shot.thumbnail((W - 40, 1400), Image.LANCZOS)

    texts = []
    for i, r in enumerate(reps, 1):
        texts.append(f'{i}. {r.text}')

    pad, head = 16, 96
    d0 = ImageDraw.Draw(Image.new('RGB', (10, 10)))
    f_t, f_b, f_s, f_x = font(23, True), font(19), font(15), font(20)
    wrapped = [wrap(d0, t, f_x, W - 60) for t in texts]
    body_h = sum(len(w) * 27 + 14 for w in wrapped) + 60
    H = head + shot.height + body_h
    sheet = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(sheet)
    d.text((20, 14), os.path.basename(page), font=f_t, fill=FG)
    d.text((20, 48), f'реплик {len(reps)} · отброшено {res["dropped"]} · '
                     f'линий {res["lines"]} · {res["seconds"]:.1f} с',
           font=f_s, fill=DIM)
    sheet.paste(shot, ((W - shot.width) // 2, head))
    y = head + shot.height + 14
    d.text((20, y), 'текст ученика, в том же порядке (справа налево)', font=f_b, fill=ACC)
    y += 34
    for lines in wrapped:
        for line in lines:
            d.text((26, y), line, font=f_x, fill=FG)
            y += 27
        y += 14
    sheet.save(out_path, quality=88)
    print(f'{out_path}: {sheet.size[0]}×{sheet.size[1]} · реплик {len(reps)} · '
          f'{os.path.getsize(out_path) // 1024} КБ')
    for t in texts:
        print('   ', t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pages', nargs='+', required=True)
    ap.add_argument('--prefix', default=os.path.join(ROOT, '..', 'свой-OCR-страница'))
    ap.add_argument('--det', default='/home/user/koma_models/koma_det.onnx')
    ap.add_argument('--model', default=os.path.join(ROOT, 'model'))
    a = ap.parse_args()
    det, reader = PageDetector(a.det), OwnReader(a.model)
    for i, page in enumerate(a.pages, 1):
        name = os.path.splitext(os.path.basename(page))[0]
        build(page, f'{a.prefix}-{name}.jpg', det, reader)


if __name__ == '__main__':
    main()
