import base64, sys
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
crops = [('b2','/tmp/b2.png')]
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
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
            b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt')])
    for name, path in crops:
        out = pg.evaluate("""async (imgb64) => {
            const img = new Image();
            await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = 'data:image/png;base64,' + imgb64; });
            const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
            c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
            const t0 = performance.now();
            const res = await recognizePage(c, RULES, null, null);
            const t = performance.now() - t0;
            return { ms: Math.round(t), boxes: res.boxes, crops: res.crops,
                     lines: (res.regions || []).map(r => r.text),
                     big: (res.largePasses||0),
                     order: readingOrder(res.regions, true, true, RULES).map(l => l.text) };
        }""", b64(path))
        print('==', name, out['ms'], 'мс, боксов', out['boxes'], 'кропов', out['crops'], 'крупный проход', out['big'])
        print('   как распознано:', ' | '.join(out['lines']))
        print('   как читается  :', ' | '.join(out['order']))
    b.close()
