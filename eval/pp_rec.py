"""Замер готового чтеца кириллицы PP-OCRv3 (deepghs/paddleocr) на нашем наборе.

Вход PP-OCR: серая строка → высота 48, ширина пропорционально (кратно 8), x/127.5-1.
Декод CTC без словаря (blank = последний класс).
"""
import json
import sys

import cv2
import numpy as np
import onnxruntime as ort

sys.path.insert(0, '/home/user/evalwork')
import gen  # noqa: E402
import holdout  # noqa: E402


def prep(gray, width_cap=640, invert_if_dark=True):
    h, w = gray.shape[:2]
    if invert_if_dark:
        # PP-OCR ждёт тёмный текст на светлом: если фон тёмный — инвертируем
        if np.median(gray) < 110:
            gray = 255 - gray
    th = 48
    tw = max(16, min(width_cap, int(round(w * th / max(1, h)))))
    tw = (tw + 7) // 8 * 8
    im = cv2.resize(gray, (tw, th), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    im = (im / 127.5 - 1.0)[None, None, :, :]        # [1,1,48,W]
    im = np.repeat(im, 3, axis=1)                     # [1,3,48,W]
    return im, tw


class PPRec:
    def __init__(self, model='/home/user/evalwork/pp/model.onnx',
                 dict_path='/home/user/evalwork/pp/dict.txt'):
        self.s = ort.InferenceSession(model, providers=['CPUExecutionProvider'])
        self.inp = self.s.get_inputs()[0].name
        chars = open(dict_path, encoding='utf-8').read().split('\n')
        if chars and chars[-1] == '':
            chars = chars[:-1]
        self.chars = [''] + chars + [' ']      # CTC blank первым
        print('вход модели:', self.s.get_inputs()[0].shape, 'классов', len(self.chars))

    def read(self, gray):
        im, tw = prep(gray)
        out = self.s.run(None, {self.inp: im})[0]
        idx = out.argmax(axis=-1)[0]
        conf = out.max(axis=-1)[0]
        res, prev, cs = [], -1, []
        for k, p in enumerate(idx):
            if p != prev and p != 0:
                res.append(self.chars[p] if p < len(self.chars) else '?')
                cs.append(float(conf[k]))
            prev = p
        return ''.join(res), (float(np.mean(cs)) if cs else 0.0)


def cer(ref, hyp):
    if not ref:
        return 0.0
    d = np.zeros((len(ref) + 1, len(hyp) + 1), np.int32)
    d[:, 0] = np.arange(len(ref) + 1)
    d[0, :] = np.arange(len(hyp) + 1)
    for i in range(1, len(ref) + 1):
        for j in range(1, len(hyp) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1,
                          d[i - 1, j - 1] + (ref[i - 1] != hyp[j - 1]))
    return d[len(ref), len(hyp)] / max(len(ref), len(hyp))


if __name__ == '__main__':
    m = PPRec()
    rows = [r for r in gen.items() if r['page'] not in holdout.HOLDOUT]
    tot = 0.0
    errs = []
    for r in rows:
        hyp, cf = m.read(r['gray'])
        c = cer(r['text'].lstrip('*'), hyp)
        tot += c
        errs.append((c, r['text'][:40], hyp[:40]))
    print(f'PP-OCRv3 кириллица: CER {100*tot/len(rows):.1f} % на {len(rows)} строках')
    errs.sort(reverse=True)
    for c, ref, hyp in errs[:12]:
        print(f'  {c:.2f}  эталон {ref!r} → {hyp!r}')
    json.dump([[c, r, h] for c, r, h in errs], open('/home/user/evalwork/pp_errors.json', 'w'))
