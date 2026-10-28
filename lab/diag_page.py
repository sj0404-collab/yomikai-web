"""Почему на чужой странице читается мало строк: разбор по шагам.

  python3 lab/diag_page.py data/real/vesyolyie_kartinki_1988_12_djvu/page-05.jpg

Печатает воронку: сколько боксов нашёл детектор, сколько строк нарезано,
сколько из них прошло порог уверенности, сколько русских и сколько выжило
после чистки словарём. Так видно, на каком шаге теряется текст, а не «мало и
всё тут».
"""
import base64
import json
import os
import sys

from playwright.sync_api import sync_playwright

MODELS = '/home/user/koma_models'
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def b64(path):
    return base64.b64encode(open(path, 'rb').read()).decode()


JS = """async ([b64img, side]) => {
  const img = new Image();
  img.src = 'data:image/jpeg;base64,' + b64img;
  await img.decode();
  const c = makeCanvas(img.naturalWidth, img.naturalHeight);
  c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
  const R = sanitizeRules(side ? { ...RULES, pageSide: side } : RULES);
  const t0 = performance.now();
  const res = await recognizePage(c, R, null, { y0: 0, y1: c.height, vy0: 0, vy1: c.height, key: 'diag' });
  const regs = (res.regions || []);
  const text = (r) => String(r.text || '');
  const raw = regs.map(text);
  const cyr = raw.filter(t => isCyr(t));
  const conf = regs.filter(r => r.confidence > R.minConfidence).map(text);
  const polished = regs.map(r => Words.polish(text(r), R.junkRatio, r.confidence));
  // сколько слов знает словарь — видно, настоящий ли это текст
  const known = raw.map(t => {
    const ws = (t.match(/[А-Яа-яЁё]{2,}/g) || []).map(w => w.toLowerCase());
    return ws.length ? ws.filter(w => Words.inDict(w)).length + '/' + ws.length : '0/0';
  });
  // ── воронка сборки реплик ────────────────────────────────────────────────
  const rtl = true;
  const fixed = regs.map(r => {
    let t = String(r.text || '').replace(/\u00AD/g, '-').replace(/\s+/g, ' ').trim();
    t = applyWordFixes(t, R.wordFixes);
    return { ...r, text: fixLookalikes(t) };
  }).filter(r => /[\p{L}\p{N}]/u.test(r.text));
  const cyrOnly = fixed.filter(r => isCyr(r.text));
  const panels = splitPanels(cyrOnly, rtl, 0);
  const bubbles = panels.flatMap(pnl => bubblesOf(pnl, rtl, R));
  const polished2 = bubbles.map(l => ({ ...l, text: Words.polish(l.text, R.junkRatio, l.confidence) }))
    .filter(l => l.text && (l.text.match(/\p{L}/gu) || []).length >= 2);
  const funnel = {
    реплик_до_сборки: regs.length, с_буквами: fixed.length, русских: cyrOnly.length,
    панелей: panels.length, панели_по_числу: panels.map(p => p.length),
    реплик_после_склейки: bubbles.length,
    после_чистки: polished2.length,
    выжили: polished2.map(l => l.text.slice(0, 50)),
    обломки: bubbles.map((l, i) => {
      const t = String(l.text || '');
      const ws = (t.match(/[А-Яа-яЁё]{2,}/g) || []).map(w => w.toLowerCase());
      const known = ws.filter(w => Words.isKnown(w));
      const pol = Words.polish(t, R.junkRatio, l.confidence);
      return { i, слов: ws.length, известных: known.length, знак: pol ? '' : '×',
               начало: t.slice(0, 42), конец: t.slice(-22) };
    }),
  };
  return {
    funnel,
    size: [c.width, c.height], pageSide: R.pageSide, junkRatio: R.junkRatio,
    ms: Math.round(performance.now() - t0),
    boxes: res.boxes, crops: res.crops, regions: raw.length,
    cyr: cyr.length, conf: conf.length,
    lines_out: null,
    raw, confTexts: conf, polished, known,
  };
}"""


def main(path: str) -> int:
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--no-sandbox', '--allow-file-access-from-files'])
        pg = b.new_page(viewport={'width': 412, 'height': 800})
        pg.goto('file:///home/user/koma-web.html')
        pg.wait_for_timeout(1200)
        ok = pg.evaluate("""async ([d, r, t]) => {
            const u = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
            await DB.put('kv', { k: 'model:det', v: u(d).buffer });
            await DB.put('kv', { k: 'model:rec', v: u(r).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(u(t)) });
            return await OCR.loadModels();
        }""", [b64(MODELS + '/koma_det.onnx'), b64(MODELS + '/koma_rec.onnx'),
               b64(MODELS + '/koma_dict.txt')])
        print('движок:', ok)
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
        for side in [None, 2200]:
            out = pg.evaluate(JS, [b64(path), side])
            print(f"\n── pageSide={out['pageSide']} · {out['size'][0]}×{out['size'][1]} · {out['ms']} мс")
            print(f"   боксов {out['boxes']} · кропов {out['crops']} · строк {out['regions']} · "
                  f"русских {out['cyr']} · выше порога {out['conf']}")
            f = out['funnel']
            print(f"   воронка: {f['реплик_до_сборки']} строк → с буквами {f['с_буквами']} → "
                  f"русских {f['русских']} → панелей {f['панелей']} {f['панели_по_числу']} → "
                  f"после склейки {f['реплик_после_склейки']} → после чистки {f['после_чистки']}")
            for x in f['обломки']:
                print(f"   {x['знак'] or '·'} #{x['i']:2d} слов {x['слов']:3d} известных {x['известных']:3d} "
                      f"| {x['начало']!r} … {x['конец']!r}")
            for i, t in enumerate(f['выжили']):
                print(f"   ✔ {i + 1:2d}. {t!r}")
            for i, (t, k, pol) in enumerate(zip(out['raw'], out['known'], out['polished'])):
                if i >= 22:
                    print(f"   … ещё {len(out['raw']) - 22}")
                    break
                mark = '' if pol == t else f'  →  {pol[:40]!r}'
                print(f"   {i + 1:2d}. {t[:62]!r}  словарь {k}{mark}")
            json.dump(out, open(os.path.join(REPO, 'runs', 'diag_page.json'), 'w'), ensure_ascii=False)
        b.close()
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else
                  os.path.join(REPO, 'data', 'real', 'vesyolyie_kartinki_1988_12_djvu', 'page-05.jpg')))
