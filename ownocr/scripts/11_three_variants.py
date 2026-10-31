#!/usr/bin/env python3
"""Одна страница в трёх видах: цветная, чёрно-белая и инверсия.

Для каждого вида: слева сам скрин с разметкой ученика (что нашёл детектор,
какие реплики собраны и в каком порядке), справа — текст ученика в той же
последовательности. Так видно и картинку, и что из неё прочитано.

    python3 scripts/11_three_variants.py --page ../koma-lab/dense-a.jpg \
        --det /home/user/koma_models/koma_det.onnx --out ../свой-OCR-три-варианта.png
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr.page_det import PageDetector, text_lines          # noqa: E402
from ownocr.pair import (cer, clean, is_harsh_page,   # noqa: E402
                        normalize_page, read_page, OwnReader)

BG = (18, 20, 28)
FG = (238, 240, 246)
DIM = (150, 158, 176)
OK = (108, 214, 150)
WARN = (232, 190, 120)
ACC = (110, 168, 255)
BOX = (60, 200, 90)

F = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FB if bold else F, size)


def make_variants(rgb: np.ndarray):
    """Три вида одной и той же страницы."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    return [
        ('ЦВЕТНАЯ', rgb),
        ('ЧЁРНО-БЕЛАЯ', np.dstack([bw] * 3)),
        ('ИНВЕРСИЯ', 255 - rgb),
    ]


def draw_overlay(img: np.ndarray, det_boxes, lines) -> Image.Image:
    """Скрин + серые рамки детектора + зелёные рамки реплик с номерами."""
    out = np.array(img, dtype=np.uint8).copy()
    h, w = out.shape[:2]
    for (x1, y1, x2, y2) in det_boxes:
        cv2.rectangle(out, (int(x1), int(y1)), (int(x2), int(y2)), (140, 140, 140), 1)
    for i, line in enumerate(lines, 1):
        p1 = (int(line.left * w), int(line.top * h))
        p2 = (int(line.right * w), int(line.bottom * h))
        cv2.rectangle(out, p1, p2, BOX, 2)
        cv2.putText(out, str(i), (p1[0] + 2, max(12, p1[1] - 3)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, BOX, 2)
    return Image.fromarray(out)


def wrap(draw, text, fnt, width):
    words, lines, cur = text.split(' '), [], ''
    for word in words:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--page', default=os.path.join(ROOT, '..', 'koma-lab', 'dense-a.jpg'))
    ap.add_argument('--det', default='/home/user/koma_models/koma_det.onnx')
    ap.add_argument('--model', default=os.path.join(ROOT, 'model'))
    ap.add_argument('--expected',
                    default=os.path.join(ROOT, '..', 'koma-lab', 'dense-expected.json'))
    ap.add_argument('--out', default=os.path.join(ROOT, '..', 'свой-OCR-три-варианта.png'))
    ap.add_argument('--json', default=os.path.join(ROOT, 'out', 'three-variants.json'))
    ap.add_argument('--layout', choices=['wide', 'phone'], default='wide',
                    help='wide — картинка и текст рядом; phone — скрин сверху, '
                         'текст под ним (для телефона: ничего не уезжает за край)')
    ap.add_argument('--prefix', default=os.path.join(ROOT, '..', 'свой-OCR-телефон'))
    a = ap.parse_args()

    rgb = np.array(Image.open(a.page).convert('RGB'))
    exp = json.load(open(a.expected, encoding='utf-8')) if a.expected else []
    det = PageDetector(a.det)
    reader = OwnReader(a.model)

    results = []
    for title, img in make_variants(rgb):
        res = read_page(det, reader, img, minconf=0.8)
        got = [line.text for line in res['replies']]
        n = min(len(exp), len(got))
        score = float(np.mean([cer(clean(exp[i]), clean(got[i])) for i in range(n)]
                              + [1.0] * abs(len(exp) - len(got)))) if exp else None
        results.append({'title': title, 'image': img, 'lines': res['replies'],
                        'texts': got, 'cer': score, 'seconds': res['seconds'],
                        'boxes': det.detect_page(normalize_page(img)), 'harsh': res['harsh']})
        print(f'{title:14s}: реплик {len(got)} · CER '
              f'{"" if score is None else f"{100 * score:.1f} %"} · {res["seconds"]:.1f} с')

    same = results[0]['texts'] == results[2]['texts']
    print(f'инверсия читается как цвет: {"да, слово в слово" if same else "нет"}')


    # ── раскладка под телефон: вертикально, ничего не уезжает за край ────────
    if a.layout == 'phone':
        W = 800                     # уже любого телефона: масштабируется по ширине
        pad = 26
        f_hdr, f_num, f_body = font(26, True), font(22, True), font(21)
        step = 27
        made = []
        for k, r in enumerate(results, 1):
            page_w = W - pad * 2
            page_h = int(rgb.shape[0] * page_w / rgb.shape[1])
            page_img = draw_overlay(r['image'], r['boxes'], r['lines']).resize(
                (page_w, page_h), Image.LANCZOS)
            probe2 = ImageDraw.Draw(Image.new('RGB', (8, 8)))
            body_h = 0
            wrapped = []
            for text in r['texts']:
                pieces = wrap(probe2, text, f_body, W - pad * 2 - 46)
                wrapped.append(pieces)
                body_h += step * len(pieces) + 8
            H = pad + 96 + page_h + 40 + body_h + pad + 40
            sheet_i = Image.new('RGB', (W, H), BG)
            di = ImageDraw.Draw(sheet_i)
            di.text((pad, pad), f'{r["title"]}', font=f_hdr, fill=ACC)
            info = f'реплик {len(r["texts"])}'
            if r['cer'] is not None:
                info += f' · CER {100 * r["cer"]:.1f} %'
            di.text((pad, pad + 34), info + f' · {r["seconds"]:.1f} с',
                    font=font(21, True),
                    fill=OK if (r['cer'] is not None and r['cer'] < 0.20) else WARN)
            di.text((pad, pad + 62), 'сверху — скрин с разметкой, ниже — текст ученика '
                                     'в том же порядке', font=font(17), fill=DIM)
            y = pad + 96
            sheet_i.paste(page_img, (pad, y))
            di.rectangle([pad - 3, y - 3, pad + page_w + 2, y + page_h + 2],
                         outline=(54, 60, 76), width=1)
            y += page_h + 34
            di.text((pad, y), 'текст ученика, в том же порядке', font=font(19, True), fill=DIM)
            y += 30
            for i, pieces in enumerate(wrapped, 1):
                di.text((pad, y + 1), f'{i}.', font=f_num, fill=ACC)
                for j, piece in enumerate(pieces):
                    di.text((pad + 40, y + j * step), piece, font=f_body, fill=FG)
                y += step * len(pieces) + 8
            di.text((pad, y + 12), 'серые рамки — детектор · зелёные с номером — реплики',
                    font=font(16), fill=DIM)
            name = f'{a.prefix}-{k}.jpg'
            sheet_i.save(name, quality=88, optimize=True)
            made.append((name, sheet_i.size))
            print(f'  {name}  {sheet_i.size[0]}×{sheet_i.size[1]}')
        print('лист для телефона: ' + ', '.join(n for n, _ in made))
        json.dump({'page': os.path.basename(a.page), 'layout': 'phone',
                   'variants': {r['title']: {'texts': r['texts'], 'cer': r['cer'],
                                             'seconds': round(r['seconds'], 2)}
                                for r in results}},
                  open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        return

    # ── сборка листа ────────────────────────────────────────────────────────
    scale = 0.74
    pw = int(rgb.shape[1] * scale)
    ph = int(rgb.shape[0] * scale)
    col_txt = 720
    pad, gap, head = 26, 26, 66
    fnt_body, step = font(19), 25
    probe = ImageDraw.Draw(Image.new('RGB', (8, 8)))
    text_h = 0
    for r in results:
        h = 0
        for text in r['texts']:
            h += step * len(wrap(probe, text, fnt_body, col_txt - 44)) + 6
        text_h = max(text_h, h)
    row_h = max(ph, text_h + 34) + head + gap
    W = pad * 2 + pw + gap + col_txt
    H = pad * 2 + row_h * len(results) + 100
    sheet = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(sheet)

    d.text((pad, 20), 'Один и тот же скрин в трёх видах — что прочитал свой ученик',
           font=font(31, True), fill=FG)
    d.text((pad, 62), f'{os.path.basename(a.page)} · детектор приложения + свой OCR · '
                      f'порядок чтения: сверху вниз, справа налево',
           font=font(18), fill=DIM)

    y = 100
    for r in results:
        # ── заголовок блока: две строки, чтобы ничего не наезжало ──
        d.text((pad, y), r['title'], font=font(25, True), fill=ACC)
        info = f'реплик {len(r["texts"])}'
        if r['cer'] is not None:
            info += f' · CER {100 * r["cer"]:.1f} %'
        info += f' · {r["seconds"]:.1f} с'
        colour = OK if (r['cer'] is not None and r['cer'] < 0.20) else WARN
        d.text((pad + pw + gap, y + 6), info, font=font(20, True), fill=colour)
        d.text((pad, y + 32), 'слева — скрин с разметкой ученика · '
                             'справа — текст ученика в той же последовательности',
               font=font(18), fill=DIM)

        # ── картинка ──
        page_img = draw_overlay(r['image'], r['boxes'], r['lines']).resize((pw, ph), Image.LANCZOS)
        sheet.paste(page_img, (pad, y + head))
        d.rectangle([pad - 6, y + head - 6, pad + pw + 5, y + head + ph + 5],
                    outline=(54, 60, 76), width=1)

        # ── текст ──
        tx = pad + pw + gap
        ty = y + head
        for i, text in enumerate(r['texts'], 1):
            pieces = wrap(d, text, fnt_body, col_txt - 44)
            d.text((tx, ty + 2), f'{i}.', font=font(19, True), fill=ACC)
            for k, piece in enumerate(pieces):
                d.text((tx + 34, ty + k * step), piece, font=fnt_body, fill=FG)
            ty += step * len(pieces) + 6
        y += row_h

    d.text((pad, H - 64), 'серые рамки — что нашёл детектор приложения · '
                          'зелёные с номером — собранная реплика в порядке чтения',
           font=font(17), fill=DIM)
    d.text((pad, H - 38), 'чёрно-белый и инвертированный вид сначала приводятся к одному: '
                          'полярность определяется по доле тёмных пикселей',
           font=font(17), fill=DIM)

    sheet.save(a.out)
    json.dump({'page': os.path.basename(a.page),
               'variants': {r['title']: {'texts': r['texts'], 'cer': r['cer'],
                                         'seconds': round(r['seconds'], 2),
                                         'boxes': len(r['boxes']), 'harsh': r['harsh']}
                            for r in results}},
              open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('лист:', a.out)
    print('json:', a.json)


if __name__ == '__main__':
    main()
