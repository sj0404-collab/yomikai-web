"""Проверка ЛЮБОГО файла распознавателя: подойдёт ли он приложению.

  python3 tools/check_onnx_contract.py koma_models/koma_rec.onnx
  python3 tools/check_onnx_contract.py models/rec_bench.onnx --lines 20

Проверяет ровно то, на что опирается part3.js:
  · вход float32 [N,3,48,W], W меняется (не зашита);
  · выход [1,T,C], T = W/8, C = 519 при штатной азбуке (517 символов + blank + «неизвестно»);
  · значения — вероятности: сумма по классам ≈ 1 (beamDecode берёт от них log);
  · класс 0 — blank: на пустой серой картинке он и должен побеждать.
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import onnxruntime as ort

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from charset import load_charset, num_classes  # noqa: E402


def check(path: str, lines: int = 3, verbose: bool = True) -> tuple:
    charset = load_charset()
    want_c = num_classes(charset)
    notes, ok = [], True
    sess = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0]
    shape = list(inp.shape)
    mb = round(os.path.getsize(path) / 1e6, 2)
    if len(shape) != 4 or shape[1] != 3 or shape[2] != 48:
        ok = False
        notes.append(f"вход {shape}: ожидался [N,3,48,W]")
    if inp.type != "tensor(float)":
        ok = False
        notes.append(f"тип входа {inp.type}: ожидался tensor(float)")

    for W in (320, 448):
        x = np.zeros((1, 3, 48, W), dtype=np.float32)      # 0 = серый 128, как в приложении
        try:
            out = sess.run(None, {inp.name: x})[0]
        except Exception as e:                              # noqa: BLE001
            ok = False
            notes.append(f"модель не приняла вход [1,3,48,{W}]: {str(e).splitlines()[-1][:120]}")
            break
        t_expect = W // 8
        if out.ndim != 3 or out.shape[0] != 1:
            ok = False
            notes.append(f"выход {out.shape}: ожидался [1,T,C]")
        elif out.shape[1] != t_expect:
            ok = False
            notes.append(f"W={W}: T={out.shape[1]}, ожидалось {t_expect} (шаг 8)")
        if out.shape[-1] != want_c:
            ok = False
            notes.append(f"классов {out.shape[-1]}, ожидалось {want_c}")
        s = float(out.sum(-1).mean())
        if not (0.98 <= s <= 1.02):
            ok = False
            notes.append(f"сумма вероятностей {s:.3f}: модель отдаёт не вероятности, "
                         f"а логиты — beamDecode приложения такую не поймёт")
        blank_share = float((out[0].argmax(-1) == 0).mean())
        if blank_share < 0.5:
            ok = False
            notes.append(f"на пустой картинке blank только в {blank_share*100:.0f} % кадров")

    if verbose:
        print(f"{os.path.basename(path)}: {mb} МБ · вход {inp.name}{shape}")
        print("  " + ("ГОДИТСЯ" if ok else "НЕ ГОДИТСЯ") +
              ("" if ok else ": " + "; ".join(notes)))
    return ok, notes


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--lines", type=int, default=3)
    a = ap.parse_args()
    good, _ = check(a.model)
    raise SystemExit(0 if good else 1)
