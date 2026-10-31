"""Дообучаемая CTC-модель «эслав»: CRNN (5 свёрток → BiGRU ×2 → линейный слой).

Веса берём из `koma_models/extra/best_finetuned_r4.onnx` — чужая обученная модель
на чистом печатном тексте: 109 символов кириллицы, класс 109 означает «пусто».
Здесь она пересобрана в PyTorch один в один, чтобы её можно было дообучать на
настоящих строках манги и манхвы: через ONNX считать можно, учить — нельзя.

Ключевые детали, на которых легко ошибиться и которые здесь учтены:
  * «пусто» — это класс 109, а не 0 (иначе декод выдаёт «О9П9З9Б9Д9С9…»);
  * порядок вентилей GRU в ONNX — z, r, h, а в PyTorch — r, z, n;
  * смещения ONNX [2, 6H] раскладываются на bias_ih (Wb) и bias_hh (Rb);
  * голова — MatMul [256, 111], в PyTorch это Linear с транспонированным весом.

Совпадение с ONNX проверяется скриптом `scripts/dev_eslav_parity.py`.
"""
from __future__ import annotations

import numpy as np

def _charset() -> str:
    """Азбука модели. Одна и та же в трёх местах: рядом с кодом, в наборе
    моделей и в приложении — берём первую доступную, чтобы файл работал и в
    репозитории, и на машине разработчика."""
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in (os.path.join(here, 'charset.txt'),
                 '/home/user/koma_models/extra/charset.txt',
                 '/home/user/koma-web/charset.txt'):
        if os.path.exists(path):
            return open(path, encoding='utf-8').read().rstrip('\n')
    raise FileNotFoundError('нет charset.txt — нечем декодировать выход модели')


CHARSET = _charset()
LETTERS = list(CHARSET)
BLANK = len(LETTERS)                     # 109 — «пусто»
NUM_CLASSES = BLANK + 2                  # 111: 109 символов + «пусто» + резерв

CHAR_TO_IDX = {c: i + 1 for i, c in enumerate(LETTERS)}
IDX_TO_CHAR = {i + 1: c for i, c in enumerate(LETTERS)}


def encode(text: str) -> list[int]:
    return [CHAR_TO_IDX[c] for c in text if c in CHAR_TO_IDX]


def decode_logits(logits: np.ndarray) -> str:
    a = np.asarray(logits)
    if a.ndim == 3:                      # (T, 1, C) — как отдаёт ONNX
        a = a[:, 0, :] if a.shape[1] == 1 else a[0]
    idx = a.argmax(axis=-1)
    out, prev = [], -1
    for i in idx:
        if i != prev and i < BLANK:
            out.append(LETTERS[i])
        prev = i
    return ''.join(out)


def _onnx_weights(path: str) -> dict:
    import onnx
    from onnx import numpy_helper
    m = onnx.load(path)
    return {t.name: numpy_helper.to_array(t) for t in m.graph.initializer}


def base_weights_path() -> str:
    """Откуда брать исходные веса: сначала репозиторий, потом машина разработчика.

    Раньше путь был зашит на `/home/user/koma_models/…`, из-за этого скрипт
    обучения не запускался на раннере GitHub.
    """
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in (os.environ.get('OWNOCR_ESLAV_BASE', ''),
                 os.path.join(here, 'model', 'eslav', 'base.onnx'),
                 '/home/user/koma_models/extra/best_finetuned_r4.onnx'):
        if path and os.path.exists(path):
            return path
    raise FileNotFoundError('нет исходных весов «эслава» (base.onnx)')


def build_torch(path: str | None = None):
    """Собрать сеть и загрузить веса из ONNX."""
    import torch
    import torch.nn as nn

    w = _onnx_weights(path or base_weights_path())

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
            # PyTorch считает вентиль так же, как ONNX с linear_before_reset=1;
            # отдельного флага в nn.GRU нет, поэтому просто не передаём его.
            self.rnn = nn.GRU(256, 128, num_layers=2, bidirectional=True,
                              batch_first=False)
            self.head = nn.Linear(256, NUM_CLASSES)

        def forward(self, x):
            f = self.features(x)                       # (B, 128, 2, W)
            b, c, h, wd = f.shape
            f = f.permute(3, 0, 1, 2).reshape(wd, b, c * h)
            o, _ = self.rnn(f)
            return self.head(o)                        # (T, B, 111)

    net = CRNN()
    conv_idx = {0: 'conv.0', 3: 'conv.3', 6: 'conv.6', 9: 'conv.9', 12: 'conv.12'}
    with torch.no_grad():
        for i, prefix in conv_idx.items():
            net.features[i].weight.copy_(torch.from_numpy(w[f'{prefix}.weight']))
            net.features[i].bias.copy_(torch.from_numpy(w[f'{prefix}.bias']))
        for layer, (wn, rn, bn) in enumerate(
                [('onnx::GRU_392', 'onnx::GRU_393', 'onnx::GRU_391'),
                 ('onnx::GRU_437', 'onnx::GRU_438', 'onnx::GRU_436')]):
            W = torch.from_numpy(w[wn])                # (2, 3H, in) порядок z,r,h
            R = torch.from_numpy(w[rn])                # (2, 3H, H)
            H = 128
            # B в ONNX: [2, 6H] — сначала Wb (3H), потом Rb (3H), на каждое
            # направление. Раскладываем: B[0] → bias_ih, B[1] → bias_hh.
            B = torch.from_numpy(w[bn]).reshape(2, 2, 3 * H)     # (вход/скрытое, dir, 3H)
            for d, suffix in ((0, ''), (1, '_reverse')):
                # ONNX: z, r, h  →  PyTorch: r, z, n
                w_ih = torch.cat([W[d][s:s + H] for s in (H, 0, 2 * H)], dim=0)
                w_hh = torch.cat([R[d][s:s + H] for s in (H, 0, 2 * H)], dim=0)
                b_ih = torch.cat([B[0][d][s:s + H] for s in (H, 0, 2 * H)], dim=0)
                b_hh = torch.cat([B[1][d][s:s + H] for s in (H, 0, 2 * H)], dim=0)
                getattr(net.rnn, f'weight_ih_l{layer}{suffix}').data.copy_(w_ih)
                getattr(net.rnn, f'weight_hh_l{layer}{suffix}').data.copy_(w_hh)
                getattr(net.rnn, f'bias_ih_l{layer}{suffix}').data.copy_(b_ih)
                getattr(net.rnn, f'bias_hh_l{layer}{suffix}').data.copy_(b_hh)
        net.head.weight.data.copy_(torch.from_numpy(w['onnx::MatMul_439'].T))
        net.head.bias.data.copy_(torch.from_numpy(w['head.bias'][:NUM_CLASSES]))
    return net


def prepare(gray: np.ndarray, height: int = 32) -> np.ndarray:
    """Кроп строки → тензор (1, 1, 32, W) в той же нормировке, что ждёт модель."""
    import cv2
    g = gray
    if g.ndim == 3:
        g = cv2.cvtColor(g, cv2.COLOR_RGB2GRAY)
    w = max(8, int(round(g.shape[1] * height / max(1, g.shape[0]))))
    img = cv2.resize(g, (w, height), interpolation=cv2.INTER_AREA)
    # Нормировка — /127.5-1. Замер на отложенных строках говорил в пользу /255
    # (8.0 % против 12.1 %), но на целых страницах наоборот: /255 даёт 10.6 %
    # против 2.7 % при /127.5-1. Причина не выяснена — кропы страниц крупнее и
    # шумнее. Критерий приёмки — страницы, поэтому оставлено /127.5-1.
    x = img.astype(np.float32) / 127.5 - 1.0
    return x[None, None]
