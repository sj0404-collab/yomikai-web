"""Предсказание эффекта интеграции в приложение: чтец приложения (rec) против gentle.

Считает ровно как Kotlin-движок приложения: rec — 48 px, 3 канала, словарь koma
(blank первым), поля до 320; eslav — 32 px, серый, /127.5-1, blank = 109.
Выбор — по словарю, как pickBetter в core.js.
"""
import sys
import cv2
import numpy as np
import onnxruntime as ort

sys.path.insert(0, '/home/user/evalwork')
sys.path.insert(0, '/home/user/ownocr')
import gen                                     # noqa: E402
from ownocr.pair import cer, clean             # noqa: E402
from holdout import split                      # noqa: E402

VOCAB = set(w.strip().upper() for w in
            open('/home/user/ownocr/ownocr/vocab-ru.txt', encoding='utf-8') if w.strip())
PUN = '.,!?…—«»"():;%-–'


def lexw(t):
    return sum(len(w.strip(PUN)) for w in (t or '').split()
               if len(w.strip(PUN)) >= 3 and w.strip(PUN).upper() in VOCAB)


class AppRec:
    """koma_rec: 48 px, 3 канала, словарь blank-первым, поля до 320."""

    def __init__(self, model='/home/user/web-ocr/models/koma_rec.onnx',
                 dict_path='/home/user/evalwork/apk_charset.txt'):
        self.s = ort.InferenceSession(model, providers=['CPUExecutionProvider'])
        self.inp = self.s.get_inputs()[0].name
        lines = open(dict_path, encoding='utf-8').read().split('\n')
        self.dict = [''] + [l for l in lines if l] + [' ']

    def read(self, gray):
        h, w = gray.shape[:2]
        width = int(max(8, min(960, round(48.0 * w / max(1, h)))))
        padded = max(320, width)
        im = cv2.resize(gray, (width, 48), interpolation=cv2.INTER_LINEAR)
        f = np.full((1, 3, 48, padded), -1.0, np.float32)
        v = im.astype(np.float32) / 255.0
        v = (v - 0.5) / 0.5
        for ch in range(3):
            f[0, ch, :, :width] = v
        out = self.s.run(None, {self.inp: f})[0]
        out = np.asarray(out).reshape(-1, out.shape[-1])
        idx = out.argmax(axis=1)
        res, prev = [], 0
        for i in idx:
            if i != 0 and i != prev and i < len(self.dict):
                res.append(self.dict[i])
            prev = i
        return ''.join(res)


class Eslav:
    def __init__(self, model='/home/user/web-ocr/models/eslav-hard.onnx'):
        self.s = ort.InferenceSession(model, providers=['CPUExecutionProvider'])
        self.inp = self.s.get_inputs()[0].name
        self.cs = open('/home/user/web-ocr/models/charset.txt', encoding='utf-8').read().rstrip('\n')
        self.blank = len(self.cs)

    def read(self, gray):
        h, w = gray.shape[:2]
        H = 32
        ww = max(8, int(round(w * H / max(1, h))))
        im = cv2.resize(gray, (ww, H), interpolation=cv2.INTER_AREA).astype(np.float32)
        x = (im / 127.5 - 1.0)[None, None]
        out = self.s.run(None, {self.inp: x})[0]
        out = np.asarray(out).reshape(-1, out.shape[-1])
        idx = out.argmax(axis=1)
        res, prev = [], -1
        for i in idx:
            if i != prev and i < self.blank:
                res.append(self.cs[i])
            prev = i
        return ''.join(res)


tr, te = split()
app, esl = AppRec(), Eslav()
ca = ce = cp = 0.0
pe = 0
for it in te:
    ta = app.read(it['gray'])
    tb = esl.read(it['gray'])
    ref = it['text']
    ca += cer(clean(ref), clean(ta))
    ce += cer(clean(ref), clean(tb))
    pick = tb if lexw(tb) > lexw(ta) else ta
    if pick is tb:
        pe += 1
    cp += cer(clean(ref), clean(pick))
n = len(te)
print(f'строк {n}')
print(f'  чтец приложения (rec)        {100*ca/n:5.2f} %')
print(f'  eslav-gentle                 {100*ce/n:5.2f} %')
print(f'  выбор по словарю (как в АПК) {100*cp/n:5.2f} % · eslav выбран в {100*pe/n:.0f} % строк')
