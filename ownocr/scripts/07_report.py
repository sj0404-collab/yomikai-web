#!/usr/bin/env python3
"""Собрать картинку отчёта по обучению на раннере.

На вход — папка с моделью и журналами (её приносит артефакт прогона).

    python3 scripts/07_report.py --model /tmp/ownocr-run/model --out /tmp/report.png
"""
import argparse
import json
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default='model')
    ap.add_argument('--out', default='/tmp/ownocr-report.png')
    a = ap.parse_args()

    dip = json.load(open(os.path.join(a.model, 'diploma.json'), encoding='utf-8'))['diploma']
    met_path = os.path.join(a.model, '..', 'out', 'metrics-final.json')
    if not os.path.exists(met_path):
        met_path = os.path.join(a.model, 'metrics-final.json')
    met = json.load(open(met_path, encoding='utf-8')) if os.path.exists(met_path) else {}

    stages = [d for d in dip if d['key'] != 'revision']
    rev = [d for d in dip if d['key'] == 'revision']

    fig = plt.figure(figsize=(14, 8.6), facecolor='white')
    gs = fig.add_gridspec(2, 2, height_ratios=[1.2, 1], hspace=0.42, wspace=0.24)

    ax = fig.add_subplot(gs[0, :])
    x = range(len(stages))
    ax.plot(x, [100 * d['exam'] for d in stages], 'o-', color='#1f4e79', lw=2.5, ms=8,
            label='экзамен (незнакомые шрифты)')
    ax.plot(x, [100 * d['exam_hard'] for d in stages], 's--', color='#c1581c', lw=1.8, ms=6,
            label='тот же экзамен с наклоном и шумом')
    ax.plot(x, [100 * d['target'] for d in stages], ':', color='#888', lw=1.5, label='планка уровня')
    ax.set_xticks(list(x))
    ax.set_xticklabels([d['name'] for d in stages], fontsize=9.5, rotation=12)
    ax.set_ylabel('% верных глифов', fontsize=10)
    ax.set_title('Зачёты по уровням: детский сад → университет (обучение на раннере GitHub)',
                 fontsize=13, weight='bold')
    ax.grid(alpha=.3); ax.legend(fontsize=9, loc='lower right'); ax.set_ylim(55, 101)
    for i, d in enumerate(stages):
        ax.annotate(f'{100 * d["exam"]:.1f}', (i, 100 * d['exam']), textcoords='offset points',
                    xytext=(0, 10), ha='center', fontsize=9)

    ax2 = fig.add_subplot(gs[1, 0])
    if met:
        names = ['печатный\nглиф', 'наклон /\nкурсив', 'мелкий\nкегль', 'строка\nпрозы (CER)',
                 'страница\nманги (CER)']
        vals = [100 * met['sheet_clean']['acc'], 100 * met['sheet_italic']['acc'],
                100 * met['sheet_small']['acc'], 100 * met['prose']['cer'],
                100 * met['manga']['cer']]
        cols = ['#2e7d32', '#558b2f', '#9e9d24', '#c62828', '#8e0000']
        bars = ax2.bar(names, vals, color=cols)
        ax2.set_title('Итоговая проверка (зелёное — точность, красное — CER)',
                      fontsize=11, weight='bold')
        ax2.set_ylim(0, 100); ax2.grid(axis='y', alpha=.3)
        for b, v in zip(bars, vals):
            ax2.text(b.get_x() + b.get_width() / 2, v + 2, f'{v:.0f}', ha='center', fontsize=10)

    ax3 = fig.add_subplot(gs[1, 1]); ax3.axis('off')
    total = sum(d['seconds'] for d in stages)
    lines = [
        f'ученик: {met.get("params", 0):,} чисел · {met.get("model_size_kb", 0):.0f} КБ'.replace(',', ' '),
        'без ONNX, без TFLite, без torch — numpy',
        f'уровней сдано: {sum(1 for d in stages if d["passed"])} из {len(stages)}',
        f'время на обучение: {total / 60:.1f} мин',
    ]
    if rev:
        r = rev[-1]
        lines.append(f'повторение до звонка: кругов {r.get("kept", 0) + r.get("dropped", 0)}, '
                     f'зафиксировано {r.get("kept", 0)}')
        lines.append(f'после повторения: {100 * r["exam"]:.1f} % / с наклоном {100 * r["exam_hard"]:.1f} %')
    ax3.text(0.0, 1.0, '\n'.join(lines), fontsize=11, va='top',
             bbox=dict(boxstyle='round,pad=0.6', fc='#f2f6fa', ec='#c9d6e3'))
    ax3.set_title('Паспорт прогона', fontsize=11, weight='bold')

    fig.suptitle('Свой OCR: лестница зачётов, фиксация верного, продолжение с последней ступени',
                 fontsize=14.5, weight='bold', y=0.985)
    fig.savefig(a.out, dpi=130, bbox_inches='tight', facecolor='white')
    print('картинка:', a.out)


if __name__ == '__main__':
    main()
