"""Замер CER на СВОЕЙ разметке — тем же кодом, что в приложении, и своей моделью.

  python3 tools/eval_dataset.py --labels data/lines/labels.tsv --split val
  python3 tools/eval_dataset.py --labels data/lines/labels.tsv --split val \\
      --onnx models/rec_manga.onnx        # своя обученная модель, путь ONNX

Два режима:
  · без --onnx — считает штатный koma_rec ВНУТРИ приложения (Chromium,
    onnxruntime-web): жадно и своим словарным декодером. Это «что умеет сейчас»;
  · с --onnx  — тот же контракт, но файл подменён, и считает onnxruntime в питоне.
"""
from __future__ import annotations

import argparse
import base64
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from charset import cer, classes_to_text, load_charset   # noqa: E402


def read_labels(labels: str, split: str):
    rows = []
    with open(labels, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            if split and len(parts) >= 4 and parts[3] != split:
                continue
            rows.append((parts[0], parts[1]))
    return rows


def b64(path):
    return base64.b64encode(open(path, "rb").read()).decode()


def eval_onnx(rows, root, onnx_path):
    import numpy as np
    import onnxruntime as ort
    from PIL import Image
    cs = load_charset()
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    name = sess.get_inputs()[0].name
    out = []
    for f, ref in rows:
        im = Image.open(os.path.join(root, f)).convert("L")
        w = max(8, min(960, round(im.width * 48 / im.height)))
        im = im.resize((w, 48), Image.BICUBIC)
        a = np.asarray(im, dtype=np.float32)
        padded = (max(320, w) + 7) // 8 * 8
        canvas = np.full((48, padded), 128.0, dtype=np.float32)
        canvas[:, :w] = a
        x = np.repeat(canvas[None], 3, axis=0)
        x = ((x / 255.0 - 0.5) / 0.5).astype(np.float32)[None]
        probs = sess.run(None, {name: x})[0][0]
        out.append((ref, classes_to_text(cs, probs.argmax(-1))))
    return out


def report(pairs, title):
    if not pairs:
        print("нечего мерить")
        return 1
    total = sum(cer(r, h) * max(1, len(r)) for r, h in pairs)
    n = sum(max(1, len(r)) for r, _ in pairs)
    exact = sum(1 for r, h in pairs if r == h)
    print(f"{title}: строк {len(pairs)} · CER {total/n*100:.1f} % · целиком верных {exact}/{len(pairs)}")
    for r, h in pairs[:6]:
        mark = "  " if r == h else "≠ "
        print(f"  {mark}{r}\n     {h}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=os.path.join(REPO, "data", "lines", "labels.tsv"))
    ap.add_argument("--root", default=os.path.join(REPO, "data", "lines"))
    ap.add_argument("--split", default="val", choices=["train", "val", ""])
    ap.add_argument("--onnx", default=None)
    a = ap.parse_args(argv)
    rows = read_labels(a.labels, a.split)
    if not a.onnx:
        print("укажи --onnx (своя модель); штатную koma_rec меряет lab/eval_in_app.py")
        return 2
    pairs = eval_onnx(rows, a.root, a.onnx)
    return report(pairs, f"{os.path.basename(a.onnx)} · {a.split or 'всё'}")


if __name__ == "__main__":
    sys.exit(main())
