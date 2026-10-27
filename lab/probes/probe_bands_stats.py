import base64, sys
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
HTML = sys.argv[1]
with sync_playwright() as p:
    br = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = br.new_page(viewport={'width':412,'height':800})
    pg.goto('file://' + HTML); pg.wait_for_timeout(800)
    pg.evaluate("""async ([det, rec, dict, words]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        await DB.put('kv',{k:'model:det',v:tb(det).buffer});
        await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
        await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
        await OCR.loadModels();
        const text = new TextDecoder().decode(tb(words));
        const rank = new Map(); let n = 0;
        for (const line of text.split('\\n')) { const w=(line.split(/\\s+/)[0]||'').toLowerCase();
          if(!w) continue; if(!rank.has(w)) rank.set(w,n); n++; }
        Words.rank=rank; Words.size=n; Words.ready=true; if ('ordered' in Words) Words.ordered=true;
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
           b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt')])
    out = pg.evaluate("""async (b64img) => {
        const img = new Image(); img.src = 'data:image/jpeg;base64,' + b64img; await img.decode();
        const c = makeCanvas(img.naturalWidth, img.naturalHeight);
        c.getContext('2d', {willReadFrequently:true}).drawImage(img, 0, 0);
        const viewH = 800, H = c.height, R = sanitizeRules(RULES);
        const pad = Math.min(H * R.bandOverlap, viewH * 0.25), step = viewH;
        const keys = new Map(); const t0 = performance.now();
        for (let scroll = 0; scroll < H; scroll += step) {
            const y0 = Math.max(0, scroll - pad), y1 = Math.min(H, scroll + viewH + pad);
            const key = Math.round(scroll/96) + ':' + Math.round((scroll+viewH)/96);
            if (keys.has(key)) continue;
            const res = await recognizePage(c, R, null, {y0, y1, vy0: scroll, vy1: scroll+viewH, key});
            keys.set(key, {lines: readingOrder(res.regions, true, true, R), res});
        }
        return {ms: Math.round(performance.now()-t0), stats: JSON.parse(JSON.stringify(DECODE_STATS))};
    }""", b64('/home/user/uploads/cover.jpg'))
    print('%s → %d мс · %s' % (HTML.split('/')[-1], out['ms'], {k:v for k,v in out['stats'].items() if v}))
    br.close()
