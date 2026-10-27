import base64, json
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
DICTS = [('250k','ru_250k.txt'), ('1.5M','d1500.txt'), ('3M','d3000.txt')]
IMGS = ['/home/user/uploads/Screenshot_20261021-123537.jpg',
        '/home/user/uploads/Screenshot_20261021-123627.jpg',
        '/home/user/uploads/Screenshot_20261021-175046.png']
res = {}
LOOK = """async (rounds) => {
  const keys = Array.from(Words.rank.keys()).slice(0, 20000);
  const times = []; let hit = 0;
  for (let r = 0; r < rounds; r++) {
    const t = performance.now(); hit = 0;
    for (const w of keys) if (Words.inDict(w)) hit++;
    times.push(+(performance.now() - t).toFixed(1));
  }
  times.sort((a,b)=>a-b);
  // и правка реплики целиком — то, что реально делает читалка
  const sample = 'УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ, ТАК ЧТО ЕЁ ВЫСОЧЕСТВО, ДОЛЖНО БЫТЬ, ПРИБЫЛА.';
  const t2 = performance.now();
  for (let i = 0; i < 50; i++) Words.polish(sample, 0.6, 0.9);
  const polishMs = +((performance.now() - t2)/50).toFixed(2);
  return {medianLookup20kMs: times[Math.floor(times.length/2)], times, polishMs,
          hit, mem: performance.memory ? Math.round(performance.memory.usedJSHeapSize/1048576) : -1};
}"""
with sync_playwright() as p:
    br = p.chromium.launch(args=['--allow-file-access-from-files', '--disable-web-security'])
    for label, fn in DICTS:
        pg = br.new_page(viewport={'width':412,'height':800})
        pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(600)
        pg.evaluate("""async ([det, rec, dict]) => {
            const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
            await DB.put('kv',{k:'model:det',v:tb(det).buffer});
            await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
            await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
            await OCR.loadModels();
        }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
               b64('/home/user/koma_models/koma_dict.txt')])
        load = pg.evaluate("""async (url) => {
            const text = await (await fetch(url)).text();
            const t0 = performance.now();
            await DB.put('kv', {k:'dict:ru250k', v: text});
            const ok = await Words.load();
            return {ok, size: Words.size, ms: Math.round(performance.now()-t0)};
        }""", 'http://127.0.0.1:8123/' + fn)
        m = pg.evaluate(LOOK, 5)
        print('[%s] словарь %s · загрузка %s мс · поиск 20k слов: %s мс (median) %s · polish реплики %s мс · память %s МБ'
              % (label, load['size'], load['ms'], m['medianLookup20kMs'], m['times'], m['polishMs'], m['mem']))
        for img in IMGS:
            try:
                lines = pg.evaluate("""async (b64img) => {
                    const img = new Image(); img.src = 'data:image/png;base64,' + b64img;
                    if (!img.src.endsWith('.png')) img.src = 'data:image/jpeg;base64,' + b64img;
                    await img.decode();
                    const c = makeCanvas(img.naturalWidth, img.naturalHeight);
                    c.getContext('2d',{willReadFrequently:true}).drawImage(img, 0, 0);
                    const res = await recognizePage(c, sanitizeRules(RULES), null, null);
                    return readingOrder(res.regions, true, true, sanitizeRules(RULES)).map(l => l.text);
                }""", b64(img))
            except Exception as e:
                print('   %s — сломалось: %s' % (img.split('/')[-1], str(e)[:80])); continue
            res.setdefault(img, {})[label] = lines
        pg.close()
    br.close()
for img, per in res.items():
    print('=====', img.split('/')[-1])
    base = per.get('250k', [])
    for label in ['250k','1.5M','3M']:
        print('  %-5s реплик %d' % (label, len(per.get(label,[]))))
    for i in range(max(len(v) for v in per.values())):
        a = base[i] if i < len(base) else '—'
        b = per['3M'][i] if i < len(per.get('3M',[])) else '—'
        same = 'совпало' if a == b else 'РАЗНИЦА'
        print('   %d. %s' % (i+1, a[:88]))
        if a != b: print('      3M: %s   ← %s' % (b[:88], same))
