#!/usr/bin/env python3
"""Честный CER для того, что прочитал браузерный движок.

    python3 web-ocr/test/score.py dense-a
"""
import json, sys, os
sys.path.insert(0, '/home/user/ownocr')
import ownocr.pair as pr

page = sys.argv[1] if len(sys.argv) > 1 else 'dense-a'
got = json.load(open(f'/home/user/web-ocr/test/{page}-web.json', encoding='utf-8'))['replies']
refs = json.load(open('/home/user/koma-lab/dense-expected.json', encoding='utf-8'))
n = min(len(refs), len(got))
c = [pr.cer(pr.clean(refs[i]), pr.clean(got[i])) for i in range(n)] + [1.0] * abs(len(refs) - len(got))
print(f'{page}: {len(got)} реплик · CER {100*sum(c)/len(c):.1f} % · '
      f'дословно {sum(1 for x in c if x == 0)}/9 · ≤15 % {sum(1 for x in c if x <= 0.15)}/9 · '
      f'ошибок {sum(pr.levenshtein(pr.clean(refs[i]), pr.clean(got[i])) for i in range(n))}')
for i in range(len(refs)):
    g = got[i] if i < len(got) else '—'
    mark = '  ' if i < n and c[i] == 0 else '✗ '
    print(f'{mark}{i+1}. эталон: {refs[i]}')
    if i < n and c[i] != 0:
        print(f'      наше:  {g}')
