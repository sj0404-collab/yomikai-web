"""Модель распознавателя строк: CRNN (свёртки → BiLSTM → CTC), повторяющая
контракт koma_rec.onnx — вход [N,3,48,W], выход [N,T,519], T = W/8.

Смысл: приложение (part3.js, recProbs) ждёт вероятности по 519 классам и умеет
их и жадно разбирать (decodeCrop), и отдавать своему словарному beam-декодеру
(beamDecode). Поэтому модель обучена отдавать softmax, а не логиты.
"""
from __future__ import annotations

import torch
import torch.nn as nn

from charset import load_charset, num_classes


class RecCTC(nn.Module):
    def __init__(self, n_classes: int = None, hid: int = 128, feat: int = 256):
        super().__init__()
        n_classes = n_classes or num_classes(load_charset())
        self.n_classes = n_classes
        self.cnn = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(True),
            nn.MaxPool2d(2, 2),                                  # 48 → 24, W → W/2
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(True),
            nn.MaxPool2d(2, 2),                                  # 24 → 12, W/2 → W/4
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(True),
            nn.MaxPool2d(2, 2),                                  # 12 → 6,  W/4 → W/8
            nn.Conv2d(128, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(True),
        )
        self.fc = nn.Linear(128 * 6, feat)                       # 6 = 48/8 — высота после свёрток
        self.rnn = nn.LSTM(feat, hid, num_layers=1, bidirectional=True, batch_first=True)
        self.out = nn.Linear(2 * hid, n_classes)

    def forward(self, x, probabilities: bool = True):
        """x: [N,3,48,W] → [N,T,C]; probabilities=False отдаёт логарифмы (для CTC)."""
        f = self.cnn(x)                                          # [N,128,6,W/8]
        n, c, h, w = f.shape
        f = f.permute(0, 3, 1, 2).reshape(n, w, c * h)           # [N,T,768]
        f = torch.relu(self.fc(f))
        f, _ = self.rnn(f)
        logits = self.out(f)
        return torch.log_softmax(logits, dim=-1) if not probabilities else \
            torch.softmax(logits, dim=-1)

    # удобное имя для экспорта: ONNX всегда отдаёт вероятности
    def export_forward(self, x):
        return self.forward(x, probabilities=True)


class ExportWrapper(nn.Module):
    """Обёртка для torch.onnx.export: фиксирует выход «вероятности» и имя выхода."""

    def __init__(self, model: RecCTC):
        super().__init__()
        self.model = model

    def forward(self, x):
        return self.model.forward(x, probabilities=True)


def apply_class_prior(model: RecCTC, charset: str, used: str, floor: float = -8.0) -> None:
    """Приглушить на старте классы, которых в обучающих данных нет.

    Классов 519, а букв в строках — около сотни. Без этого softmax первые сотни
    шагов тратит на «погасить» 400 лишних классов, и CTC долго стоит на месте
    (первый прогон 27.10: потеря 3,6 не двигалась 14 эпох). Значения остаются
    теми же классами контракта — меняется только начальное смещение.
    """
    with torch.no_grad():
        b = model.out.bias.clone()
        for i in range(1, b.numel()):        # i=0 — blank, его не трогаем
            if i <= len(charset):
                ch = charset[i - 1]
            elif i == len(charset) + 1:
                ch = " "                      # пробел — последний класс
            else:
                ch = ""
            if ch == "" or ch not in used:
                b[i] = floor
        model.out.bias.copy_(b)


def build(n_classes: int = None) -> RecCTC:
    return RecCTC(n_classes)
