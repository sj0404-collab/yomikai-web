import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
with sync_playwright() as p:
    b = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width':412,'height':800})
    errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)[:200]))
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(1200)
    pg.evaluate("""async ([det,rec,dict,txt]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        await DB.put('kv',{k:'model:det',v:tb(det).buffer});
        await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
        await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
        await OCR.loadModels();
        const rank=new Map(); let n=0;
        for (const line of new TextDecoder().decode(tb(txt)).split('\\n')) {
            const w=(line.split(/\\s+/)[0]||'').toLowerCase(); if(!w) continue;
            if(!rank.has(w)) rank.set(w,n); n++; }
        Words.rank=rank; Words.size=n; Words.ready=true;
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
            b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt')])
    for name in ['b4','b1','b2']:
        out = pg.evaluate("""async (imgb64) => {
            const img = new Image();
            await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = 'data:image/png;base64,' + imgb64; });
            const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
            c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
            const R = RULES;
            const t0 = performance.now();
            const res = await recognizePage(c, R, null, null);
            const ms = Math.round(performance.now() - t0);
            const order = readingOrder(res.regions, true, true, RULES).map(l => l.text);
            return { ms, crops: res.crops, variants: DECODE_STATS.variantRuns,
                     picked: DECODE_STATS.variantsPicked, rec2: DECODE_STATS.rec2Picked || 0,
                     order, rec2note: OCR.rec2Note, hardOn: RULES.hardVariants };
        }""", b64('/tmp/%s.png' % name))
        print('==', name, out['ms'], 'мс · кропов', out['crops'], '· вариантов', out['variants'],
              '· выбран вариант', out['picked'], '· hardVariants', out['hardOn'])
        for t in out['order']: print('   ', t)
    print('ошибки:', errs[:2])
    b.close()
