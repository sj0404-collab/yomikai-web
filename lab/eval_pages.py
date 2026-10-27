"""Прогон настоящих страниц манги в приложении: сколько реплик, есть ли дубли.

  LD_LIBRARY_PATH=~/libs/usr/lib/x86_64-linux-gnu CHROME_EXE=... \
  python3 lab/eval_pages.py [сколько страниц]

Читает страницы ПОЛОСАМИ, как телефон 412×800, с НАСТРОЙКАМИ ПО УМОЛЧАНИЮ
(`RULES`), то есть ровно тем путём, которым идёт пользователь. Для каждой
страницы печатает число полос, реплик, время, попадания в кэш и текст. Отдельно
ищет то, что считается дефектом по критериям приёмки: одинаковый текст дважды
(дубль из-за перекрытия полос) и реплики не по порядку сверху вниз.
"""
import base64, json, os, sys

from playwright.sync_api import sync_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = '/home/user/koma-web.html'
MODELS = '/home/user/koma_models'
UPLOADS = '/home/user/uploads'
PAGES = os.environ.get('PAGES') or os.path.join(REPO, 'lab', 'pages_real.txt')


def b64(p):
    return base64.b64encode(open(p, 'rb').read()).decode()


def launch(p):
    exe = os.environ.get('CHROME_EXE') or ''
    kw = {'args': ['--no-sandbox', '--allow-file-access-from-files']}
    if exe and os.path.exists(exe):
        kw['executable_path'] = exe
    return p.chromium.launch(**kw)


PAGE_JS = """async ([b64img, speed]) => {
    const img = new Image();
    img.src = 'data:image/jpeg;base64,' + b64img;
    await img.decode();
    const c = makeCanvas(img.naturalWidth, img.naturalHeight);
    c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
    const viewH = 800, H = c.height;
    const R = sanitizeRules(speed ? { ...RULES, speed } : RULES);
    const pad = Math.min(H * R.bandOverlap, viewH * 0.25);
    const keys = new Map();
    const t0 = performance.now();
    let scans = 0;
    for (let scroll = 0; scroll < H; scroll += viewH) {
        const y0 = Math.max(0, scroll - pad);
        const y1 = Math.min(H, scroll + viewH + pad);
        const key = Math.round(scroll / 96) + ':' + Math.round((scroll + viewH) / 96);
        if (keys.has(key)) continue;
        const res = await recognizePage(c, R, null, { y0, y1, vy0: scroll, vy1: scroll + viewH, key });
        keys.set(key, { lines: readingOrder(res.regions, true, true, R), res });
        scans++;
    }
    const parts = Array.from(keys.entries())
        .sort((a, b) => (a[1].res.band?.y0 ?? 0) - (b[1].res.band?.y0 ?? 0));
    const lines = mergeBandLines(parts.map(([, p]) => p), c);
    return { scans, ms: Math.round(performance.now() - t0), size: [c.width, c.height],
             crops: parts.reduce((a, [, p]) => a + p.res.crops, 0),
             hits: _textHits, miss: _textMiss,
             lines: lines.map(l => ({ text: l.text, top: +l.top.toFixed(3), large: !!l.large })) };
}"""


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    names = [l.strip() for l in open(PAGES, encoding='utf-8') if l.strip()][:limit]
    rows = []
    with sync_playwright() as p:
        b = launch(p)
        page = b.new_page(viewport={'width': 412, 'height': 800})
        page.goto('file://' + HTML)
        page.wait_for_timeout(1200)
        page.evaluate("""async ([det, rec, dict]) => {
            const t = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
            await DB.put('kv', { k: 'model:det', v: t(det).buffer });
            await DB.put('kv', { k: 'model:rec', v: t(rec).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(t(dict)) });
            return await OCR.loadModels();
        }""", [b64(os.path.join(MODELS, 'koma_det.onnx')),
               b64(os.path.join(MODELS, 'koma_rec.onnx')),
               b64(os.path.join(MODELS, 'koma_dict.txt'))])
        page.evaluate("""(text) => {
            const rank = new Map(); let n = 0;
            for (const line of text.split('\\n')) {
              const w = (line.split(/\\s+/)[0] || '').toLowerCase();
              if (!w) continue;
              if (!rank.has(w)) rank.set(w, n);
              n++;
            }
            Words.rank = rank; Words.ready = rank.size > 0;
        }""", open('/home/user/lab/ru_250k.txt', encoding='utf-8').read())

        for i, name in enumerate(names, 1):
            path = os.path.join(UPLOADS, name)
            if not os.path.exists(path):
                print(f'{i}. {name} — файла нет, пропуск')
                continue
            page.evaluate("[_textHits = 0, _textMiss = 0, _textCache.clear()]")
            r = page.evaluate(PAGE_JS, [b64(path), os.environ.get('SPEED') or ''])
            texts = [l['text'] for l in r['lines']]
            norm = [' '.join(t.lower().split()) for t in texts]
            dup = len(norm) != len(set(norm))
            order_ok = all(r['lines'][j]['top'] <= r['lines'][j + 1]['top'] + 0.02
                           for j in range(len(r['lines']) - 1))
            rows.append({'page': name, 'size': r['size'], 'scans': r['scans'], 'ms': r['ms'],
                         'crops': r['crops'], 'hits': r['hits'], 'miss': r['miss'],
                         'dup': dup, 'order_ok': order_ok, 'texts': texts})
            print(f"{i}. {name} {r['size'][0]}×{r['size'][1]} · полос {r['scans']} · реплик {len(texts)} "
                  f"· {r['ms']} мс · кэш {r['hits']}/{r['hits'] + r['miss']}"
                  f"{' · ДУБЛИ' if dup else ''}{'' if order_ok else ' · ПОРЯДОК СБИТ'}")
            for t in texts:
                print('     ', t[:110])
        b.close()
    json.dump(rows, open(os.path.join(REPO, 'runs', 'eval_pages.json'), 'w'), ensure_ascii=False, indent=1)
    bad = [r for r in rows if r['dup'] or not r['order_ok']]
    print(f"\nстраниц {len(rows)} · с дефектами {len(bad)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
