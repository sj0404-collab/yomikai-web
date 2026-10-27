"""СБОР РАЗМЕТКИ с настоящих страниц: строки-кропы ровно такими, какими их видит
распознаватель приложения.

  python3 tools/make_dataset.py --pages /home/user/uploads/*.jpg --limit 12 --out data/lines

Что делает: открывает `koma-web.html` в Chromium, поднимает движок (детектор +
распознаватель + словарь), для каждой страницы гоняет ТОТ ЖЕ путь, что и читалка —
`detectWithRetry` → `textLines` — и выгружает каждый кроп строки картинкой.
Поэтому обучаться будет ровно на том, что модель увидит в бою: та же резка, те же
поля, тот же масштаб.

Рядом кладётся:
  data/lines/<страница>__<номер>.png   кропы (как есть)
  data/lines/index.json               откуда взят каждый кроп (страница, бокс, координаты)
  data/lines/sheet-<страница>.png     лист для разметки: кропы друг под другом с номерами

Дальше глазами: смотрим листы, пишем `data/lines/labels.tsv` в формате
`путь<TAB>текст`, и `tools/train_rec.py --crops data/lines --labels data/lines/labels.tsv`
учит модель на настоящих строках.
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import sys

from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw

def launch(p):
    """Chromium для песочницы: свой бинарь + библиотеки из ~/libs (см. tools/README).

    В контейнере нет системных libnspr4/libnss3, поэтому браузер запускается с
    LD_LIBRARY_PATH=~/libs/usr/lib/x86_64-linux-gnu. Если переменная не задана —
    обычный запуск playwright (как на своей машине и на раннере CI).
    """
    exe = os.environ.get("CHROME_EXE") or ""
    kw = {"args": ["--no-sandbox", "--allow-file-access-from-files"]}
    if exe and os.path.exists(exe):
        kw["executable_path"] = exe
    return p.chromium.launch(**kw)


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def b64file(path: str) -> str:
    return base64.b64encode(open(path, "rb").read()).decode()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", nargs="+", required=True, help="картинки страниц")
    ap.add_argument("--html", default=os.path.join(os.path.dirname(REPO), "koma-web.html"))
    ap.add_argument("--models", default="/home/user/koma_models")
    ap.add_argument("--out", default=os.path.join(REPO, "data", "lines"))
    ap.add_argument("--limit", type=int, default=12, help="сколько страниц брать")
    ap.add_argument("--scale", type=float, default=1.0, help="во сколько раз увеличить кропы")
    a = ap.parse_args(argv)

    pages = sorted(sum([glob.glob(p) for p in a.pages], []))[: a.limit]
    if not pages:
        print("нет страниц")
        return 2
    os.makedirs(a.out, exist_ok=True)

    index = []
    with sync_playwright() as p:
        browser = launch(p)
        page = browser.new_page(viewport={"width": 420, "height": 780})
        page.goto("file://" + a.html)
        page.wait_for_timeout(1200)
        engine = page.evaluate("""async ([det, rec, dict]) => {
            const toBytes = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
            await DB.put('kv', { k: 'model:det', v: toBytes(det).buffer });
            await DB.put('kv', { k: 'model:rec', v: toBytes(rec).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(toBytes(dict)) });
            const ok = await OCR.loadModels();
            return { ok, engine: OCR.engine, reason: OCR.reason };
        }""", [b64file(os.path.join(a.models, "koma_det.onnx")),
               b64file(os.path.join(a.models, "koma_rec.onnx")),
               b64file(os.path.join(a.models, "koma_dict.txt"))])
        if not engine.get("ok"):
            print("движок не поднялся:", engine)
            browser.close()
            return 1
        print("движок готов")

        for i, path in enumerate(pages, 1):
            name = os.path.splitext(os.path.basename(path))[0]
            crops = page.evaluate("""async ([b64img, scale]) => {
                const img = new Image();
                img.src = 'data:image/jpeg;base64,' + b64img;
                await img.decode();
                const c = makeCanvas(img.naturalWidth, img.naturalHeight);
                c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
                const R = sanitizeRules(RULES);
                const det = await detectWithRetry(c, R);
                const out = [];
                for (let bi = 0; bi < det.boxes.length; bi++) {
                    const box = det.boxes[bi];
                    const lines = textLines(c, box, R);
                    for (let li = 0; li < lines.length; li++) {
                        const ln = lines[li];
                        const w = Math.max(1, ln.right - ln.left), h = Math.max(1, ln.bottom - ln.top);
                        if (w < 8 || h < 6) continue;
                        const cv = makeCanvas(Math.round(w * scale), Math.round(h * scale));
                        const g = cv.getContext('2d', { willReadFrequently: true });
                        g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
                        g.drawImage(c, ln.left, ln.top, w, h, 0, 0, cv.width, cv.height);
                        // заодно читаем кроп тем распознавателем, что стоит в
                        // приложении: это заготовка для разметки — править
                        // ошибки глазами быстрее, чем писать строки с нуля
                        let guess = '', conf = 0;
                        try { [guess, conf] = await decodeBetter(cv, R); } catch (e) { guess = ''; }
                        out.push({ box: bi, line: li, w, h,
                                   left: Math.round(ln.left), top: Math.round(ln.top),
                                   guess, conf: +(conf || 0).toFixed(3),
                                   png: cv.toDataURL('image/png').split(',')[1] });
                    }
                }
                return { boxes: det.boxes.length, crops: out };
            }""", [b64file(path), a.scale])

            n = 0
            for k, cr in enumerate(crops["crops"]):
                fn = f"{name}__{k:02d}.png"
                raw = base64.b64decode(cr["png"])
                open(os.path.join(a.out, fn), "wb").write(raw)
                index.append({"file": fn, "page": os.path.basename(path),
                              "box": cr["box"], "line": cr["line"],
                              "w": cr["w"], "h": cr["h"],
                              "left": cr["left"], "top": cr["top"],
                              "guess": cr["guess"], "conf": cr["conf"], "text": ""})
                n += 1
            print(f"{i:2d}. {os.path.basename(path)}: боксов {crops['boxes']}, строк {n}")
        browser.close()

    # листы для разметки: кропы подряд, с номером слева (номер = порядок в labels.tsv)
    by_page = {}
    for rec in index:
        by_page.setdefault(rec["page"], []).append(rec)
    for pg, recs in by_page.items():
        imgs = [Image.open(os.path.join(a.out, r["file"])).convert("RGB") for r in recs]
        pad, label_w = 8, 30
        W = max(im.width for im in imgs) + label_w + pad
        H = sum(im.height + pad + 14 for im in imgs) + pad
        sheet = Image.new("RGB", (W, H), (245, 245, 245))
        d = ImageDraw.Draw(sheet)
        y = pad
        for r, im in zip(recs, imgs):
            sheet.paste(im, (label_w, y))
            d.text((4, y + im.height // 2 - 6), f"{int(r['file'].split('__')[1][:2])}", fill=(20, 20, 20))
            d.text((label_w, y + im.height + 1), "→ " + (r.get("guess") or ""),  fill=(150, 30, 30))
            y += im.height + pad + 14
        sp = os.path.join(a.out, "sheet-" + os.path.splitext(pg)[0] + ".png")
        sheet.save(sp)

    with open(os.path.join(a.out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"\nвсего кропов {len(index)} на {len(by_page)} страницах → {a.out}")
    print("дальше: смотреть sheet-*.png и заполнять labels.tsv (путь<TAB>текст)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
