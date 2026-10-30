#!/usr/bin/env python3
"""Полный курс «детский сад → университет» с проверкой домашних заданий.

    python3 scripts/06_curriculum.py --budget-minutes 40
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr.curriculum import Curriculum   # noqa: E402


def default_labels():
    own = os.path.join(ROOT, 'data-real', 'labels.tsv')
    return own if os.path.exists(own) else os.path.join(ROOT, '..', 'data', 'lines-real', 'labels.tsv')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', default=os.path.join(ROOT, 'out', 'sheet.png'))
    ap.add_argument('--manifest', default=os.path.join(ROOT, 'out', 'sheet-manifest.json'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'model'))
    ap.add_argument('--labels', default=default_labels())
    ap.add_argument('--page', default=os.path.join(ROOT, '..', 'koma-lab', 'dense-a.jpg'))
    ap.add_argument('--budget-minutes', type=float, default=40.0)
    ap.add_argument('--stages', default='')
    a = ap.parse_args()
    stages = [s for s in a.stages.split(',') if s.strip()] or None
    c = Curriculum(a.sheet, a.manifest, a.out, budget_min=a.budget_minutes)
    diploma = c.run(stages, labels_tsv=a.labels, page=a.page if os.path.exists(a.page) else None)
    json.dump(diploma, open(os.path.join(a.out, 'diploma-final.json'), 'w'),
              ensure_ascii=False, indent=1)
    ok = sum(1 for d in diploma if d['passed'])
    print(f'\nСДАНО: {ok}/{len(diploma)} уровней')


if __name__ == '__main__':
    main()
