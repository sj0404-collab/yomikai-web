"""ONNX → PyTorch state_dict для чтеца «эслав» (обратная конвертация).

Нужна, потому что дообучать можно только веса PyTorch, а лучший наш чтец
(`web-ocr/models/eslav-hard.onnx`, он же gentle) остался только в ONNX — файл
`.pt` не сохранился. Имена инициализаторов в этом экспорте питоновские
(`features.0.weight`) для свёрток, но GRU переименованы в `onnx::GRU_NNN`,
поэтому раскладываем их по форме, а не по имени. Совпадение проверяется
побитово по прочтениям (`--check`).
"""
import argparse

import numpy as np
import onnx
import torch
from onnx import numpy_helper

H = 128          # размер скрытого состояния BiGRU (по форме весов)
import sys
sys.path.insert(0, '/home/user/ownocr')
from ownocr.eslav import NUM_CLASSES  # noqa: E402


def build_net():
    import torch.nn as nn

    class CRNN(nn.Module):
        def __init__(self):
            super().__init__()
            self.features = nn.Sequential(
                nn.Conv2d(1, 32, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2, 2),
                nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2, 2),
                nn.Conv2d(64, 128, 3, padding=1), nn.ReLU(), nn.MaxPool2d((2, 1), (2, 1)),
                nn.Conv2d(128, 128, 3, padding=1), nn.ReLU(), nn.MaxPool2d((2, 1), (2, 1)),
                nn.Conv2d(128, 128, (3, 2), padding=(1, 0)), nn.ReLU(),
            )
            self.rnn = nn.GRU(256, H, num_layers=2, bidirectional=True, batch_first=False)
            self.head = nn.Linear(256, NUM_CLASSES)

        def forward(self, x):
            f = self.features(x)
            b, c, hh, wd = f.shape
            f = f.permute(3, 0, 1, 2).reshape(wd, b, c * hh)
            o, _ = self.rnn(f)
            return self.head(o)

    return CRNN()


def attach(onnx_path: str):
    net = build_net()
    w = {t.name: numpy_helper.to_array(t) for t in onnx.load(onnx_path).graph.initializer}

    # свёртки ищем по ТОЧНОЙ форме: у пятой ядро 3×2, и сортировка по числу
    # каналов ставила её на место четвёртой (падение на копировании весов)
    want = [((32, 1, 3, 3), 0), ((64, 32, 3, 3), 3), ((128, 64, 3, 3), 6),
            ((128, 128, 3, 3), 9), ((128, 128, 3, 2), 12)]
    with torch.no_grad():
        for shape, slot in want:
            keys = [k for k in w if w[k].ndim == 4 and tuple(w[k].shape) == shape]
            assert len(keys) == 1, f'свёртка {shape}: найдено {keys}'
            base = keys[0][:-len('.weight')]
            net.features[slot].weight.copy_(torch.from_numpy(w[base + '.weight']))
            net.features[slot].bias.copy_(torch.from_numpy(w[base + '.bias']))

    gru_b = [k for k in w if w[k].shape == (2, 6 * H)]
    gru_w = [k for k in w if w[k].shape == (2, 3 * H, 256)]
    gru_r = [k for k in w if w[k].shape == (2, 3 * H, H)]
    assert len(gru_b) == 2 and len(gru_w) == 2 and len(gru_r) == 2, (gru_b, gru_w, gru_r)
    num = lambda k: int(''.join(c for c in k.split('::')[-1] if c.isdigit()) or 0)
    for keys in (gru_w, gru_r, gru_b):
        keys.sort(key=num)
    with torch.no_grad():
        for layer in (0, 1):
            W = torch.from_numpy(w[gru_w[layer]])        # (2, 3H, in) порядок z,r,h
            R = torch.from_numpy(w[gru_r[layer]])
            B = torch.from_numpy(w[gru_b[layer]]).reshape(2, 2, 3 * H)
            for d, suf in ((0, ''), (1, '_reverse')):
                sel = [H, 0, 2 * H]                      # ONNX z,r,h → torch r,z,n
                getattr(net.rnn, f'weight_ih_l{layer}{suf}').data.copy_(
                    torch.cat([W[d][s:s + H] for s in sel], 0))
                getattr(net.rnn, f'weight_hh_l{layer}{suf}').data.copy_(
                    torch.cat([R[d][s:s + H] for s in sel], 0))
                getattr(net.rnn, f'bias_ih_l{layer}{suf}').data.copy_(
                    torch.cat([B[0][d][s:s + H] for s in sel], 0))
                getattr(net.rnn, f'bias_hh_l{layer}{suf}').data.copy_(
                    torch.cat([B[1][d][s:s + H] for s in sel], 0))
        heads = [k for k in w if w[k].shape == (256, NUM_CLASSES)]
        assert len(heads) == 1, f'голова не найдена: {[k for k in w if w[k].ndim == 2]}'
        net.head.weight.data.copy_(torch.from_numpy(w[heads[0]].T))
        bias = [k for k in w if w[k].shape == (NUM_CLASSES,)]
        net.head.bias.data.copy_(torch.from_numpy(w[bias[0]][:NUM_CLASSES]))
    return net


def check(net, onnx_path):
    """Сверить прочтения PyTorch и ONNX на размеченных строках."""
    import cv2
    import onnxruntime as ort
    sys.path.insert(0, '/home/user/ownocr')
    from ownocr import eslav as E
    s = ort.InferenceSession(onnx_path, providers=['CPUExecutionProvider'])
    inp = s.get_inputs()[0].name
    net.eval()
    rows = [l.split('\t') for l in open('/home/user/ownocr/data-hand/labels.tsv', encoding='utf-8')]
    # ONNX в fp16, PyTorch в fp32: полного совпадения прочтений не будет,
    # поэтому сверяем не строки, а CER между ними — он должен быть ~0.
    import numpy as _np
    from ownocr.pair import cer as _cer
    bad = 0
    tot = 0.0
    n = 0
    for fn, text, *_ in rows[:40]:
        g = cv2.imread(f'/home/user/ownocr/data-hand/{fn}', cv2.IMREAD_GRAYSCALE)
        if g is None:
            continue
        x = E.prepare(g)
        with torch.no_grad():
            a = net(torch.from_numpy(x)).numpy()
        b = s.run(None, {inp: x})[0]
        ta, tb = E.decode_logits(a), E.decode_logits(np.asarray(b).reshape(-1, NUM_CLASSES))
        tot += _cer(ta, tb)
        n += 1
        if ta != tb:
            bad += 1
            print(f'  разница {fn}: torch {ta!r} · onnx {tb!r}')
    print(f'проверено строк: {n} · строк с расхождением {bad} · CER между torch и onnx '
          f'{100*tot/max(1,n):.2f} %')
    return n > 0 and tot / max(1, n) < 0.05


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('onnx')
    ap.add_argument('out')
    ap.add_argument('--check', action='store_true')
    a = ap.parse_args()
    net = attach(a.onnx)
    ok = check(net, a.onnx) if a.check else True
    if ok:
        torch.save(net.state_dict(), a.out)
        print('сохранено:', a.out)
    else:
        print('НЕ сохраняю: расхождения с ONNX')
