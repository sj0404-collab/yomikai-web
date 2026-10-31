#!/usr/bin/env python3
"""Дообученную CTC-модель — в ONNX, чтобы её читал движок без torch."""
import os, sys
import numpy as np, torch
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ownocr.eslav as E

src = os.path.join(ROOT, 'out', 'eslav-ft.pt')
dst = os.path.join(ROOT, 'out', 'eslav-ft.onnx')
net = E.build_torch()
net.load_state_dict(torch.load(src, map_location='cpu'))
net.eval()
dummy = torch.zeros(1, 1, 32, 64)
torch.onnx.export(net, dummy, dst, input_names=['x'], output_names=['logit'],
                  dynamic_axes={'x': {3: 'width'}, 'logit': {0: 'T'}},
                  opset_version=13, do_constant_folding=True)
print('сохранено:', dst, os.path.getsize(dst) // 1024, 'КБ')

# сверка torch ↔ onnx
import onnxruntime as ort
sess = ort.InferenceSession(dst, providers=['CPUExecutionProvider'])
import cv2
for f in ['data-real/01.png', 'data-real/05.png']:
    g = cv2.imread(os.path.join(ROOT, f), cv2.IMREAD_GRAYSCALE)
    x = E.prepare(g)
    with torch.no_grad():
        a = net(torch.from_numpy(x)).numpy()
    b = sess.run(None, {'x': x})[0]
    print(f'{f}: torch {E.decode_logits(a.reshape(-1, a.shape[-1]))!r} · '
          f'onnx {E.decode_logits(b.reshape(-1, b.shape[-1]))!r} · '
          f'расхождение {float(np.abs(a - b).max()):.2e}')
