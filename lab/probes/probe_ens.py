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
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
            b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt')])
    for name in ['b4','b1']:
        out = pg.evaluate("""async (imgb64) => {
            const img = new Image();
            await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = 'data:image/png;base64,' + imgb64; });
            const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
            c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
            const R = RULES, W = c.width, H = c.height;
            const det = await detectWithRetry(c, R);
            const rows = [];
            const scale = (src, k) => { const o = makeCanvas(Math.round(src.width*k), Math.round(src.height*k));
                const g = o.getContext('2d'); g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
                g.drawImage(src, 0, 0, o.width, o.height); return o; };
            for (const box of det.boxes) {
              for (const ln of textLines(c, box, R)) {
                const w0 = Math.max(1, ln.right-ln.left), h0 = Math.max(1, ln.bottom-ln.top);
                const base = makeCanvas(w0, h0);
                base.getContext('2d', {willReadFrequently:true}).drawImage(c, ln.left, ln.top, w0, h0, 0, 0, w0, h0);
                const variants = {
                  'как есть': base,
                  'x1.5': scale(base, 1.5),
                  'x2': scale(base, 2),
                  'x3': scale(base, 3),
                  'контраст': contrastCanvas(base),
                  'бинаризация': binarizeCanvas(base, 0, R),
                  'контраст x2': scale(contrastCanvas(base), 2),
                  'бинаризация x2': scale(binarizeCanvas(base, 0, R), 2),
                  'инверсия': (() => { const o = makeCanvas(base.width, base.height);
                      const g = o.getContext('2d'); g.drawImage(base,0,0);
                      const d = g.getImageData(0,0,o.width,o.height);
                      for (let i=0;i<d.data.length;i+=4){ d.data[i]=255-d.data[i]; d.data[i+1]=255-d.data[i+1]; d.data[i+2]=255-d.data[i+2]; }
                      g.putImageData(d,0,0); return o; })(),
                };
                const res = [];
                for (const [k, v] of Object.entries(variants)) {
                  const t = await decodeBetter(v, R, { wide: true });
                  const txt = t[0], conf = t[1];
                  const words = (txt.match(/[А-Яа-яЁё]{2,}/g)||[]).map(x=>x.toLowerCase());
                  const known = words.filter(x => Words.inDict(x)).length;
                  res.push({ variant: k, txt, conf: +conf.toFixed(2), known, all: words.length });
                }
                rows.push(res);
              }
            }
            return rows;
        }""", b64('/tmp/%s.png' % name))
        print('=====', name)
        for r in out:
            best = sorted(r, key=lambda x: (-x['known'], -x['conf']))[0]
            print('ЛУЧШЕЕ [%s] известных %d/%d conf %.2f · %s' % (best['variant'], best['known'], best['all'], best['conf'], best['txt']))
            for x in r:
                print('   %-15s %s   (%d/%d, %.2f)' % (x['variant'], x['txt'], x['known'], x['all'], x['conf']))
            print()
    b.close()
