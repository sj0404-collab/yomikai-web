#!/usr/bin/env python3
"""Дообучение CTC-модели «эслав» на нашем домене: мелкий смазанный шрифт манги.

Учим на смеси: синтетические строки (шрифт 10–26 px, размытие, шум, растр,
перекос) + настоящие строки с размеченных страниц. Проверка — на строках,
которые в обучение НЕ попадают, и на репликах страниц.

    python3 scripts/16_finetune_ctc.py --epochs 12 --steps 200
"""
import argparse, json, os, sys, time
import numpy as np, cv2, torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ownocr.eslav as E
from ownocr.synth import render_line, random_text, augment_real, elastic
from ownocr.pair import cer, clean

LAB = '/home/user/koma-lab'
OUT = os.path.join(ROOT, 'out')


def real_lines():
    rows = []
    for line in open(os.path.join(ROOT, 'data-real', 'labels.tsv'), encoding='utf-8'):
        name, text = line.rstrip('\n').split('\t')
        path = os.path.join(ROOT, 'data-real', name)
        g = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if g is not None:
            rows.append((g, text))
    return rows


def ctc_target(text: str):
    """Индексы букв в алфавите модели: 0..108. «Пусто» — это 109, не 0."""
    ids = [E.LETTERS.index(c) for c in text.upper() if c in E.CHAR_TO_IDX]
    return torch.tensor(ids, dtype=torch.long)


def evaluate(net, rows):
    net.eval()
    cers, exact = [], 0
    for g, ref in rows:
        x = E.prepare(g)
        with torch.no_grad():
            out = net(torch.from_numpy(x)).numpy()
        t = E.decode_logits(out.reshape(-1, out.shape[-1]))
        c = cer(clean(ref), clean(t))
        cers.append(c)
        exact += int(clean(ref) == clean(t))
    return float(np.mean(cers)), exact


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=12)
    ap.add_argument('--steps', type=int, default=200, help='шагов на эпоху')
    ap.add_argument('--batch', type=int, default=16)
    ap.add_argument('--lr', type=float, default=3e-4)
    ap.add_argument('--holdout', type=int, default=7, help='сколько настоящих строк держим на проверку')
    ap.add_argument('--freeze-conv', action='store_true')
    ap.add_argument('--out', default=os.path.join(OUT, 'eslav-ft.onnx'))
    ap.add_argument('--tag', default='eslav-ft', help='имя артефактов в out/ (для пробных прогонов)')
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()

    torch.manual_seed(a.seed)
    rng = np.random.default_rng(a.seed)
    rows = real_lines()
    hold = rows[:a.holdout]                      # 1–7 — отложены, в обучение не идут
    train_real = rows[a.holdout:]
    words = sorted(w for w in open(os.path.join(ROOT, 'ownocr', 'vocab-ru.txt'),
                                   encoding='utf-8').read().split() if len(w) >= 3)
    lines = [t for _, t in rows]

    net = E.build_torch().train()
    if a.freeze_conv:
        for p in net.features.parameters():
            p.requires_grad_(False)
    params = [p for p in net.parameters() if p.requires_grad]
    opt = torch.optim.Adam(params, lr=a.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, a.epochs))
    # «Пусто» у этой модели — класс 109 (на этом я уже обжёгся при замере).
    ctc = torch.nn.CTCLoss(blank=E.BLANK, zero_infinity=True)

    base_cer, base_exact = evaluate(net, hold)
    print(f'ДО дообучения: на отложенных строках CER {100 * base_cer:.1f} % · '
          f'дословно {base_exact}/{len(hold)}', flush=True)

    best = base_cer
    history = []
    for ep in range(1, a.epochs + 1):
        net.train()
        t0, total = time.time(), 0.0
        for step in range(a.steps):
            imgs, texts = [], []
            for _ in range(a.batch):
                if train_real and rng.random() < 0.55:
                    g, text = train_real[int(rng.integers(len(train_real)))]
                    # настоящих строк мало (34), поэтому каждую показываем в
                    # новых искажениях: иначе модель запоминает их наизусть
                    g = augment_real(g, rng)
                    imgs.append(E.prepare(g))
                    texts.append(text)
                else:
                    text = random_text(rng, words, lines)
                    img = render_line(text, rng)
                    if rng.random() < 0.5:
                        img = elastic(img, rng, alpha=float(rng.uniform(0.6, 1.8)))
                    imgs.append(E.prepare(img))
                    texts.append(text)
            width = max(i.shape[-1] for i in imgs)
            batch = np.full((len(imgs), 1, 32, width), -1.0, np.float32)
            for i, im in enumerate(imgs):
                batch[i, :, :, :im.shape[-1]] = im
            x = torch.from_numpy(batch)
            logits = net(x)                       # (T, B, C)
            logp = logits.log_softmax(2)
            T = logp.shape[0]
            targets = torch.cat([ctc_target(t) for t in texts])
            lens = torch.tensor([len(ctc_target(t)) for t in texts], dtype=torch.long)
            in_lens = torch.full((len(imgs),), T, dtype=torch.long)
            loss = ctc(logp, targets, in_lens, lens)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
            opt.step()
            total += float(loss)
        hold_cer, hold_exact = evaluate(net, hold)
        sched.step()
        history.append({'epoch': ep, 'loss': total / a.steps,
                        'hold_cer': hold_cer, 'hold_exact': hold_exact})
        print(f'эпоха {ep:2d}: loss {total / a.steps:.3f} · '
              f'отложенные CER {100 * hold_cer:.1f} % · дословно {hold_exact}/{len(hold)} · '
              f'{time.time() - t0:.0f} с', flush=True)
        if hold_cer < best - 0.005:
            best = hold_cer
            torch.save(net.state_dict(), os.path.join(OUT, a.tag + '.pt'))
            print('   сохранено (лучшее на отложенных)', flush=True)

    json.dump({'base_cer': base_cer, 'best_cer': best, 'history': history},
              open(os.path.join(OUT, a.tag + '.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'ИТОГ: было {100 * base_cer:.1f} % → стало {100 * best:.1f} % на отложенных')
    print('веса:', os.path.join(OUT, a.tag + '.pt'))


if __name__ == '__main__':
    main()
