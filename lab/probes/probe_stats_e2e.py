import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
with sync_playwright() as p:
    br = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = br.new_page(viewport={'width':412,'height':800})
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(900)
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
        Words.rank=rank; Words.size=n; Words.ready=true; Words.ordered=true;
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
           b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt')])
    out = pg.evaluate("""async (b64img) => {
        const img = new Image(); img.src = 'data:image/jpeg;base64,' + b64img; await img.decode();
        const c = makeCanvas(img.naturalWidth, img.naturalHeight);
        c.getContext('2d', {willReadFrequently:true}).drawImage(img, 0, 0);
        const R = sanitizeRules(RULES); const t0 = performance.now();
        const res = await recognizePage(c, R, null, null);
        const tRec = Math.round(performance.now() - t0);
        return {ms: tRec, crops: res.crops, stats: JSON.parse(JSON.stringify(DECODE_STATS)),
                lines: readingOrder(res.regions, true, true, R).length};
    }""", b64('/home/user/uploads/cover.jpg'))
    print('страница: %d мс · кропов %d · строк %d' % (out['ms'], out['crops'], out['lines']))
    print('статистика перебора:', {k: v for k, v in out['stats'].items() if v})
    br.close()
