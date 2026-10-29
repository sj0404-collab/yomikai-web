#!/usr/bin/env python3
"""YOLOv8 как ВТОРОЙ, независимый источник рамок строк — для сверки.

Задача 77, пункт (б): «попробуй yolo v8 для сверки». Смысл не в том, чтобы
заменить наш детектор, а в том, чтобы получить рамки из другой модели и
посмотреть, где наш детектор и YOLO расходятся: расхождение = место, которое
надо проверить глазами.

Данных мало (одна размеченная страница), поэтому:
  • обучение — на плотной странице `dense-a.jpg` с ручными рамками
    (`data/lines-real/boxes.json`, 41 строка), с аугментацией окнами;
  • проверка — на ДРУГОЙ странице (`dense-b.jpg`), рамки которой взяты из
    нашего детектора в приложении (`--ours-b`). Метрики — согласие двух
    источников: сколько наших строк YOLO подтверждает и сколько рамок YOLO
    наш детектор не нашёл.

  python3 lab/yolo_check.py --train --epochs 40        # обучить и сверить
  python3 lab/yolo_check.py --predict-only             # только сверка
"""
import argparse
import json
import os
import random
import shutil

import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAB = '/home/user/koma-lab'
OUT = os.path.join(ROOT, 'runs', 'yolo')


def make_dataset(train_page, boxes_json, out_dir, windows=160, imgsz=320, seed=7):
    """Нарезать из страницы окна с 1–3 строками — по ним и учим YOLO."""
    rnd = random.Random(seed)
    img = cv2.imread(train_page)
    H, W = img.shape[:2]
    boxes = [(d['x0'], d['y0'], d['x1'], d['y1']) for d in json.load(open(boxes_json, encoding='utf-8'))]
    for sub in ('images/train', 'labels/train', 'images/val', 'labels/val'):
        os.makedirs(os.path.join(out_dir, sub), exist_ok=True)
    n = 0
    for i in range(windows):
        # окно-фрагмент: 1–3 соседние строки с полями
        b = boxes[rnd.randrange(len(boxes))]
        group = [b]
        if rnd.random() < 0.55:
            for other in boxes:
                if other is b:
                    continue
                if abs(other[1] - b[1]) < 4.5 * (b[3] - b[1]) and rnd.random() < 0.5:
                    group.append(other)
        x0 = max(0, min(g[0] for g in group) - rnd.randint(4, 30))
        y0 = max(0, min(g[1] for g in group) - rnd.randint(3, 25))
        x1 = min(W, max(g[2] for g in group) + rnd.randint(4, 30))
        y1 = min(H, max(g[3] for g in group) + rnd.randint(3, 25))
        if x1 - x0 < 24 or y1 - y0 < 16:
            continue
        crop = img[y0:y1, x0:x1]
        lines = []
        for g in group:
            cx = (g[0] + g[2]) / 2 - x0
            cy = (g[1] + g[3]) / 2 - y0
            bw, bh = g[2] - g[0], g[3] - g[1]
            if not (0 < cx < crop.shape[1] and 0 < cy < crop.shape[0]):
                continue
            lines.append(f'0 {cx / crop.shape[1]:.6f} {cy / crop.shape[0]:.6f} '
                         f'{bw / crop.shape[1]:.6f} {bh / crop.shape[0]:.6f}')
        if not lines:
            continue
        part = 'val' if i % 7 == 0 else 'train'
        name = f'w{i:03d}'
        cv2.imwrite(os.path.join(out_dir, 'images', part, name + '.jpg'), crop)
        open(os.path.join(out_dir, 'labels', part, name + '.txt'), 'w').write('\n'.join(lines) + '\n')
        n += 1
    yaml_path = os.path.join(out_dir, 'data.yaml')
    open(yaml_path, 'w').write(
        f"path: {out_dir}\ntrain: images/train\nval: images/val\nnames:\n  0: line\n")
    return yaml_path, n


def iou(a, b):
    x0 = max(a[0], b[0]); y0 = max(a[1], b[1])
    x1 = min(a[2], b[2]); y1 = min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0


def predict(model, page, conf=0.25):
    res = model.predict(page, conf=conf, imgsz=320, verbose=False)[0]
    out = []
    for box in res.boxes.xyxy.tolist():
        out.append(tuple(round(v) for v in box))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--train', action='store_true')
    ap.add_argument('--predict-only', action='store_true')
    ap.add_argument('--epochs', type=int, default=40)
    ap.add_argument('--train-page', default=os.path.join(LAB, 'dense-a.jpg'))
    ap.add_argument('--train-boxes', default=os.path.join(ROOT, 'data', 'lines-real', 'boxes.json'))
    ap.add_argument('--check-page', default=os.path.join(LAB, 'dense-b.jpg'))
    ap.add_argument('--ours-b', default='/tmp/dense-b-lines.json')
    ap.add_argument('--weights', default=os.path.join(OUT, 'train', 'weights', 'best.pt'))
    args = ap.parse_args()

    from ultralytics import YOLO

    if args.train and not args.predict_only:
        ds = os.path.join(OUT, 'ds')
        shutil.rmtree(ds, ignore_errors=True)
        yaml_path, n = make_dataset(args.train_page, args.train_boxes, ds)
        print(f'окон для обучения: {n} (data.yaml: {yaml_path})')
        model = YOLO('/var/tmp/yolov8n.pt' if os.path.exists('/var/tmp/yolov8n.pt') else 'yolov8n.pt')
        model.train(data=yaml_path, epochs=args.epochs, imgsz=320, batch=8, workers=1,
                    device='cpu', project=OUT, name='train', exist_ok=True,
                    plots=False, val=True, seed=7, patience=20)

    model = YOLO(args.weights)
    ours = json.load(open(args.ours_b, encoding='utf-8'))
    img = cv2.imread(args.check_page)
    H, W = img.shape[:2]
    our_boxes = [(round(r['l'] * W), round(r['t2'] * H), round(r['r'] * W), round(r['b'] * H)) for r in ours]
    yolo_boxes = predict(model, args.check_page)

    hit = sum(1 for b in our_boxes if any(iou(b, y) >= 0.3 for y in yolo_boxes))
    lone = [y for y in yolo_boxes if not any(iou(b, y) >= 0.3 for b in our_boxes)]
    print(f'страница сверки: {os.path.basename(args.check_page)} ({W}×{H})')
    print(f'наших строк {len(our_boxes)}, рамок YOLO {len(yolo_boxes)}')
    print(f'YOLO подтверждает наших строк: {hit}/{len(our_boxes)} = {100 * hit / max(1, len(our_boxes)):.0f} %')
    print(f'рамок YOLO без пары у нас: {len(lone)}')
    for y in lone[:8]:
        print(f'   лишняя у YOLO: {y}')


if __name__ == '__main__':
    main()
