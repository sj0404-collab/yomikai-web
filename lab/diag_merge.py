"""Где теряется проза: чтение полосами → порядок → склейка → слияние полос.

  python3 lab/diag_merge.py [страница.jpg]

Печатает, сколько реплик остаётся на каждом шаге и ЧТО именно выброшено.
Замер 28.10 на page-15 (две газетные колонки): распознавание дало 58 строк,
а до шторки доходило 2 реплики и 8 слов — этот скрипт показывает виновника.
"""
import base64
import os
import sys

from playwright.sync_api import sync_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = '/home/user/koma_models'
DEFAULT_PAGE = os.path.join(REPO, 'data', 'real', 'vesyolyie_kartinki_1988_12_djvu', 'page-15.jpg')


def b64(path):
    return base64.b64encode(open(path, 'rb').read()).decode()


JS = """async ([b64img, viewH]) => {
  const img = new Image();
  img.src = 'data:image/jpeg;base64,' + b64img;
  await img.decode();
  const c = makeCanvas(img.naturalWidth, img.naturalHeight);
  c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
  const R = sanitizeRules(RULES);
  const H = c.height;
  const pad = Math.min(H * R.bandOverlap, viewH * 0.25);
  const parts = [];
  for (let scroll = 0; scroll < H; scroll += viewH) {
    const y0 = Math.max(0, scroll - pad), y1 = Math.min(H, scroll + viewH + pad);
    const key = Math.round(scroll / 96) + ':' + Math.round((scroll + viewH) / 96);
    const res = await recognizePage(c, R, null, { y0, y1, vy0: scroll, vy1: scroll + viewH, key });
    const lines = readingOrder(res.regions, true, true, R);
    parts.push({ key, res, lines, raw: (res.regions || []).length });
  }
  const merged = mergeBandLines(parts.map(p => p), c);
  return {
    parts: parts.map(p => ({
      key: p.key, raw: p.raw, after_order: p.lines.length,
      words: p.lines.reduce((a, l) => a + (l.text.match(/[А-Яа-яЁё]{2,}/g) || []).length, 0),
      lines: p.lines.map(l => ({ t: l.text.slice(0, 60), top: +l.top.toFixed(3),
                                 bot: +l.bottom.toFixed(3), left: +l.left.toFixed(3) })),
    })),
    merged: merged.map(l => ({ t: l.text.slice(0, 60), top: +l.top.toFixed(3),
                               bot: +l.bottom.toFixed(3) })),
  };
}"""


def main(argv):
    page = argv[0] if argv else DEFAULT_PAGE
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
        out = pg.evaluate(JS, [b64(page), 800])
        for part in out['parts']:
            print(f"\n── полоса {part['key']}: строк {part['raw']} → после порядка "
                  f"{part['after_order']} · слов {part['words']}")
            for l in part['lines']:
                print(f"   [{l['top']:.3f}–{l['bot']:.3f} x{l['left']:.2f}] {l['t']!r}")
        print(f"\n── после слияния полос: {len(out['merged'])} реплик")
        for l in out['merged']:
            print(f"   [{l['top']:.3f}–{l['bot']:.3f}] {l['t']!r}")
        b.close()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
