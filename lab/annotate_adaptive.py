"""Разметка страницы по АДАПТИВНОЙ схеме (основной проход + добор потерянного)."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import adapt3
import annotate as A
import pipeline as P

FONT_DIR = '/usr/share/fonts/truetype/dejavu'


def font(size, bold=False):
    try:
        return ImageFont.truetype(f'{FONT_DIR}/DejaVuSans{"-Bold" if bold else ""}.ttf', size)
    except Exception:
        return ImageFont.load_default()


def render(page: str, out: str, title: str, notes: list[str], extra=None, rescued=()) -> None:
    models = P.Models()
    _, regions = adapt3.adaptive(models, Path(page))
    lines = adapt3.dedupe_text(P.reading_order(regions, True))
    rescued_boxes = {(round(r.left, 3), round(r.top, 3)) for r in rescued}
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
        c = A.COLORS[(i - 1) % len(A.COLORS)]
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
    render(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
