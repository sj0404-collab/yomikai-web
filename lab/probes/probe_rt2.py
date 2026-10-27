import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
with sync_playwright() as p:
    b = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width':412,'height':800})
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
        window.__img = await (await fetch(document.querySelector('link[rel=icon]')? '':'' )) ; // placeholder
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
            b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt')])
    # грузим картинку через canvas из data-url
    img = b64('/home/user/uploads/cover.jpg')
    out = pg.evaluate("""async (imgb64) => {
        const img = new Image();
        await new Promise((res, rej) => { img.onload = res; img.onerror = rej;
            img.src = 'data:image/jpeg;base64,' + imgb64; });
        const R = RULES;
        const res = [];
        const H = 800, W = img.width;
        for (let y = 0; y < img.height; y += H) {
            const h = Math.min(H, img.height - y);
            const c = document.createElement('canvas'); c.width = W; c.height = h;
            c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, y, W, h, 0, 0, W, h);
            const t0 = performance.now();
            const det = await detectWithRetry(c, R);
            const tDet = performance.now() - t0;
            const t1 = performance.now();
            const first = await recognizeFirstBubble(c, R, { top: 0, bottom: h / h }, det);
            const tFirst = performance.now() - t1;
            const t2 = performance.now();
            await recognizePage(c, R, null, null, det);
            const tBand = performance.now() - t2;
            res.push({ y, ms: [Math.round(tDet), Math.round(tFirst), Math.round(tBand)],
                       first: (first || '—').slice(0, 40) });
        }
        return res;
    }""", img)
    print('полоса     детектор  первая реплика  вся полоса   до первого звука   первая реплика')
    for r in out:
        print('y=%-8d %7d %13d %11d %16d   %s' % (r['y'], r['ms'][0], r['ms'][1], r['ms'][2],
              r['ms'][0] + r['ms'][1], r['first']))
    b.close()
