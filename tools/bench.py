"""ТРЕНИРОВОЧНАЯ ПЛОЩАДКА: один прогон «данные → обучение → ONNX → проверка».

  python3 tools/bench.py                      # короткий прогон, минуты на CPU
  python3 tools/bench.py --steps 2000 --epochs 12
  python3 tools/bench.py --crops data/lines --labels data/labels.tsv --epochs 30

Печатает таблицу по эпохам (CER на отложенных строках) и итог: файл .onnx,
который приложение принимает через ⚙ → Модели. Ничего не отправляет в сеть.
Отчёт кладётся в runs/bench_report.json и runs/bench_report.md.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Тренировочная площадка распознавателя")
    ap.add_argument("--steps", type=int, default=600, help="строк за эпоху")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-3)
    ap.add_argument("--crops", default=None)
    ap.add_argument("--labels", default=None)
    ap.add_argument("--out", default=os.path.join(REPO, "runs", "rec_bench.pt"))
    ap.add_argument("--onnx", default=os.path.join(REPO, "models", "rec_bench.onnx"))
    a = ap.parse_args(argv)

    t0 = time.time()
    py = sys.executable
    print("── 1/3 обучение ───────────────────────────────────────────────")
    cmd = [py, os.path.join(HERE, "train_rec.py"), "--steps", str(a.steps),
           "--epochs", str(a.epochs), "--batch", str(a.batch), "--lr", str(a.lr),
           "--out", a.out]
    if a.crops:
        cmd += ["--crops", a.crops, "--labels", a.labels]
    rc = subprocess.call(cmd)
    if rc != 0:
        raise SystemExit(f"обучение упало, код {rc}")

    print("── 2/3 экспорт в ONNX ─────────────────────────────────────────")
    rc = subprocess.call([py, os.path.join(HERE, "export_onnx.py"),
                          "--ckpt", a.out, "--out", a.onnx])
    if rc != 0:
        raise SystemExit(f"экспорт/проверка упали, код {rc}")

    print("── 3/3 отчёт ──────────────────────────────────────────────────")
    hist = []
    jpath = os.path.splitext(a.out)[0] + ".json"
    if os.path.exists(jpath):
        hist = json.load(open(jpath, encoding="utf-8"))
    rows = hist.get("history", [])
    if rows:
        print("| эпоха | проверка CER | время, с |")
        print("|---|---|---|")
        for r in rows:
            print(f"| {r['epoch']} | {r['val_cer']*100:.1f} % | {r['sec']} |")
    report = {"ckpt": os.path.relpath(a.out, REPO), "onnx": os.path.relpath(a.onnx, REPO),
              "params": hist.get("params"), "val_cer": hist.get("val_cer"),
              "history": rows, "minutes": round((time.time() - t0) / 60, 1)}
    os.makedirs(os.path.join(REPO, "runs"), exist_ok=True)
    with open(os.path.join(REPO, "runs", "bench_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    with open(os.path.join(REPO, "runs", "bench_report.md"), "w", encoding="utf-8") as f:
        f.write("# Тренировочная площадка — последний прогон\n\n")
        f.write(f"- набор: {'свои кропы ' + str(a.crops) if a.crops else 'синтетика из словаря'}\n")
        f.write(f"- параметров: {hist.get('params')}\n")
        f.write(f"- итог: CER {hist.get('val_cer', 0)*100:.1f} % за {report['minutes']} мин\n")
        f.write(f"- файл для ⚙ → Модели: `{report['onnx']}`\n\n")
        f.write("| эпоха | проверка CER | время, с |\n|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['epoch']} | {r['val_cer']*100:.1f} % | {r['sec']} |\n")
    print(f"готово за {report['minutes']} мин · {report['onnx']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
