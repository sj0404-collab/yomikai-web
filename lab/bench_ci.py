#!/usr/bin/env python3
"""Замер скорости и качества чтения на настоящем браузере — для GitHub Actions.

Локальная песочница на 1,9 ГБ памяти роняла вкладку на `pageSide 1600`
(«Target crashed»), поэтому длинные замеры не получались. На ранере памяти и
ядер больше, а прогоны идут параллельно (matrix), так что таблица собирается за
минуты и без падений.

Запуск:
    python3 lab/bench_ci.py --page dense --speed fast --autodepth 0
    python3 lab/bench_ci.py --all

Печатает строки вида
    RESULT page=dense speed=normal autoDepth=1 ms=37606 calls=282 regions=61 dict=83.8
и пишет bench-result.json (артефакт workflow).
"""
import argparse
import base64
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HTML = os.environ.get('KOMA_HTML', os.path.join(ROOT, 'koma-web.html'))
MODELS = os.path.join(ROOT, 'models')
DICT = os.path.join(MODELS, 'koma_dict.txt')
WORDS = os.path.join(ROOT, 'data', 'ru_250k.txt')
PAGES = {
    # плотная манга: 60+ реплик, самое злое для скорости
    'dense': os.path.join(ROOT, 'data', 'real', 'dense.jpg'),
    # проза с цветными картинками: проверка, что дожим не съедает текст
    'prose': os.path.join(ROOT, 'data', 'real', 'prose-15.jpg'),
}

JS_PAGE = r"""async ([b64img, speed, autoDepth, twice]) => {
  const img = new Image(); img.src = 'data:image/jpeg;base64,' + b64img; await img.decode();
  const full = makeCanvas(img.naturalWidth, img.naturalHeight);
  full.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
  // autoDepth === 2 — «как в профиле»: у профиля «Умно» дожим включён сам,
  // и перебивать его снаружи нельзя, иначе замеряем не тот режим.
  const base = { ...RULES, speed };
  if (autoDepth === 0 || autoDepth === 1) base.autoDepth = autoDepth === 1;
  const R = sanitizeRules(base);
  // МЕЖДУ ЗАМЕРАМИ КЭШ НАДО ЧИСТИТЬ. Ключ кэша — пиксели кропа и настройки
  // чтения, но НЕ профиль: если гнать «Быстро» и «Обычно» подряд в одной
  // вкладке, второй замер попадает в кэш первого и показывает 0 вызовов
  // модели (ровно так и вышло в первом прогоне serial). Чистим, иначе цифры
  // врут в пользу того, кто бежит вторым.
  try { _textCache.clear(); } catch (e) {}
  try { if (typeof _decCache !== 'undefined') _decCache.clear(); } catch (e) {}
  try { _probsCache = { canvas: null, res: null }; } catch (e) {}
  let calls = 0;
  const orig = window.decodeCrop;
  window.decodeCrop = function (...a) { calls++; return orig.apply(this, a); };
  const opt = { y0: 0, y1: full.height, vy0: 0, vy1: full.height, key: 'bench' };
  const t = performance.now();
  const res = await recognizePage(full, R, null, opt);
  const ms = Math.round(performance.now() - t);
  const calls1 = calls;
  const texts = (res.regions || []).map(r => String(r.text || ''));
  // Кэш: второй проход по той же странице не должен трогать модель.
  let ms2 = null, calls2 = null, same = null;
  if (twice) {
    const t2 = performance.now();
    const res2 = await recognizePage(full, R, null, opt);
    ms2 = Math.round(performance.now() - t2);
    calls2 = calls - calls1;
    const tx = r => (r.regions || []).map(x => String(x.text || '')).join('|');
    same = tx(res) === tx(res2);
  }
  window.decodeCrop = orig;
  const ws = texts.flatMap(x => (x.match(/[А-Яа-яЁё]{2,}/g) || []).map(w => w.toLowerCase()));
  return {
    ms, calls: calls1, regions: texts.length, words: ws.length,
    known: ws.filter(w => Words.isKnown(w)).length,
    ms2, calls2, same,
    ext: R.extCrop, side: R.pageSide, ad: !!R.autoDepth,
    texts: texts.map(x => x.slice(0, 80)),
  };
}"""


def b64(path):
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--page', default='dense', choices=sorted(PAGES))
    ap.add_argument('--speed', default='fast')
    ap.add_argument('--autodepth', type=int, default=-1,
                    help='0/1 — включить/выключить дожим, 2 или -1 — как в профиле')
    ap.add_argument('--twice', type=int, default=0, help='второй проход ради кэша')
    ap.add_argument('--all', action='store_true', help='все страницы × {fast,normal} × {0,1}')
    ap.add_argument('--out', default=os.path.join(ROOT, 'bench-result.json'))
    a = ap.parse_args()

    combos = []
    if a.all:
        for page in ('dense', 'prose'):
            for speed, ad in (('fast', 0), ('smart', 2), ('normal', 0), ('normal', 1)):
                combos.append((page, speed, ad))
    else:
        combos.append((a.page, a.speed, a.autodepth))

    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox', '--allow-file-access-from-files'])
        page = browser.new_page(viewport={'width': 412, 'height': 800})
        page.goto('file://' + os.path.abspath(HTML))
        page.wait_for_timeout(1200)
        for k, path in (('model:det', os.path.join(MODELS, 'koma_det.onnx')),
                        ('model:rec', os.path.join(MODELS, 'koma_rec.onnx'))):
            page.evaluate("""async ([k,b])=>{const u=Uint8Array.from(atob(b),c=>c.charCodeAt(0));
                await DB.put('kv',{k,v:u.buffer});}""", [k, b64(path)])
        page.evaluate("""async (b)=>{const u=Uint8Array.from(atob(b),c=>c.charCodeAt(0));
            await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(u)});}""", b64(DICT))
        page.evaluate("async()=>await OCR.loadModels()")
        with open(WORDS, encoding='utf-8') as f:
            page.evaluate("""(t)=>{const rank=new Map();let n=0;
                for(const l of t.split('\\n')){const w=(l.split(/\\s+/)[0]||'').toLowerCase();
                if(!w)continue;if(!rank.has(w))rank.set(w,n);n++;}
                Words.rank=rank;Words.ready=rank.size>0;}""", f.read())

        for i, (pname, speed, ad) in enumerate(combos):
            twice = 1 if (a.twice or (a.all and i == 0)) else 0
            r = page.evaluate(JS_PAGE, [b64(PAGES[pname]), speed, ad, twice])
            share = 100.0 * r['known'] / max(1, r['words'])
            r.update(page=pname, speed=speed, autoDepth=ad, dict=round(share, 1))
            results.append(r)
            line = (f"RESULT page={pname} speed={speed} autoDepth={ad} ms={r['ms']} "
                    f"calls={r['calls']} regions={r['regions']} words={r['words']} "
                    f"dict={share:.1f}")
            if r['ms2'] is not None:
                line += f" | повтор ms={r['ms2']} calls={r['calls2']} текст_тот_же={r['same']}"
            print(line, flush=True)
        browser.close()

    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print('JSON:', a.out)


if __name__ == '__main__':
    sys.exit(main())
