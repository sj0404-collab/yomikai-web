#!/usr/bin/env python3
"""Седьмой урок: научить ученика читать настоящую страницу манги.

    python3 scripts/04_lesson_real.py
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ownocr.lesson_real import run   # noqa: E402


def default_labels():
    """Строки манги: своя копия, иначе общий набор из корня репозитория."""
    here = os.path.join(ROOT, 'data-real', 'labels.tsv')
    if os.path.exists(here):
        return here
    return os.path.join(ROOT, '..', 'data', 'lines-real', 'labels.tsv')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sheet', default=os.path.join(ROOT, 'out', 'sheet.png'))
    ap.add_argument('--manifest', default=os.path.join(ROOT, 'out', 'sheet-manifest.json'))
    ap.add_argument('--labels', default=default_labels())
    ap.add_argument('--model', default=os.path.join(ROOT, 'model'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'out'))
    ap.add_argument('--test-every', type=int, default=3)
    ap.add_argument('--epochs', type=int, default=8)
    a = ap.parse_args()
    run(a.sheet, a.manifest, a.labels, a.model, a.out,
        test_every=a.test_every, epochs=a.epochs)


if __name__ == '__main__':
    main()
