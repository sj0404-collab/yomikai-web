"""Свободные роли: каждый чтец — отдельная роль, добавляется одной записью.

Зачем так. Специализация по типам текста полезна, но проверка на страницах
показала: голосовать всем обо всём — плохо (три чужие модели дали 7,5 % против
3,7 % с одной). Поэтому роль — это не «ещё один голос всегда», а чтец, у
которого есть:

  * **имя** — по нему видно, кто ошибся (в замерах и в отчёте);
  * **вес** — сколько стоит его голос; разный по зонам;
  * **зона** — где он вообще берётся за строку (`all`, `wide`, `dark`, `light`);
  * **сколько вариантов** он выдаёт на одну строку (растянутая, размытая).

Список ролей задаётся строкой, поэтому «хоть 5, хоть 10» — это одна переменная:

    OWNOCR_ROLES=eslav,eslav_stretch,base,app,alphabet

Новая роль = функция-фабрика и строка в `SPECS`. Голосование и взвешивание
трогать не надо: оно давно в `crew.foreman` и работает с любым числом работников.
"""
from __future__ import annotations

import os

import numpy as np

# ── в работе ──────────────────────────────────────────────────────────────────
# Только те роли, которые выиграли замер: см. docs/roles-sweep.json и
# docs/retrospective.json. Всё остальное — в ИДЕИ ниже.
SPECS: dict[str, tuple[float, str]] = {
    'app':             (0.55, 'распознаватель приложения (PP-OCR, 519 классов) — лучший голос'),
    'eslav':           (0.80, 'CTC-модель, дообученная на домене манги — живая манга'),
}

# ── задумки ───────────────────────────────────────────────────────────────────
# Проверены, но не в работе: каждая проиграла замер, хотя у каждой есть сильная
# сторона, которая однажды пригодится (другие шрифты, другие полосы). Включаются
# только явно: OWNOCR_ROLES_IDEAS=1.
IDEAS: dict[str, tuple[float, str]] = {
    'eslav_stretch':   (0.90, 'эслав с растяжкой 1.1: длинные строки лучше (20,0 % против 24,3 %), '
                              'короткие — хуже'),
    'eslav_otsu':      (0.70, 'эслав на ч/б по Отсу: другая сеть ошибок, иногда спасает плашку'),
    'eslav_blur':      (0.70, 'эслав на слегка размытом кропе: мягкие края манги'),
    'base':            (0.60, 'чужая базовая CTC-модель: 56,8 % на манге, но её веса — '
                              'материал для дообучения'),
    'alphabet':        (0.70, 'чтец, обученный ТОЛЬКО алфавиту: 85,3 % букв на незнакомых '
                              'шрифтах — главный запас на будущее'),
}


# Что включено по умолчанию — решено замером, а не вкусом. Перебор на трёх
# страницах (см. scripts/23_roles_sweep.py): 0 ролей 3.9 % · «эслав» 4.4 % ·
# «эслав»+растяжка 4.4 % · **распознаватель приложения 2.6 %** · он же вместе с
# «эславом» 3.1 % · семь ролей 8.5 %. Выигрывает ОДНА роль: голос приложения
# (PP-OCR, 519 классов). Каждая лишняя роль разбавляет её голос.
DEFAULT = 'app'


def enabled(spec: str | None = None) -> list[str]:
    """Какие роли включены.

    По умолчанию — только рабочие (`SPECS`). Задумки (`IDEAS`) подключаются
    осознанно: `OWNOCR_ROLES_IDEAS=1`, иначе они в бригаду не попадут даже если
    их явно назвали в списке.
    """
    raw = (spec if spec is not None else os.environ.get('OWNOCR_ROLES', DEFAULT))
    ideas_on = os.environ.get('OWNOCR_ROLES_IDEAS', '0') == '1'
    out = []
    for name in (x.strip() for x in raw.split(',') if x.strip()):
        if name in SPECS:
            out.append(name)
        elif name in IDEAS:
            if ideas_on:
                out.append(name)
            else:
                print(f'роль «{name}» — задумка, не в работе (включить: OWNOCR_ROLES_IDEAS=1)')
        else:
            print(f'роль «{name}» неизвестна — пропускаю (есть: {", ".join(list(SPECS) + list(IDEAS))})')
    return out


def weight_of(name: str) -> float:
    from .crew import WEIGHTS
    base = SPECS.get(name) or IDEAS.get(name) or (0.7, '')
    return float(WEIGHTS.get(name, base[0]))





# ── читатели ──────────────────────────────────────────────────────────────────

def _eslav_path() -> str:
    p = os.environ.get('OWNOCR_ESLAV_MODEL', '')
    if p and os.path.exists(p):
        return p
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in (os.path.join(here, 'model', 'eslav', 'eslav-ft.onnx'),
                 '/home/user/koma_models/extra/best_finetuned_r4.onnx'):
        if os.path.exists(cand):
            return cand
    return ''


def _base_path() -> str:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for cand in (os.path.join(here, 'model', 'eslav', 'base.onnx'),
                 '/home/user/koma_models/extra/best_base_r3.onnx'):
        if os.path.exists(cand):
            return cand
    return ''


class CtcRole:
    """Роль поверх CTC-модели: одна строка — одно или два прочтения."""

    def __init__(self, name: str, path: str, stretch: float = 1.0, wide_only: bool = False,
                 pre=None):
        from .pair import CtcLineReader, ESLAV_CONF
        self.reader = CtcLineReader(path)
        self.name = name
        self.stretch = float(stretch)
        self.wide_only = wide_only
        self.pre = pre
        self.conf = ESLAV_CONF

    def emit(self, gray: np.ndarray) -> list[tuple[str, float]]:
        import cv2
        from .pair import ESLAV_WIDE
        if self.wide_only and gray.shape[1] < ESLAV_WIDE:
            return []
        g = gray
        if self.pre == 'otsu':
            g = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        elif self.pre == 'blur':
            g = cv2.GaussianBlur(g, (0, 0), 0.8)
        text, _ = self.reader.read(g, stretch=self.stretch)
        return [(text, self.conf)] if text.strip() else []


class AppRole:
    """Распознаватель приложения: другой словарь, другой вход (3×48×W)."""

    def __init__(self):
        from .pair import CtcReader
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model = os.environ.get('OWNOCR_APP_REC', '/home/user/koma_models/koma_rec.onnx')
        dictionary = os.environ.get('OWNOCR_APP_DICT', '/home/user/koma_models/koma_dict.txt')
        self.name = 'app'
        self.ok = os.path.exists(model) and os.path.exists(dictionary)
        self.reader = CtcReader(model, dictionary) if self.ok else None

    def emit(self, gray: np.ndarray) -> list[tuple[str, float]]:
        if not self.ok:
            return []
        rgb = np.repeat(gray[:, :, None], 3, axis=2)
        text, conf = self.reader.read(rgb)
        # своя шкала уверенности: у PP-OCR она лежит в других пределах
        return [(text, 0.5)] if text.strip() else []


class AlphabetRole:
    """Чтец «только алфавит»: сеть на 109 буквах в 50 начертаниях.

    Режет строку тем же станком, что и наш ученик (`segment.pieces_as_boxes`), и
    каждую букву опознаёт свёрточной сетью, обученной не на шрифтах, а на
    алфавите: 85,3 % на начертаниях, которых в обучении не было.
    """

    def __init__(self, ocr, model: str = ''):
        import torch
        import torch.nn as nn
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.path = model or os.path.join(here, 'model', 'alphabet-only.pt')
        self.name = 'alphabet'
        self.ocr = ocr
        self.net = None
        if not os.path.exists(self.path):
            return
        from . import eslav as _E
        self.net = _AlphabetNet(len(_E.LETTERS))
        # Веса сохранялись у сети-обёртки (self.f = Sequential), поэтому ключи
        # приходят с префиксом «f.». Снимаем его — иначе state_dict не сходится
        # и роль молча не поднималась (в переборе это выглядело как «роль есть,
        # а цифры не изменились»).
        sd = torch.load(self.path, map_location='cpu')
        sd = {(k[2:] if k.startswith('f.') else k): v for k, v in sd.items()}
        self.net.load_state_dict(sd)
        self.net.eval()

    def emit(self, gray: np.ndarray) -> list[tuple[str, float]]:
        if self.net is None:
            return []
        import cv2
        import torch
        from .segment import pieces_as_boxes
        from . import eslav as E
        bw = (gray < 150).astype(np.uint8) * 255
        try:
            # pieces_as_boxes отдаёт тройку (рамки [x0,y0,x1,y1], вероятности,
            # куски) — не список рамок. Ошибка на этом уже съедала роль целиком.
            boxes, probs, pieces = pieces_as_boxes(self.ocr, gray, bw, topk=3)
        except Exception as exc:
            if os.environ.get('OWNOCR_ROLE_DEBUG'):
                print(f'алфавит: станок не отдал куски ({exc})')
            return []
        if not boxes:
            return []
        letters, scores, prev_end = [], [], None
        for b in sorted(boxes, key=lambda r: r[0]):
            x0, y0, x1, y1 = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
            x, y, w, h = x0, y0, max(1, x1 - x0), max(1, y1 - y0)
            if w < 2 or h < 6:
                continue
            crop = gray[max(0, y):y + h, max(0, x):x + w]
            if crop.size == 0:
                continue
            img = _to_square(crop, 32)
            x_in = torch.from_numpy((img / 255.0).astype(np.float32))[None, None]
            with torch.no_grad():
                out = torch.softmax(self.net(x_in), dim=1)[0]
            k = int(out.argmax())
            letters.append(E.LETTERS[k])
            scores.append(float(out[k]))
            # пробел — большой разрыв между буквами
            if prev_end is not None and x - prev_end > 0.55 * h:
                letters.append(' ')
            prev_end = x + w
        text = ''.join(letters).strip()
        conf = float(np.mean(scores)) * 0.6 if scores else 0.0     # своя шкала
        return [(text, conf)] if text else []


def _to_square(crop: np.ndarray, S: int) -> np.ndarray:
    import cv2
    ink = crop < 200
    if ink.sum() < 6:
        return np.full((S, S), 255, np.uint8)
    ys, xs = np.where(ink)
    c = crop[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h, w = c.shape
    k = min(S / h, S / w)
    im = cv2.resize(c, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
    canvas = np.full((S, S), 255, np.uint8)
    y0, x0 = (S - im.shape[0]) // 2, (S - im.shape[1]) // 2
    canvas[y0:y0 + im.shape[0], x0:x0 + im.shape[1]] = im
    return canvas


def _AlphabetNet(n: int):
    import torch.nn as nn
    return nn.Sequential(
        nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(), nn.MaxPool2d(2),
        nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(), nn.MaxPool2d(2),
        nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(), nn.MaxPool2d(2),
        nn.Flatten(), nn.Linear(128 * 4 * 4, 256), nn.ReLU(), nn.Dropout(0.3),
        nn.Linear(256, n),
    )


def build(names: list[str], ocr=None) -> list:
    """Собрать роли по именам. Недоступная роль просто не попадает в список."""
    roles = []
    eslav = _eslav_path()
    for name in names:
        try:
            if name == 'eslav':
                if eslav:
                    roles.append(CtcRole('eslav', eslav))
            elif name == 'eslav_stretch':
                if eslav:
                    roles.append(CtcRole('eslav_stretch', eslav, stretch=1.1, wide_only=True))
            elif name == 'eslav_otsu':
                if eslav:
                    roles.append(CtcRole('eslav_otsu', eslav, pre='otsu'))
            elif name == 'eslav_blur':
                if eslav:
                    roles.append(CtcRole('eslav_blur', eslav, pre='blur'))
            elif name == 'base':
                p = _base_path()
                if p:
                    roles.append(CtcRole('base', p))
            elif name == 'app':
                r = AppRole()
                if r.ok:
                    roles.append(r)
            elif name == 'alphabet':
                r = AlphabetRole(ocr)
                if r.net is not None:
                    roles.append(r)
        except Exception as exc:                   # роль не поднялась — не падаем
            print(f'роль «{name}» не поднялась: {exc}')
    return roles
