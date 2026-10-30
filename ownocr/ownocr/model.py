"""Свой классификатор: softmax-регрессия с одним скрытым слоем.

Здесь нет ни одной готовой обученной модели — только математика:

    z1 = X·W1 + b1            (линейный слой)
    h  = max(0, z1)           (ReLU)
    z2 = h·W2 + b2            (оценки классов)
    p  = exp(z2 - max) / Σexp  (softmax, устойчивый через максимум)
    L  = -log p[верный класс] + λ/2·‖W‖²   (перекрёстная энтропия + L2)

Градиенты считаются вручную (backprop), шаг — Adam. Всё на numpy, матричное
умножение — это то же, что делает калькулятор, только на 135 чисел сразу.

Отдельно — «учительская» работа: на ошибках видно, какие пары букв ученик путает,
и по ним можно адресно добавить примеры (см. teach.py).
"""
from __future__ import annotations

import json
import os

import numpy as np


class OwnClassifier:
    def __init__(self, d_in: int, n_cls: int, hidden: int = 192, seed: int = 0,
                 l2: float = 3e-5):
        rng = np.random.default_rng(seed)
        self.d_in, self.n_cls, self.hidden, self.l2 = d_in, n_cls, hidden, l2
        self.W1 = (rng.standard_normal((d_in, hidden)) * np.sqrt(2.0 / d_in)).astype(np.float32)
        self.b1 = np.zeros(hidden, np.float32)
        self.W2 = (rng.standard_normal((hidden, n_cls)) * np.sqrt(2.0 / hidden)).astype(np.float32)
        self.b2 = np.zeros(n_cls, np.float32)
        self.m = {k: np.zeros_like(v) for k, v in self._params().items()}
        self.v = {k: np.zeros_like(v) for k, v in self._params().items()}
        self.step = 0

    # ── параметры ────────────────────────────────────────────────────────────
    def _params(self) -> dict:
        return {'W1': self.W1, 'b1': self.b1, 'W2': self.W2, 'b2': self.b2}

    # ── прямой проход ────────────────────────────────────────────────────────
    def _forward(self, X: np.ndarray):
        z1 = X @ self.W1 + self.b1
        h = np.maximum(z1, 0.0)
        z2 = h @ self.W2 + self.b2
        z2 = z2 - z2.max(axis=1, keepdims=True)                  # устойчивый softmax
        e = np.exp(z2)
        s = e.sum(axis=1, keepdims=True)
        logp = z2 - np.log(s)                                    # логарифм правдоподобия
        return h, z1, logp

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        h, _, logp = self._forward(X)
        return np.exp(logp)

    def loss_and_grad(self, X: np.ndarray, y: np.ndarray, w: np.ndarray | None = None,
                      soft: np.ndarray | None = None, lam: np.ndarray | None = None):
        """Перекрёстная энтропия (+ необязательная дистилляция от учителя).

        soft/lam — мягкие цели старой модели и вес дистилляции по строке. Смысл:
        новый материал тянет веса на себя, а дистилляция держит ответы на старом
        материале такими, какими они были у учителя, — тогда ученик не забывает
        пройденное, даже не видя старых экзаменов.
        """
        n = len(y)
        h, z1, logp = self._forward(X)
        p = np.exp(logp)
        ll = -logp[np.arange(n), y]
        if w is None:
            loss = ll.mean()
        else:
            w = w / w.sum()
            loss = float((ll * w).sum())
        # градиент перекрёстной энтропии по логитам
        dz2 = p.copy()
        dz2[np.arange(n), y] -= 1.0
        if soft is not None and lam is not None:
            # KL(q‖p) по строкам, где q — ответы учителя
            eps = 1e-8
            kl = (soft * (np.log(soft + eps) - logp)).sum(axis=1)
            loss = loss + float((lam * kl).mean())
            dz2 += lam[:, None] * (p - soft)
        if w is not None:
            dz2 *= (w * n)[:, None]
        dz2 /= n
        dW2 = h.T @ dz2 + self.l2 * self.W2
        db2 = dz2.sum(axis=0)
        dh = dz2 @ self.W2.T
        dh[z1 <= 0] = 0.0
        dW1 = X.T @ dh + self.l2 * self.W1
        db1 = dh.sum(axis=0)
        return loss, {'W1': dW1, 'b1': db1, 'W2': dW2, 'b2': db2}

    def adam(self, grads: dict, lr: float, b1=0.9, b2=0.999, eps=1e-8):
        self.step += 1
        for k, g in grads.items():
            self.m[k] = b1 * self.m[k] + (1 - b1) * g
            self.v[k] = b2 * self.v[k] + (1 - b2) * (g * g)
            mh = self.m[k] / (1 - b1 ** self.step)
            vh = self.v[k] / (1 - b2 ** self.step)
            self._params()[k] -= (lr * mh / (np.sqrt(vh) + eps)).astype(np.float32)

    # ── обучение ─────────────────────────────────────────────────────────────
    def fit(self, X, y, epochs=6, batch=256, lr=1e-3, seed=0, log=None,
            sample_weight=None, on_epoch=None, soft=None, lam=None):
        rng = np.random.default_rng(seed)
        n = len(y)
        hist = []
        for ep in range(epochs):
            order = rng.permutation(n)
            total, seen = 0.0, 0
            for i in range(0, n - batch + 1, batch):
                idx = order[i:i + batch]
                w = None if sample_weight is None else sample_weight[idx]
                so = None if soft is None else soft[idx]
                la = None if lam is None else lam[idx]
                loss, grads = self.loss_and_grad(X[idx], y[idx], w, so, la)
                self.adam(grads, lr)
                total += loss * len(idx)
                seen += len(idx)
            hist.append(total / max(1, seen))
            if log:
                log(f'      эпоха {ep + 1:2d}/{epochs}: −log p = {hist[-1]:.4f}')
            if on_epoch:
                on_epoch(ep + 1)
        return hist

    def accuracy(self, X, y) -> float:
        return float((self.predict_proba(X).argmax(axis=1) == y).mean())

    # ── сохранение ───────────────────────────────────────────────────────────
    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez_compressed(path, W1=self.W1, b1=self.b1, W2=self.W2, b2=self.b2)

    def load(self, path: str):
        z = np.load(path)
        self.W1, self.b1, self.W2, self.b2 = z['W1'], z['b1'], z['W2'], z['b2']
        self.m = {k: np.zeros_like(v) for k, v in self._params().items()}
        self.v = {k: np.zeros_like(v) for k, v in self._params().items()}
        return self
