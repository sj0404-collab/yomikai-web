import base64, json
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
TRUTH = {
 'b1': 'ЛУЧШЕ БЫТЬ БОЛЕЕ РАВНОДУШНЫМ.',
 'b2': 'Я ТОЖЕ ТАК СЧИТАЮ. ЖЕНЩИН БОЛЬШЕ ПРИВЛЕКАЮТ РАВНОДУШНЫЕ ПЛОХИЕ ПАРНИ.',
 'b3': 'НО РАЗВЕ НАШ ЛИДЕР УЖЕ НЕДОСТАТОЧНО ПЛОХ?',
 'b4': 'ГДЕ, ЧЁРТ ВОЗЬМИ, ТЫ БЫЛ ЧТО ТЫ МОЖЕШЬ ЗНАТЬ!',
}
DICTS = [('250k', '/home/user/lab/ru_250k.txt'),
         ('1,5 млн', '/home/user/lab/d1500.txt'),
         ('3 млн', '/home/user/lab/d3000.txt'),
         ('3 млн «наивно»', '/home/user/lab/d3000naive.txt')]
JS_HELPERS = r"""() => {
window.__cer = (a, b) => {
  const norm = (s) => (String(s).toLowerCase().match(/[а-яё]/g) || []).join('');
  const s = Array.from(norm(a)), t = Array.from(norm(b));
  let prev = Array.from({length: t.length+1}, (_, j) => j), cur = new Array(t.length+1);
  for (let i = 1; i <= s.length; i++) {
    cur[0] = i;
    for (let j = 1; j <= t.length; j++)
      cur[j] = Math.min(prev[j]+1, cur[j-1]+1, prev[j-1] + (s[i-1] === t[j-1] ? 0 : 1));
    [prev, cur] = [cur, prev];
  }
  return +(prev[t.length] / Math.max(1, t.length) * 100).toFixed(1);
};
window.__lines = async (imgb64) => {
  const img = new Image();
  await new Promise((r, j) => { img.onload = r; img.onerror = j; img.src = 'data:image/png;base64,' + imgb64; });
  const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
  c.getContext('2d', {willReadFrequently: true}).drawImage(img, 0, 0);
  const det = await detectWithRetry(c, RULES);
  const lines = [];
  for (const box of det.boxes) for (const ln of textLines(c, box, RULES)) lines.push(ln);
  const rows = [];
  DECODE_STATS.hardLines = 0;
  for (const ln of lines) {
    const crop = makeCanvas(Math.max(1, ln.right-ln.left), Math.max(1, ln.bottom-ln.top));
    crop.getContext('2d', {willReadFrequently: true})
      .drawImage(c, ln.left, ln.top, ln.right-ln.left, ln.bottom-ln.top, 0, 0, crop.width, crop.height);
    const base = await decodeBetter(crop, RULES, {wide: true});
    const hard = await decodeHard(crop, RULES, base);
    const raw = hard ? hard[0] : base[0];
    const polished = Words.polish(raw, RULES.junkRatio, base[1]);
    rows.push({raw, polished, variant: hard ? hard[2] : null,
               stat: lineStat(raw), junk: +Words.junkRatio(raw).toFixed(2)});
  }
  return rows;
};
}
"""
with sync_playwright() as p:
    br = p.chromium.launch(args=['--allow-file-access-from-files', '--js-flags=--expose-gc'])
    pg = br.new_page(viewport={'width':412,'height':800})
    errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)[:200]))
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(1200)
    pg.evaluate(JS_HELPERS)
    st = pg.evaluate("""async ([det, rec, dict]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        await DB.put('kv',{k:'model:det',v:tb(det).buffer});
        await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
        await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
        const ok = await OCR.loadModels();
        return {ok, engine: OCR.engine, reason: OCR.reason || '', det: !!OCR.det, rec: !!OCR.rec};
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
           b64('/home/user/koma_models/koma_dict.txt')])
    print('движок:', st)
    pages = {n: b64('/tmp/%s.png' % n) for n in TRUTH}
    for label, path in DICTS:
        info = pg.evaluate("""async (dictText) => {
            await DB.put('kv', {k:'dict:ru250k', v: dictText});
            const t0 = performance.now();
            const ok = await Words.load();
            const loadMs = Math.round(performance.now() - t0);
            const mem = performance.memory ? Math.round(performance.memory.usedJSHeapSize/1048576) : -1;
            // скорость поиска: 20 000 случайных слов из словаря
            const keys = Array.from(Words.rank.keys()).slice(0, 20000);
            const t1 = performance.now(); let hit = 0;
            for (const w of keys) if (Words.inDict(w)) hit++;
            const lookupMs = +(performance.now() - t1).toFixed(1);
            return {ok, size: Words.size, map: Words.rank.size, loadMs, mem, lookupMs, hit,
                    source: Words.source};
        }""", open(path,encoding='utf-8').read())
        print('=====', label, json.dumps(info, ensure_ascii=False))
        tot = {'raw': [], 'polished': []}
        dropped = 0
        for name in TRUTH:
            rows = pg.evaluate("__lines", pages[name])
            raw = ' '.join(r['raw'] for r in rows)
            pol = ' '.join(r['polished'] for r in rows)
            c1 = pg.evaluate("([a,b]) => __cer(a,b)", [raw, TRUTH[name]])
            c2 = pg.evaluate("([a,b]) => __cer(a,b)", [pol, TRUTH[name]])
            tot['raw'].append(c1); tot['polished'].append(c2)
            dropped += sum(1 for r in rows if not r['polished'].strip() and r['raw'].strip())
            print('  %s CER сырой %5s%%  после правки словарём %5s%%  | %s' % (name, c1, c2, pol[:95]))
        print('  строк выброшено правкой:', dropped)
        print('  ошибки:', errs[:2])
    br.close()
