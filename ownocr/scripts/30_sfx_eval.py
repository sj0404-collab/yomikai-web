#!/usr/bin/env python3
"""Замер распознавания ЗВУКОВ (SFX): находит ли движок «ХА-ХА-ХА», «ГОНГ», «ШИЕП».

Зачем отдельный замер: звук и реплику нельзя путать. Реплику читаем голосом,
звук — играем эффектом и голосом НЕ читаем. Поэтому считаем recall (сколько
настоящих звуков узнали) и precision (сколько из названных звуков — правда звуки),
а не CER.

    python3 scripts/30_sfx_eval.py
"""
import json
import os
import sys

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ownocr.pair import CtcLineReader, CtcReader            # noqa: E402

# тот же словарь звукоподражаний, что в браузере (web/core.js) — держим в одном месте
SFX_WORDS = {
    'ГОНГ': 'gong', 'ДЗЫНЬ': 'gong', 'ДОН': 'gong', 'БОМ': 'gong',
    'УДАР': 'hit', 'БАМ': 'hit', 'БАХ': 'hit', 'БУХ': 'hit', 'ТКАДЫ': 'hit',
    'ХРЯСЬ': 'hit', 'ТРЕСЬ': 'hit', 'КРАК': 'hit', 'ЧПОК': 'hit', 'ХЛОП': 'hit',
    'ХЛОБЫСЬ': 'slap', 'ШЛЁП': 'slap', 'ЩЁЛК': 'slap', 'ХЛОПОК': 'slap',
    'БУМ': 'boom', 'ВЗРЫВ': 'boom', 'ГРОХОТ': 'boom',
    'ШИЕП': 'whoosh', 'ШУХ': 'whoosh', 'ФЬЮ': 'whoosh', 'ВЖУХ': 'whoosh',
    'СВУШ': 'whoosh', 'ВЖИК': 'whoosh',
}


def bare(text):
    keep = 'АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ-'
    return ''.join(c if c in keep else ' ' for c in str(text).upper()).split()


def sfx_class(text):
    words = bare(text)
    if not words or len(words) > 3:
        return None
    cls, other = None, 0
    for w in words:
        flat = w.replace('-', '')
        parts = [p for p in w.split('-') if p]
        if len(parts) >= 2 and len(parts[0]) == 1 and all(p == parts[1] for p in parts[1:]):
            parts = parts[1:]
        if w in SFX_WORDS:
            cls = cls or SFX_WORDS[w]
            continue
        if flat in SFX_WORDS:
            cls = cls or SFX_WORDS[flat]
            continue
        if len(parts) >= 2 and all(p == parts[0] for p in parts) and len(parts[0]) <= 4:
            cls = cls or ('laugh' if parts[0].startswith('Х') else 'hit')
            continue
        if len(flat) >= 3 and set(flat) <= set('ХА') and flat.count('ХА') >= 2:
            cls = cls or 'laugh'
            continue
        other += 1
    return None if (not cls or other) else cls


def load(dirname, default_page):
    out, path = [], os.path.join(ROOT, dirname, 'labels.tsv')
    if not os.path.exists(path):
        return out
    for line in open(path, encoding='utf-8'):
        p = line.rstrip('\n').split('\t')
        img = cv2.imread(os.path.join(ROOT, dirname, p[0]))
        if img is None:
            continue
        out.append({'page': p[2] if len(p) > 2 else default_page,
                    'text': p[1], 'kind': p[3] if len(p) > 3 else 'voice', 'img': img})
    return out


def main():
    rows = []
    for d, dp in (('data-real', 'dense-a'), ('data-pages', 'p'), ('data-manhua', 'm'),
                  ('data-comic', 'c')):
        rows += load(d, dp)
    # «ГОНГ» с kuro-p1 руками: он не попал в строки страницы, но помечен как звук
    reader_app = CtcReader('/home/user/cand/q/koma_rec-fp16.onnx',
                           '/home/user/koma_models/koma_dict.txt')
    reader_esl = CtcLineReader(os.path.join(ROOT, 'model/eslav/eslav-ft-all.onnx'))

    # медиана высоты строки по странице — так же, как считает браузер
    import numpy as np
    med = {}
    for page in {r['page'] for r in rows}:
        hs = sorted(r['img'].shape[0] for r in rows if r['page'] == page)
        med[page] = float(np.median(hs))

    def look(r):
        h = r['img'].shape[0]
        if h <= med[r['page']] * 1.75:
            return None
        words = bare(r['got'])
        if len(words) > 3:
            return None
        return sfx_class(r['got']) or 'hit'

    tp = fp = fn = tn = 0
    wrong = []
    for r in rows:
        got = reader_esl.read(r['img'])[0] or reader_app.read(r['img'])[0]
        r['got'] = got
        cls = look(r) or sfx_class(got)
        is_sfx = r['kind'] == 'sfx'
        if is_sfx and cls:
            tp += 1
        elif is_sfx and not cls:
            fn += 1
            wrong.append(('пропустил звук', r['text'], got, r['page']))
        elif cls and not is_sfx:
            fp += 1
            wrong.append(('речь назвал звуком', r['text'], got, r['page']))
        else:
            tn += 1
    rec = tp / max(1, tp + fn)
    prec = tp / max(1, tp + fp)
    print(f'строк {len(rows)} · звуков в эталоне {tp + fn} · найдено {tp}')
    print(f'  узнал звуки (recall)   {100 * rec:.0f} %')
    print(f'  из названных звуков верно (precision) {100 * prec:.0f} %')
    print(f'  реплик, ошибочно принятых за звук: {fp} · звуков, ошибочно прочитанных как речь: {fn}')
    for kind, ref, got, page in wrong:
        print(f'   [{kind}] {page}: эталон {ref!r} → прочтено {got!r}')
    json.dump({'всего': len(rows), 'звуков': tp + fn, 'узнал': tp, 'recall': rec,
               'precision': prec, 'fp': fp, 'fn': fn},
              open(os.path.join(ROOT, 'out', 'sfx-eval.json'), 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
