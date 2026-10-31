#!/usr/bin/env python3
"""Стенд замера: три страницы с эталоном. Не для отчёта, для перебора.

    python3 scripts/dev_bench.py [--label имя] [--pages dense-a dense-b]
"""
import argparse, json, os, sys, time
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ownocr.page_det import PageDetector          # noqa: E402
import ownocr.pair as pr                          # noqa: E402

LAB = '/home/user/koma-lab'
ap = argparse.ArgumentParser()
ap.add_argument('--label', default=os.environ.get('LABEL', '?'))
ap.add_argument('--pages', nargs='+', default=['dense-a', 'dense-b', 'dense-page'])
a = ap.parse_args()

det = PageDetector('/home/user/koma_models/koma_det.onnx')
r = pr.OwnReader(os.path.join(ROOT, 'model'))
refs = json.load(open(os.path.join(LAB, 'dense-expected.json'), encoding='utf-8'))
tot, exact_all, tol_all, err_all, dump = [], 0, 0, 0, {}
for page in a.pages:
    rgb = np.array(Image.open(os.path.join(LAB, f'{page}.jpg')).convert('RGB'))
    res = pr.read_page(det, r, rgb)
    got = [x.text for x in res['replies']]
    dump[page] = [{'text': x.text, 'box': [x.left, x.top, x.right, x.bottom]}
                  for x in res['replies']]
    n = min(len(refs), len(got))
    c = [pr.cer(pr.clean(refs[i]), pr.clean(got[i])) for i in range(n)] + \
        [1.0] * abs(len(refs) - len(got))
    cer = 100 * float(np.mean(c))
    exact = sum(1 for x in c if x == 0)
    tol = sum(1 for x in c if x <= 0.15)
    errs = sum(pr.levenshtein(pr.clean(refs[i]), pr.clean(got[i])) for i in range(n))
    tot.append(cer); exact_all += exact; tol_all += tol; err_all += errs
    print(f'{a.label} {page}: {len(got)} репл · {cer:.1f} % · дословно {exact}/9 · '
          f'≤15% {tol}/9 · ошибок {errs} · {res["seconds"]:.0f} с', flush=True)
print(f'{a.label} СРЕДНЕЕ {np.mean(tot):.1f} % · дословно {exact_all}/{9*len(a.pages)} · '
      f'≤15% {tol_all}/{9*len(a.pages)} · ошибок {err_all}', flush=True)
if os.environ.get('DUMP'):
    json.dump(dump, open(os.environ['DUMP'], 'w'), ensure_ascii=False, indent=1)
