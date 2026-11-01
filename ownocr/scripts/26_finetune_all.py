#!/usr/bin/env python3
"""Дообучение чтеца на ВСЁМ, что размечено: манга + манхва, по страницам.

Отличие от 16_finetune_ctc.py:
  * данные — не одна страница (41 строка), а пять: dense-a (манга, 41),
    kuro-p1 (манга, другой шрифт, 31), kuro-p2 (манга, 7), tyrant-p1 (манхва, 29),
    reader-p1 (манхва, 5);
  * проверка — ЦЕЛЫМИ СТРАНИЦАМИ (`--eval-pages`), а не случайными строками:
    иначе строки одного облачка утекают в обучение и CER врёт;
  * курс из этапов: манга → манга другого шрифта → манхва, после каждого этапа
    замер по каждой странице отдельно (видно, что даёт манхва, а что ломает мангу);
  * лучшее состояние выбирается по среднему CER на отложенных страницах.

    python3 scripts/26_finetune_all.py --epochs 8 --steps 150
"""
import argparse
import json
import os
import sys
import time

import cv2
import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ownocr.eslav as E                                    # noqa: E402
from ownocr.pair import cer, clean                          # noqa: E402
from ownocr.synth import augment_real, elastic, random_text, render_line  # noqa: E402

OUT = os.path.join(ROOT, 'out')


def read_labels(path, page=None):
    rows = []
    if not os.path.exists(path):
        return rows
    for line in open(path, encoding='utf-8'):
        parts = line.rstrip('\n').split('\t')
        if len(parts) < 2:
            continue
        name, text = parts[0], parts[1]
        pg = parts[2] if len(parts) > 2 else page
        g = cv2.imread(os.path.join(os.path.dirname(path), name), cv2.IMREAD_GRAYSCALE)
        if g is not None and text.strip():
            rows.append({'page': pg, 'text': text.strip(), 'gray': g})
    return rows


def all_real():
    rows = read_labels(os.path.join(ROOT, 'data-real', 'labels.tsv'), page='dense-a')
    rows += read_labels(os.path.join(ROOT, 'data-pages', 'labels.tsv'))
    return rows


def ctc_target(text: str):
    ids = [E.CHAR_TO_IDX[c] for c in text.upper() if c in E.CHAR_TO_IDX]
    return torch.tensor(ids, dtype=torch.long)


def evaluate(net, rows):
    """CER и дословные совпадения — по каждой странице отдельно."""
    net.eval()
    per_page = {}
    for r in rows:
        x = E.prepare(r['gray'])
        with torch.no_grad():
            out = net(torch.from_numpy(x)).numpy()
        got = E.decode_logits(out.reshape(-1, out.shape[-1]))
        c = cer(clean(r['text']), clean(got))
        d = per_page.setdefault(r['page'], {'cers': [], 'exact': 0, 'n': 0, 'rows': []})
        d['cers'].append(c)
        d['exact'] += int(clean(r['text']) == clean(got))
        d['n'] += 1
        if len(d['rows']) < 4:
            d['rows'].append({'ref': r['text'], 'got': got})
    total = []
    for pg, d in per_page.items():
        d['cer'] = float(np.mean(d['cers']))
        total += d['cers']
    return float(np.mean(total)), per_page


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=8, help='эпох на этап')
    ap.add_argument('--steps', type=int, default=150, help='шагов на эпоху')
    ap.add_argument('--batch', type=int, default=16)
    ap.add_argument('--lr', type=float, default=2.5e-4)
    ap.add_argument('--seed', type=int, default=3)
    ap.add_argument('--eval-pages', default='kuro-p2,reader-p1',
                    help='страницы, которые в обучение НЕ идут')
    ap.add_argument('--tag', default='eslav-ft')
    ap.add_argument('--real-share', type=float, default=0.55)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    torch.set_num_threads(max(1, (os.cpu_count() or 4)))

    rows = all_real()
    eval_pages = [p for p in a.eval_pages.split(',') if p]
    held = [r for r in rows if r['page'] in eval_pages]
    train_pool = {p: [r for r in rows if r['page'] == p]
                  for p in sorted({r['page'] for r in rows}) if p not in eval_pages}
    print('данные:', {p: len(v) for p, v in train_pool.items()},
          '· отложено:', {p: sum(1 for r in held if r['page'] == p) for p in eval_pages}, flush=True)

    words = sorted(w for w in open(os.path.join(ROOT, 'ownocr', 'vocab-ru.txt'),
                                   encoding='utf-8').read().split() if len(w) >= 3)
    lines = [r['text'] for r in rows]

    stages = [('манга dense-a', ['dense-a']),
              ('манга + второй шрифт', ['dense-a', 'kuro-p1']),
              ('манга + манхва', ['dense-a', 'kuro-p1', 'tyrant-p1'])]

    net = E.build_torch().train()
    opt = torch.optim.Adam([p for p in net.parameters() if p.requires_grad], lr=a.lr)
    ctc = torch.nn.CTCLoss(blank=E.BLANK, zero_infinity=True)

    base_cer, base_pages = evaluate(net, held)
    print(f'ДО: CER {100 * base_cer:.1f} % на отложенных страницах · '
          + ' · '.join(f'{p} {100 * d["cer"]:.1f} %' for p, d in base_pages.items()), flush=True)

    best, best_where, history = base_cer, 'база', []
    stage_train = []
    for si, (title, pages) in enumerate(stages, 1):
        stage_train += [r for p in pages for r in train_pool.get(p, [])]
        seen = {id(r) for r in stage_train}
        train_real = [r for r in stage_train if id(r) in seen]
        print(f'\n=== этап {si}: {title} · настоящих строк {len(train_real)} ===', flush=True)
        for ep in range(1, a.epochs + 1):
            net.train()
            t0, total = time.time(), 0.0
            sched_lr = a.lr * 0.5 * (1 + np.cos(np.pi * (ep - 1) / max(1, a.epochs)))
            for gparam in opt.param_groups:
                gparam['lr'] = sched_lr
            for _ in range(a.steps):
                imgs, texts = [], []
                for _ in range(a.batch):
                    if train_real and rng.random() < a.real_share:
                        r = train_real[int(rng.integers(len(train_real)))]
                        g = augment_real(r['gray'], rng)
                        # Манхва часто белым по чёрному, и на таких кропах модель
                        # вслепую выдавала мусор (88 % CER). Учим обе полярности.
                        if rng.random() < 0.5:
                            import cv2
                            g = cv2.bitwise_not(g)
                        imgs.append(E.prepare(g))
                        texts.append(r['text'])
                    else:
                        text = random_text(rng, words, lines)
                        img = render_line(text, rng)
                        if rng.random() < 0.25:
                            import cv2
                            img = cv2.bitwise_not(img)
                        if rng.random() < 0.5:
                            img = elastic(img, rng, alpha=float(rng.uniform(0.6, 1.8)))
                        imgs.append(E.prepare(img))
                        texts.append(text)
                width = max(i.shape[-1] for i in imgs)
                batch = np.full((len(imgs), 1, 32, width), -1.0, np.float32)
                for i, im in enumerate(imgs):
                    batch[i, :, :, :im.shape[-1]] = im
                logits = net(torch.from_numpy(batch)).log_softmax(2)
                tg = [ctc_target(t) for t in texts]
                targets = torch.cat(tg)
                lens = torch.tensor([len(t) for t in tg], dtype=torch.long)
                in_lens = torch.full((len(imgs),), logits.shape[0], dtype=torch.long)
                loss = ctc(logits, targets, in_lens, lens)
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
                opt.step()
                total += float(loss)
            cer_all, per_page = evaluate(net, held)
            history.append({'stage': si, 'epoch': ep, 'loss': total / a.steps, 'cer': cer_all,
                            'pages': {p: d['cer'] for p, d in per_page.items()}})
            print(f'  эпоха {ep}: loss {total / a.steps:.3f} · '
                  + ' · '.join(f'{p} {100 * d["cer"]:.1f} %' for p, d in per_page.items())
                  + f' · среднее {100 * cer_all:.1f} % · {time.time() - t0:.0f} с', flush=True)
            if cer_all < best - 0.002:
                best, best_where = cer_all, f'этап {si}, эпоха {ep}'
                torch.save(net.state_dict(), os.path.join(OUT, a.tag + '.pt'))
                print('   сохранено (лучшее)', flush=True)

    final_cer, final_pages = evaluate(net, held)
    report = {'данные': {p: len(v) for p, v in train_pool.items()},
              'отложенные': eval_pages, 'база_cer': base_cer, 'лучший_cer': best,
              'где_лучший': best_where, 'итог_cer': final_cer,
              'страницы_итог': {p: {'cer': d['cer'], 'exact': d['exact'], 'n': d['n'],
                                    'rows': d['rows']} for p, d in final_pages.items()},
              'история': history}
    json.dump(report, open(os.path.join(OUT, a.tag + '.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'\nИТОГ: было {100 * base_cer:.1f} % → лучшее {100 * best:.1f} % ({best_where})')
    for p, d in final_pages.items():
        print(f'  {p}: CER {100 * d["cer"]:.1f} % · дословно {d["exact"]}/{d["n"]}')
        for row in d['rows']:
            print(f'     эталон {row["ref"]!r} · прочтено {row["got"]!r}')


if __name__ == '__main__':
    main()
