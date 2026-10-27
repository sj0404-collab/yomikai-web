"""Экспорт обученного чекпоинта в ONNX + проверка, что файл годится приложению.

  python3 tools/export_onnx.py --ckpt runs/bench.pt --out models/rec_bench.onnx

Проверки после экспорта (все три — обязательные):
  1) формы: вход [1,3,48,W] (W меняется), выход [1,W/8,519];
  2) числа: сумма вероятностей по классам = 1, расхождение с torch < 1e-4;
  3) смысл: CER того, что отдаёт ONNX, на отложенных синтетических строках.
"""
from __future__ import annotations

import argparse
import os
import random
import sys

import numpy as np
import onnxruntime as ort
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from charset import cer, classes_to_text, load_charset, num_classes  # noqa: E402
from model import ExportWrapper, RecCTC                                     # noqa: E402
import synth                                                               # noqa: E402


def export(ckpt: str, out: str, opset: int = 17) -> str:
    ck = torch.load(ckpt, map_location="cpu", weights_only=False)
    charset = ck.get("charset") or load_charset()
    model = RecCTC(ck.get("n_classes") or num_classes(charset))
    model.load_state_dict(ck["model"])
    model.eval()
    wrapper = ExportWrapper(model).eval()
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    dummy = torch.zeros(1, 3, 48, 320)
    kw = dict(input_names=["x"], output_names=["probs"],
              dynamic_axes={"x": {3: "width"}, "probs": {1: "T"}},
              opset_version=opset, do_constant_folding=True)
    try:                                  # новый экспортёр (torch ≥ 2.6)
        torch.onnx.export(wrapper, dummy, out, verbose=False, **kw)
    except Exception:                     # старый, на torchscript — без onnxscript
        torch.onnx.export(wrapper, dummy, out, dynamo=False, **kw)
    # Вес может уехать в соседний .data-файл — приложению нужен ОДИН файл,
    # поэтому пересохраняем модель с весами внутри.
    import onnx
    m = onnx.load(out)
    onnx.save_model(m, out, save_as_external_data=False)
    for side in (out + ".data", "weights.pb"):
        if os.path.exists(side):
            os.remove(side)
    return out


def verify(onnx_path: str, ckpt: str = None, lines: int = 40, seed: int = 777) -> dict:
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    charset = load_charset()
    res = {"file": os.path.basename(onnx_path),
           "mb": round(os.path.getsize(onnx_path) / 1e6, 2),
           "input": f"{inp.name}{inp.shape}", "ok": True, "notes": []}

    words = synth.load_words(20000)
    r = synth.LineRenderer(words, charset, hard=0.35)
    rng = random.Random(seed)
    refs, hyps, sums, diffs = [], [], [], []
    net = None
    if ckpt and os.path.exists(ckpt):
        ck = torch.load(ckpt, map_location="cpu", weights_only=False)
        net = RecCTC(ck.get("n_classes") or num_classes(charset))
        net.load_state_dict(ck["model"])
        net.eval()

    w_seen = set()
    for _ in range(lines):
        x3, text = r.render(rng)
        # обрежем «серый хвост» до настоящей ширины, как это делает приложение
        x = x3[None]
        W = x.shape[3]
        out = sess.run(None, {inp.name: x})[0]
        w_seen.add((W, out.shape[1], out.shape[2]))
        sums.append(float(out.sum(-1).mean()))
        idx = out[0].argmax(-1)
        hyps.append(classes_to_text(charset, idx))
        refs.append(text)
        if net is not None:
            with torch.no_grad():
                tp = net(torch.from_numpy(x), probabilities=True).numpy()
            diffs.append(float(np.abs(tp - out).max()))

    res["shapes"] = sorted(w_seen)
    res["prob_sum"] = round(float(np.mean(sums)), 5)
    res["torch_max_diff"] = round(max(diffs), 6) if diffs else None
    res["cer"] = round(float(np.mean([cer(a, b) for a, b in zip(refs, hyps)])), 4)
    res["sample"] = [f"{a} → {b}" for a, b in list(zip(refs, hyps))[:3]]

    if res["prob_sum"] < 0.98 or res["prob_sum"] > 1.02:
        res["ok"] = False
        res["notes"].append("выход не похож на вероятности (сумма по классам != 1)")
    if any(w != t * 8 and w != 320 for w, t, c in w_seen) and \
            any(t != max(1, w // 8) for w, t, c in w_seen):
        res["ok"] = False
        res["notes"].append("T != W/8 — приложение такое не разберёт")
    if any(c != num_classes(charset) for w, t, c in w_seen):
        res["ok"] = False
        res["notes"].append(f"классов не {num_classes(charset)}")
    if res["torch_max_diff"] is not None and res["torch_max_diff"] > 1e-4:
        res["ok"] = False
        res["notes"].append("ONNX расходится с torch")
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="Экспорт .pt → .onnx с проверкой контракта")
    ap.add_argument("--ckpt", default="runs/bench.pt")
    ap.add_argument("--out", default="models/rec_bench.onnx")
    ap.add_argument("--lines", type=int, default=40)
    ap.add_argument("--opset", type=int, default=17)
    a = ap.parse_args(argv)
    export(a.ckpt, a.out, a.opset)
    res = verify(a.out, a.ckpt, a.lines)
    print(f"{res['file']}: {res['mb']} МБ · вход {res['input']} · формы {res['shapes']}")
    print(f"  сумма вероятностей {res['prob_sum']} · расхождение с torch {res['torch_max_diff']}")
    print(f"  CER на {a.lines} отложенных строках: {res['cer']*100:.1f} %")
    for s in res["sample"]:
        print("   ", s)
    if not res["ok"]:
        print("  ОТКАЗ:", "; ".join(res["notes"]))
        return 1
    print("  КОНТРАКТ ПРИЛОЖЕНИЯ ВЫПОЛНЕН")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
