#!/usr/bin/env python3
"""Разбор порядка: какие области нашлись и в каком порядке склеились."""
import sys, os
import numpy as np
from PIL import Image
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ownocr.page_det import PageDetector, text_lines          # noqa: E402
import ownocr.pair as pr                                       # noqa: E402

det = PageDetector('/home/user/koma_models/koma_det.onnx')
r = pr.OwnReader(os.path.join(ROOT, 'model'))
rgb = pr.normalize_page(np.array(Image.open(sys.argv[1]).convert('RGB')))
H, W = rgb.shape[:2]
harsh = pr.is_harsh_page(rgb)
print('страница', rgb.shape, 'harsh', harsh)
regs = []
for box in det.detect_page(rgb)[:400]:
    for (x0, y0, x1, y1) in text_lines(rgb, box):
        crop = rgb[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        if crop.shape[0] > crop.shape[1] * 1.8:
            crop = np.rot90(crop, k=-1)
        text, score = r.read(np.array(Image.fromarray(crop).convert('L')), harsh=harsh)
        alnum = sum(c.isalnum() for c in text.strip())
        if text.strip() and score >= 0.8 and alnum >= 2 and alnum / max(1, len(text)) >= 0.5:
            regs.append(pr.Region(text.strip(), x0 / W, y0 / H, x1 / W, y1 / H, score))
print('--- области (x, y, текст):')
for g in regs:
    print(f'  {g.left:.3f},{g.top:.3f} → {g.text!r}')
print('--- панели и реплики в порядке чтения:')
for pi, panel in enumerate(pr.split_panels(regs, True), 1):
    for rep in pr.bubbles_of(panel, True):
        print(f'  панель {pi}: {rep.text!r}  (обл. {len(rep.parts) if hasattr(rep, "parts") else "?"})')
