"""Полоса против целой страницы: где теряется текст на прозе.

  python3 lab/eval_bands.py [страница.jpg] [--viewH 800]

Читалка на телефоне читает страницу ПОЛОСАМИ (видимая область), и это
требование (длинную страницу читать только в пределах видимого). Но на чужой
прозе (журнал, книга) полосовое чтение даёт в разы меньше текста, чем чтение
страницы целиком: замер 28.10 на «Весёлых картинках» 1988 — 4,8 % слов эталона
полосами против ~60 % целой страницей. Этот скрипт показывает разницу по шагам,
чтобы править конвейер, а не гадать.
"""
import base64
import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = '/home/user/koma_models'
DEFAULT_PAGE = os.path.join(REPO, 'data', 'real', 'vesyolyie_kartinki_1988_12_djvu', 'page-15.jpg')


def b64(path):
    return base64.b64encode(open(path, 'rb').read()).decode()


JS = """async ([b64img, viewH, mode]) => {
  const img = new Image();
  img.src = 'data:image/jpeg;base64,' + b64img;
  await img.decode();
  const c = makeCanvas(img.naturalWidth, img.naturalHeight);
  c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
  const R = sanitizeRules(RULES);
  const H = c.height;
  const t0 = performance.now();
  const bands = [];
  if (mode === 'full') {
    bands.push([0, H, 'full']);
  } else {
    const pad = Math.min(H * R.bandOverlap, viewH * 0.25);
    for (let scroll = 0; scroll < H; scroll += viewH) {
      bands.push([Math.max(0, scroll - pad), Math.min(H, scroll + viewH + pad),
                  Math.round(scroll / 96) + ':' + Math.round((scroll + viewH) / 96)]);
    }
  }
  const parts = [];
  for (const [y0, y1, key] of bands) {
    const res = await recognizePage(c, R, null, { y0, y1, vy0: y0, vy1: y1, key });
    parts.push({ key, y0, y1, boxes: res.boxes, crops: res.crops,
                 n: (res.regions || []).length,
                 text: (res.regions || []).map(r => String(r.text || '')) });
  }
  return { size: [c.width, c.height], ms: Math.round(performance.now() - t0), parts,
           bandOverlap: R.bandOverlap };
}"""


def norm(s):
    return re.sub(r'[^а-я0-9]+', ' ', s.lower().replace('ё', 'е')).strip()


def main(argv):
    page_path = DEFAULT_PAGE
    viewH = 800
    i = 0
    while i < len(argv):
        if argv[i] == '--viewH':
            viewH = int(argv[i + 1]); i += 2
        else:
            page_path = argv[i]; i += 1
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--no-sandbox', '--allow-file-access-from-files'])
        pg = b.new_page(viewport={'width': 412, 'height': 800})
        pg.goto('file:///home/user/koma-web.html')
        pg.wait_for_timeout(1200)
        pg.evaluate("""async ([d, r, t]) => {
            const u = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
            await DB.put('kv', { k: 'model:det', v: u(d).buffer });
            await DB.put('kv', { k: 'model:rec', v: u(r).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(u(t)) });
            return await OCR.loadModels();
        }""", [b64(MODELS + '/koma_det.onnx'), b64(MODELS + '/koma_rec.onnx'),
               b64(MODELS + '/koma_dict.txt')])
        pg.evaluate("""(text) => {
            const rank = new Map(); let n = 0;
            for (const line of text.split('\\n')) {
              const w = (line.split(/\\s+/)[0] || '').toLowerCase();
              if (!w) continue;
              if (!rank.has(w)) rank.set(w, n);
              n++;
            }
            Words.rank = rank; Words.ready = rank.size > 0;
        }""", open(os.path.join(REPO, 'data', 'ru_250k.txt'), encoding='utf-8').read())

        out = {}
        for mode in ('full', 'bands'):
            r = pg.evaluate(JS, [b64(page_path), viewH, mode])
            out[mode] = r
            words = sum(len(norm(t).split()) for part in r['parts'] for t in part['text'])
            print(f"\n── {mode}: {r['size'][0]}×{r['size'][1]} · {r['ms']} мс · "
                  f"полос {len(r['parts'])} · слов {words}")
            for part in r['parts']:
                print(f"   полоса {part['key']:<12} y {part['y0']}–{part['y1']}: "
                      f"боксов {part['boxes']}, кропов {part['crops']}, строк {part['n']}")
                for t in part['text'][:3]:
                    print(f"      {t[:70]!r}")
        json.dump(out, open(os.path.join(REPO, 'runs', 'eval_bands.json'), 'w'), ensure_ascii=False)
        b.close()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
