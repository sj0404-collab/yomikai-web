"""Эксперимент: рекурсивный XY-cut (самый большой разрыв делит панели).

Классическая раскладка манги: страница сначала режется по самой широкой пустой
полосе — неважно, вертикальной или горизонтальной. Внутри правой панели при
чтении справа налево идём сверху вниз.
"""
from __future__ import annotations


def _biggest_y_gap(group):
    order = sorted(group, key=lambda r: r.top)
    best, at = 0.0, None
    bottom = order[0].bottom
    for r in order[1:]:
        gap = r.top - bottom
        if gap > best:
            best, at = gap, (r.top + bottom) / 2
        bottom = max(bottom, r.bottom)
    return best, at


def _biggest_x_gap(group):
    order = sorted(group, key=lambda r: r.left)
    best, at = 0.0, None
    right = order[0].right
    for r in order[1:]:
        gap = r.left - right
        if gap > best:
            best, at = gap, (r.left + right) / 2
        right = max(right, r.right)
    return best, at


def split_panels(group, rtl=True, depth=0):
    if len(group) <= 1 or depth > 12:
        return [group]
    heights = sorted(r.bottom - r.top for r in group)
    lh = max(0.008, heights[len(heights) // 2])
    y_gap, y_at = _biggest_y_gap(group)
    x_gap, x_at = _biggest_x_gap(group)
    if max(y_gap, x_gap) < lh * 0.9:
        return [group]
    if y_gap >= x_gap:
        top = [r for r in group if r.top < y_at]
        bottom = [r for r in group if r.top >= y_at]
        return [p for part in (top, bottom) for p in split_panels(part, rtl, depth + 1)]
    left = [r for r in group if r.left < x_at]
    right = [r for r in group if r.left >= x_at]
    parts = (right, left) if rtl else (left, right)
    return [p for part in parts for p in split_panels(part, rtl, depth + 1)]
