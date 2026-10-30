#!/usr/bin/env python3
"""Запуск курса обучения: учитель ведёт ученика по листу.

    python3 scripts/03_teach.py                 # все шесть уроков
    python3 scripts/03_teach.py --lessons 1,2,3 # только первые три
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr.teach import Teacher   # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', default=os.path.join(ROOT, 'out', 'sheet.png'))
    ap.add_argument('--manifest', default=os.path.join(ROOT, 'out', 'sheet-manifest.json'))
    ap.add_argument('--model', default=os.path.join(ROOT, 'model', 'ownocr.npz'))
    ap.add_argument('--lessons', default='1,2,3,4,5,6')
    ap.add_argument('--out', default=os.path.join(ROOT, 'out'))
    args = ap.parse_args()

    t = Teacher(args.sheet, args.manifest, args.model, args.out)
    t.run([int(x) for x in args.lessons.split(',') if x.strip()])


if __name__ == '__main__':
    main()
