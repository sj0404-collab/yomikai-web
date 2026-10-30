#!/usr/bin/env python3
"""Нарисовать итоговую карточку «зачётная лестница + чтение» из артефактов прогона.

    python3 scripts/09_diploma_card.py --art /tmp/art4 --out /home/user/свой-OCR-курс.png

Берёт model/diploma.json и out/metrics-final.json из артефактов раннера, поэтому
картинка всегда соответствует последнему прогону, а не нарисована руками.
"""
import argparse
import json
import os

from PIL import Image, ImageDraw, ImageFont

BG = (18, 20, 28)
FG = (238, 240, 246)
DIM = (150, 158, 176)
OK = (108, 214, 150)
BAD = (232, 120, 120)
ACC = (110, 168, 255)

F = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FB = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def font(size, bold=False):
    return ImageFont.truetype(FB if bold else F, size)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--art', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--title', default='Свой OCR: зачётная лестница')
    a = ap.parse_args()

    dip = json.load(open(os.path.join(a.art, 'model', 'diploma.json')))['diploma']
    met = json.load(open(os.path.join(a.art, 'out', 'metrics-final.json')))
    les = json.load(open(os.path.join(a.art, 'out', 'lesson-real.json')))

    levels = [d for d in dip if d['key'] != 'revision']
    revision = next((d for d in dip if d['key'] == 'revision'), None)
    passed = sum(1 for d in levels if d['passed'])

    W, row_h = 1180, 58
    H = 300 + row_h * (len(levels) + 2) + 210
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((48, 40), a.title, font=font(40, True), fill=FG)
    d.text((48, 96), 'обучение на раннере GitHub · 8 ступеней · зачёт только по экзамену',
           font=font(21), fill=DIM)

    y = 150
    d.text((48, y), f'сдано ступеней: {passed} из {len(levels)}', font=font(26, True), fill=ACC)
    y += 46

    head = ('ступень', 'экзамен', 'с наклоном', 'планка')
    d.text((72, y), head[0], font=font(20), fill=DIM)
    d.text((560, y), head[1], font=font(20), fill=DIM)
    d.text((720, y), head[2], font=font(20), fill=DIM)
    d.text((920, y), head[3], font=font(20), fill=DIM)
    y += 34

    for lv in levels:
        ok = lv['passed']
        d.rectangle([48, y - 8, W - 48, y + row_h - 22], fill=(26, 29, 40))
        d.text((72, y), ('✓ ' if ok else '· ') + lv['name'], font=font(22, True),
               fill=OK if ok else DIM)
        d.text((560, y), f"{100 * lv['exam']:.1f} %", font=font(22, True),
               fill=OK if ok else FG)
        d.text((720, y), f"{100 * lv['exam_hard']:.1f} %", font=font(22), fill=FG)
        d.text((920, y), f"{100 * lv['target']:.0f} %", font=font(22), fill=DIM)
        y += row_h

    if revision:
        kept, dropped = revision.get('kept', 0), revision.get('dropped', 0)
        d.rectangle([48, y - 8, W - 48, y + row_h - 22], fill=(30, 26, 44))
        d.text((72, y), f'повторение сданного ×{kept + dropped}', font=font(22, True),
               fill=(214, 196, 255))
        d.text((560, y), f"{100 * revision['exam']:.1f} %", font=font(22, True),
               fill=(214, 196, 255))
        d.text((720, y), f"зафикс {kept} · откат {dropped}", font=font(20), fill=DIM)
        y += row_h

    y += 18
    d.line([48, y, W - 48, y], fill=(52, 57, 72), width=2)
    y += 26
    d.text((48, y), 'Чтение (на строках, не на целой странице)', font=font(24, True), fill=FG)
    y += 40

    def bar(label, value, best=True):
        nonlocal y
        d.text((72, y), label, font=font(20), fill=DIM)
        x0, x1 = 500, W - 130
        d.rectangle([x0, y + 4, x1, y + 24], fill=(32, 36, 48))
        w = int((x1 - x0) * min(1.0, value))
        d.rectangle([x0, y + 4, x0 + w, y + 24], fill=ACC)
        d.text((x1 + 14, y), f'{100 * value:.1f} %', font=font(20, True), fill=FG)
        y += 40

    manga = met.get('manga', {})
    prose = met.get('prose', {})
    bar('манга, буквы верно', manga.get('letter_acc', 0))
    bar('манга, строка целиком', manga.get('exact', 0) / max(1, manga.get('n', 1)))
    bar('проза в чужих шрифтах', prose.get('exact', 0) / max(1, prose.get('n', 1)))
    bar('глифы незнакомых шрифтов', met.get('sheet_clean', {}).get('acc', 0))

    y += 8
    d.text((72, y), f"Урок 7 (настоящая страница): "
                    f"{100 * les['before_cer']:.1f} → {100 * les['after_cer']:.1f} % CER · "
                    f"целых строк {les['after_exact']} из {les['n_test']} · "
                    f"{'принят' if les['accepted'] else 'откат'}",
           font=font(20), fill=FG if les['accepted'] else BAD)
    y += 36
    d.text((72, y), f"CER манги {100 * manga.get('cer', 0):.1f} % · "
                    f"время {met.get('speed', {}).get('line_ms', 0):.0f} мс на строку · "
                    f"модель {met.get('model_size_kb', 0):.0f} КБ · "
                    f"{met.get('params', 0)} чисел",
           font=font(20), fill=DIM)

    img.save(a.out)
    print('картинка:', a.out)


if __name__ == '__main__':
    main()
