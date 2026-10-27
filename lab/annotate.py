"""Рисует найденные реплики на странице: рамки, номера = порядок чтения.

  python3 lab/annotate.py pages/page15_shot.jpg out.png "Заголовок" "заметка" ...
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import pipeline as P

COLORS = ['#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4',
          '#008080', '#9a6324', '#000075', '#b03060']
FONT_DIR = '/usr/share/fonts/truetype/dejavu'


def font(size, bold=False):
    try:
        return ImageFont.truetype(f'{FONT_DIR}/DejaVuSans{"-Bold" if bold else ""}.ttf', size)
    except Exception:
        return ImageFont.load_default()


def best_lines(models, page):
    """Условия, подобранные в лаборатории: ×2, детектор 1600, projection, порог 0.25."""
    import experiment as E
    img = E.load(page, 2.0, False)
    boxes = E.detect_with(models, img, 1600, False)
    regions = E.recognize(models, img, boxes, 'projection', 0.25)
    return regions, P.reading_order(regions, True)


def annotate(page: str, out: str, title: str, notes: list[str], extra=None) -> None:
    models = P.Models()
    regions, lines = best_lines(models, Path(page))
    base = Image.open(page).convert('RGB')
    W, H = base.size
    S = 2
    legend = [f'{i}. {line.text}' for i, line in enumerate(lines, 1)]
    if notes:
        legend += [''] + list(notes)
    row = 46
    leg = row * len(legend) + 100

    canvas = Image.new('RGB', (W * S, H * S + leg), 'white')
    canvas.paste(base.resize((W * S, H * S), Image.LANCZOS), (0, 0))
    d = ImageDraw.Draw(canvas)
    num, small, head = font(26, True), font(24), font(30, True)

    for i, line in enumerate(lines, 1):
        x1, x2 = line.left * W * S, line.right * W * S
        y1, y2 = line.top * H * S, line.bottom * H * S
        c = COLORS[(i - 1) % len(COLORS)]
        d.rectangle([x1 - 6, y1 - 6, x2 + 6, y2 + 6], outline=c, width=5)
        d.rectangle([x1 - 6, y1 - 38, x1 + 42, y1 - 6], fill=c)
        d.text((x1 + 6, y1 - 36), str(i), fill='white', font=num)

    for label, rect, color in (extra or []):
        x1, y1, x2, y2 = [v * (W if k % 2 == 0 else H) * S for k, v in enumerate(rect)]
        d.rectangle([x1, y1, x2, y2], outline=color, width=6)
        d.rectangle([x1, max(0, y1 - 38), x1 + 44, max(0, y1 - 6)], fill=color)
        d.text((x1 + 8, max(0, y1 - 36)), label, fill='white', font=num)

    d.rectangle([0, H * S, W * S, H * S + leg], fill='white')
    d.text((22, H * S + 12), title, fill='black', font=head)
    for k, text in enumerate(legend):
        d.text((22, H * S + 62 + row * k), text[:80], fill='#222', font=small)
    canvas.save(out)
    print(out, canvas.size)


if __name__ == '__main__':
    annotate(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
