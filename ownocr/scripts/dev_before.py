#!/usr/bin/env python3
"""Прочтение страницы ПРЕЖНЕЙ версией кода (для коллажа «до/после»).

    python3 scripts/dev_before.py --pkg /tmp/bo --out /home/user/ownocr/out/before.json
"""
import argparse, json, sys
import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument('--pkg', default='/tmp/bo')
ap.add_argument('--out', default='/home/user/ownocr/out/before.json')
ap.add_argument('--model', default='/home/user/ownocr/model')
ap.add_argument('--pages', nargs='+', default=['dense-a', 'dense-b', 'dense-page'])
a = ap.parse_args()
sys.path.insert(0, a.pkg)
from ownocr.page_det import PageDetector          # noqa: E402
import ownocr.pair as pr                          # noqa: E402
print('версия ДО:', pr.__file__)
det = PageDetector('/home/user/koma_models/koma_det.onnx')
r = pr.OwnReader(a.model)
out = {}
for page in a.pages:
    rgb = np.array(Image.open(f'/home/user/koma-lab/{page}.jpg').convert('RGB'))
    res = pr.read_page(det, r, rgb)
    out[page] = [x.text for x in res['replies']]
    print(page, len(out[page]), round(res['seconds'], 1))
json.dump(out, open(a.out, 'w'), ensure_ascii=False, indent=1)
