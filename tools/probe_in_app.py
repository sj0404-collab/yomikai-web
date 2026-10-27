"""Проверка обученной модели ВНУТРИ приложения: Chromium + koma-web.html.

Кладём .onnx в IndexedDB ровно так, как это делает ⚙ → Модели, поднимаем движок
(onnxruntime-web + вшитые wasm) и читаем настоящие строки штатным кодом страницы:
жадно (`decodeCrop`) и своим словарным декодером (`beamDecode`), плюс правку по
словарю. Никаких заглушек: считается то, что увидит пользователь.

  python3 tools/probe_in_app.py --onnx models/rec_synth.onnx --lines 20
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import random
import sys

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from charset import cer, load_charset          # noqa: E402
import synth                                   # noqa: E402


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def png_of(x3) -> bytes:
    """Картинка строки (3×48×W, значения −1…1) → PNG, как её видит приложение."""
    from PIL import Image
    import numpy as np
    a = ((np.asarray(x3[0]) + 1) / 2 * 255).clip(0, 255).astype("uint8")
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, format="PNG")
    return buf.getvalue()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default=os.path.join(os.path.dirname(REPO), "koma-web.html"))
    ap.add_argument("--onnx", default=os.path.join(REPO, "models", "rec_synth.onnx"))
    ap.add_argument("--lines", type=int, default=20)
    ap.add_argument("--det", default="/home/user/koma_models/koma_det.onnx",
                    help="детектор облачков: без него OCR.loadModels() отказывается")
    a = ap.parse_args(argv)
    if not os.path.exists(a.html):
        print(f"нет сборки {a.html} — сначала ./build.sh")
        return 2

    cs = load_charset()
    renderer = synth.LineRenderer(synth.load_words(20000), cs, hard=0.3, max_chars=14)
    rng = random.Random(4242)
    cases = []
    for _ in range(a.lines):
        x3, text = renderer.render(rng)
        cases.append((b64(png_of(x3)), text))

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--allow-file-access-from-files"])
        page = browser.new_page(viewport={"width": 420, "height": 780})
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)[:200]))
        page.goto("file://" + a.html)
        page.wait_for_timeout(1500)

        det_b64 = b64(open(a.det, "rb").read()) if os.path.exists(a.det) else ""
        res = page.evaluate("""async ([rec, chars, det]) => {
            const toBytes = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
            if (det) await DB.put('kv', { k: 'model:det', v: toBytes(det).buffer });
            await DB.put('kv', { k: 'model:rec', v: toBytes(rec).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(toBytes(chars)) });
            const ok = await OCR.loadModels();
            return { ok, engine: OCR.engine, reason: OCR.reason,
                     dictLen: OCR.dict ? OCR.dict.length : 0,
                     words: Words.ready ? Words.size : 0 };
        }""", [b64(open(a.onnx, "rb").read()),
               b64(open(os.path.join(HERE, "rec_charset.txt"), "rb").read()), det_b64])
        print("движок:", res)
        if not res.get("ok"):
            browser.close()
            return 1

        out = page.evaluate("""async (cases) => {
            const res = [];
            for (const [png, _] of cases) {
                const img = new Image();
                await new Promise((ok, bad) => { img.onload = ok; img.onerror = bad;
                    img.src = 'data:image/png;base64,' + png; });
                const cv = makeCanvas(img.width, img.height);
                cv.getContext('2d').drawImage(img, 0, 0);
                _probsCache = { canvas: null, res: null };
                const greedy = await decodeCrop(cv);
                _probsCache = { canvas: null, res: null };
                const probs = await recProbs(cv);
                const beam = probs ? beamDecode(probs) : ['', 0];
                const better = await decodeBetter(cv, RULES);
                res.push([greedy[0], beam[0], better[0]]);
            }
            return res;
        }""", cases)

    rows = []
    for (png, ref), (g, bm, bt) in zip(cases, out):
        rows.append((ref, g, bm, bt))
    n = len(rows)
    cg = sum(cer(r[0], r[1]) for r in rows) / n
    cb = sum(cer(r[0], r[2]) for r in rows) / n
    cd = sum(cer(r[0], r[3]) for r in rows) / n
    print(f"\nстрок {n} · CER: жадно {cg*100:.1f} % · свой декодер {cb*100:.1f} % · "
          f"с правкой по словарю {cd*100:.1f} %")
    for ref, g, bm, bt in rows[:6]:
        print(f"  {ref}\n    жадно:    {g}\n    декодер:  {bm}\n    с правкой:{bt}")
    if errs:
        print("ошибки страницы:", errs[:3])
    return 0


if __name__ == "__main__":
    sys.exit(main())
