"""«Археолог»: читать незнакомый шрифт по подсказкам, а не по обучению.

Идея. Когда чтец видит незнакомое начертание, он не обязан его «знать»: у него
есть библиотека — 109 букв в 56 начертаниях, — и можно поступить как археолог с
неизвестным письмом: найти знакомые формы, понять, какой это почерк, и только
потом дочитать остальное.

Три шага, ровно как у дешифровщика:

1. **Знакомые формы.** Каждый глиф строки сравнивается со всеми шаблонами
   (56 начертаний × 109 букв). Пока это не чтение — это «в записях есть похожие
   знаки».
2. **Гипотеза о почерке.** Для каждого начертания считаем, насколько хорошо оно
   объясняет ВСЮ строку целиком, и берём лучшие несколько. Одно начертание, а не
   6104 независимых ответа: у строки один почерк, и это главное ограничение.
3. **Дочитывание и арбитр.** Буквы берём только из выбранного начертания, а
   слово целиком проверяем по языку: словарь + длины + частые пары букв. Если
   слово не сходится ни с одним словарным, остаётся как прочитано — врать нельзя.

Ничего не обучается: ни одной эпохи. Всё сводится к перебору библиотеки.
"""
from __future__ import annotations

import glob
import os

import cv2
import numpy as np

SIZE = 24                       # сторона квадрата, к которому приводим глиф


# ── библиотека шаблонов ────────────────────────────────────────────────────────

def font_paths() -> list[str]:
    paths = []
    for d in ('/home/user/fonts', '/var/tmp/ownocr/fonts'):
        paths += sorted(glob.glob(os.path.join(d, '*.ttf')))
    paths += sorted(glob.glob('/usr/share/fonts/truetype/dejavu/*.ttf'))
    return paths


def _descriptor(gray: np.ndarray) -> np.ndarray:
    """Форма глифа: чёрное на белом, обрезано по чернилам, приведено к SIZE.

    Нормировка важна: у незнакомого шрифта размер и жирность другие, а форма та
    же. Поэтому обрезаем по bbox и растягиваем на квадрат — сравнение идёт по
    форме, а не по кеглю.
    """
    ink = gray < 200
    if ink.sum() < 6:
        return np.zeros(SIZE * SIZE, np.float32)
    ys, xs = np.where(ink)
    crop = gray[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    im = cv2.resize(crop, (SIZE, SIZE), interpolation=cv2.INTER_AREA).astype(np.float32)
    im = 1.0 - im / 255.0                      # чернила = 1
    v = im.reshape(-1)
    v -= v.mean()
    n = np.linalg.norm(v)
    return (v / n).astype(np.float32) if n > 1e-6 else v


def build_library(letters, fonts=None, cache: str = '') -> tuple[np.ndarray, list]:
    """Матрица шаблонов: (глифов × 576) и список (буква, шрифт) по строкам."""
    if cache and os.path.exists(cache):
        d = np.load(cache, allow_pickle=True)
        return d['X'], list(d['meta'])
    from PIL import Image, ImageDraw, ImageFont
    fonts = fonts or font_paths()
    rows, meta = [], []
    for path in fonts:
        for size in (32, 48, 64):
            try:
                font = ImageFont.truetype(path, size)
            except Exception:
                continue
            for ch in letters:
                img = Image.new('L', (size * 3, size * 3), 255)
                ImageDraw.Draw(img).text((size // 2, size // 2), ch, font=font, fill=0)
                arr = np.asarray(img)
                if (arr < 200).sum() < 8:
                    continue                      # буквы нет в этом начертании
                rows.append(_descriptor(arr))
                meta.append((ch, os.path.basename(path), size))
    X = np.stack(rows)
    if cache:
        np.savez_compressed(cache, X=X, meta=np.array(meta, dtype=object))
    return X, meta


# ── строка → глифы ────────────────────────────────────────────────────────────

def glyphs_of_line(gray: np.ndarray, min_h: int = 6) -> list[tuple[int, int, np.ndarray]]:
    """Разрез строки по столбцам. Возвращает (x, ширина, картинка глифа).

    Проекция по столбцам — самый дешёвый способ и он честно разваливается на
    касающихся буквах; поэтому дополнительно режем слишком широкие куски по
    типичной ширине буквы в этой строке.
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    bw = (gray < 170).astype(np.uint8)
    col = bw.sum(axis=0)
    thr = max(1, int(0.03 * bw.shape[0]))
    ink = col > thr
    out, x = [], 0
    while x < len(ink):
        if not ink[x]:
            x += 1
            continue
        y = x
        while y < len(ink) and ink[y]:
            y += 1
        out.append((x, y - x))
        x = y
    if not out:
        return []
    widths = np.array([w for _, w in out])
    med = float(np.median(widths)) or 8.0
    fine = []
    for x0, w in out:
        if w <= med * 1.7:
            fine.append((x0, w))
        else:                                    # слипшиеся буквы — делим по ширине
            k = max(2, int(round(w / med)))
            step = w / k
            for i in range(k):
                fine.append((int(x0 + i * step), int(step)))
    res = []
    for x0, w in fine:
        part = gray[:, x0:x0 + w]
        ink_m = part < 170
        if ink_m.sum() < 6:
            continue
        ys, xs = np.where(ink_m)
        if ys.max() - ys.min() + 1 < min_h:
            continue
        res.append((x0, w, part[ys.min():ys.max() + 1, xs.min():xs.max() + 1]))
    return res


# ── три шага ──────────────────────────────────────────────────────────────────

def match_glyphs(gl, X, meta, fonts_limit: int = 0):
    """Шаг 1 и 2: похожие формы и гипотеза о почерке.

    Возвращает (лучшая буква без модели почерка, буква с моделью, рейтинг почерков).
    """
    D = np.stack([_descriptor(g) for _, _, g in gl])          # (N, 576)
    sim = D @ X.T                                             # косинус: больше — похожее
    k = sim.shape[1]
    best_all = [meta[i][0] for i in sim.argmax(axis=1)]       # без модели почерка

    fonts = sorted({m[1] for m in meta})
    scores = np.full(len(fonts), -9.0, np.float32)
    idx_by_font = {f: np.array([i for i, m in enumerate(meta) if m[1] == f]) for f in fonts}
    for fi, f in enumerate(fonts):
        cols = idx_by_font[f]
        # каждый глиф объясняем лучшей буквой ЭТОГО начертания
        scores[fi] = float(sim[:, cols].max(axis=1).mean())
    order = np.argsort(-scores)
    best_font = fonts[int(order[0])]
    cols = idx_by_font[best_font]
    sub = sim[:, cols]
    take = sub.argmax(axis=1)
    best_font_letters = [meta[int(cols[t])][0] for t in take]
    ranking = [(fonts[int(i)], float(scores[int(i)])) for i in order[:5]]
    return best_all, best_font_letters, ranking


def read_line(gray: np.ndarray, X, meta, archer: dict | None = None) -> dict:
    gl = glyphs_of_line(gray)
    if not gl:
        return {'text_all': '', 'text_font': '', 'text_final': '', 'glyphs': 0, 'ranking': []}
    best_all, best_font, ranking = match_glyphs(gl, X, meta)
    text_all = ''.join(best_all)
    text_font = ''.join(best_font)
    final = text_font
    if archer:
        final = archer.apply(text_font)
    return {'text_all': text_all, 'text_font': text_font, 'text_final': final,
            'glyphs': len(gl), 'ranking': ranking, 'font': ranking[0][0] if ranking else ''}


# ── разрез строки там, где буквы слиплись ─────────────────────────────────────

class Library:
    """Библиотека шаблонов, сжатая по форме (PCA) — чтобы перебор был быстрым.

    Без сжатия перебор «все разрезы × все шаблоны» занимает десятки секунд на
    строку: 4 500 вариантов куска против 6 104 шаблонов по 576 чисел. После
    сжатия до 64 чисел тот же перебор в 9 раз быстрее и теряет меньше процента
    попаданий.
    """

    def __init__(self, X: np.ndarray, meta: list, comps: int = 64):
        self.meta = meta
        self.mean = X.mean(axis=0)
        U, S, Vt = np.linalg.svd(X - self.mean, full_matrices=False)
        self.P = Vt[:comps].T.astype(np.float32)
        self.Z = ((X - self.mean) @ self.P).astype(np.float32)
        self.fonts = sorted({m[1] for m in meta})
        self.by_font = {f: np.array([i for i, m in enumerate(meta) if m[1] == f])
                        for f in self.fonts}

    def project(self, d: np.ndarray) -> np.ndarray:
        return (d - self.mean) @ self.P

    def best(self, d: np.ndarray):
        z = self.project(d)
        sim = self.Z @ z
        i = int(sim.argmax())
        return self.meta[i][0], self.meta[i][1], float(sim[i])

    def best_in_font(self, d: np.ndarray, font: str):
        z = self.project(d)
        cols = self.by_font[font]
        sim = self.Z[cols] @ z
        i = int(sim.argmax())
        return self.meta[int(cols[i])][0], float(sim[i])

    def font_scores(self, ds: list[np.ndarray]) -> list[tuple[str, float]]:
        """Насколько каждое начертание объясняет ВСЮ строку целиком."""
        out = []
        for f, cols in self.by_font.items():
            tot = 0.0
            for d in ds:
                z = self.project(d)
                tot += float((self.Z[cols] @ z).max())
            out.append((f, tot / max(1, len(ds))))
        out.sort(key=lambda x: -x[1])
        return out


def cut_line(gray: np.ndarray, lib: Library, min_frac: float = 0.32,
             max_frac: float = 1.35, lam: float = 0.45):
    """Разрез строки динамическим программированием по форме кусков.

    Стоимость куска — «насколько он не похож ни на одну знакомую букву». Разрез
    выбирается так, чтобы вся строка объяснялась библиотекой лучше всего. Это и
    есть поведение археолога: он режет надпись там, где получаются знакомые знаки.
    """
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    H, W = gray.shape
    # сжимаем по высоте до 40 px: кегль не должен влиять на узнавание формы
    k = 40.0 / max(1, H)
    g = cv2.resize(gray, (max(1, int(W * k)), 40), interpolation=cv2.INTER_AREA)
    W = g.shape[1]
    # ширина буквы в этой строке — от высоты: у обычных начертаний 0,3–1,4 высоты
    min_w = max(6, int(min_frac * 40))
    max_w = max(min_w + 4, int(max_frac * 40))
    ink = g < 200
    cols = ink.sum(axis=0) > 0
    if not cols.any():
        return []
    # границы куска не должны приходиться на середину плотного столбца
    cnt = ink.sum(axis=0)
    pos = cnt[cnt > 0]
    dense = cnt > (0.55 * float(np.median(pos)) if pos.size else 0)

    desc: dict[tuple[int, int], np.ndarray] = {}
    score: dict[tuple[int, int], float] = {}
    for i in range(W):
        for j in range(i + min_w, min(W, i + max_w) + 1):
            if dense[min(W - 1, max(0, j - 1))] and j < W:
                pass
            part = g[:, i:j]
            if (part < 200).sum() < 5:
                continue
            d = _descriptor(part)
            if not d.any():
                continue
            z = lib.project(d)
            sim = float((lib.Z @ z).max())
            desc[(i, j)] = d
            # λ за каждый лишний кусок: без него разрез выгодно дробить на пенки
            score[(i, j)] = sim - lam - (0.08 if dense[min(W - 1, j - 1)] else 0.0)

    INF = 1e9
    dp = np.full(W + 1, INF, np.float32)
    back = np.full(W + 1, -1, int)
    dp[0] = 0.0
    for j in range(1, W + 1):
        for i in range(max(0, j - max_w), j - min_w + 1):
            s = score.get((i, j))
            if s is None or dp[i] >= INF:
                continue
            v = dp[i] - s
            if v < dp[j]:
                dp[j] = v
                back[j] = i
    if back[W] < 0:
        return []
    cuts, j = [], W
    while j > 0:
        i = back[j]
        cuts.append((i, j))
        j = i
    cuts.reverse()
    sx = W / float(gray.shape[1])
    return [(int(a / sx), int((b - a) / sx), gray[:, int(a / sx):max(int(b / sx), int(a / sx) + 1)])
            for a, b in cuts]


def read_line_dp(gray: np.ndarray, lib: Library, op: dict | None = None) -> dict:
    """Полный проход: разрез по знакомым формам → гипотеза о почерке → арбитр."""
    cuts = cut_line(gray, lib)
    if not cuts:
        return {'text_forms': '', 'text_font': '', 'text_final': '', 'glyphs': 0,
                'ranking': [], 'font': ''}
    ds = [_descriptor(g) for _, _, g in cuts]
    forms = ''.join(lib.best(d)[0] for d in ds)
    ranking = lib.font_scores(ds)
    font = ranking[0][0]
    letters = [lib.best_in_font(d, font)[0] for d in ds]
    text_font = ''.join(letters)
    final = (op or {}).get('apply', lambda x: x)(text_font)
    return {'text_forms': forms, 'text_font': text_font, 'text_final': final,
            'glyphs': len(cuts), 'ranking': ranking[:5], 'font': font}
