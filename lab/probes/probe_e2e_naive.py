import base64, sys, json
from playwright.sync_api import sync_playwright
DICTS = {'3M-naive': 'd3000naive.txt'}
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
IMG = '/home/user/uploads/cover.jpg'
for label, fn in DICTS.items():
    with sync_playwright() as p:
        br = p.chromium.launch(args=['--allow-file-access-from-files', '--disable-web-security'])
        pg = br.new_page(viewport={'width':412,'height':800})
        errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)[:160]))
        pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(700)
        pg.evaluate("""async ([det, rec, dict]) => {
            const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
            await DB.put('kv',{k:'model:det',v:tb(det).buffer});
            await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
            await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
            await OCR.loadModels();
        }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
               b64('/home/user/koma_models/koma_dict.txt')])
        try:
            load = pg.evaluate("""async (url) => {
                const text = await (await fetch(url)).text();
                const t0 = performance.now();
                await DB.put('kv', {k:'dict:ru250k', v: text});
                const ok = await Words.load();
                return {ok, size: Words.size, ms: Math.round(performance.now()-t0)};
            }""", 'http://127.0.0.1:8123/' + fn)
        except Exception as e:
            print('[%s] СЛОМАЛОСЬ: %s' % (label, str(e)[:120])); br.close(); continue
        try:
            out = pg.evaluate("""async (b64img) => {
                const img = new Image(); img.src = 'data:image/jpeg;base64,' + b64img; await img.decode();
                const c = makeCanvas(img.naturalWidth, img.naturalHeight);
                c.getContext('2d', {willReadFrequently:true}).drawImage(img, 0, 0);
                const viewH = 800, H = c.height, R = sanitizeRules(RULES);
                const pad = Math.min(H * R.bandOverlap, viewH * 0.25), step = viewH;
                const keys = new Map(); const t0 = performance.now(); let scans = 0;
                for (let scroll = 0; scroll < H; scroll += step) {
                    const y0 = Math.max(0, scroll - pad), y1 = Math.min(H, scroll + viewH + pad);
                    const key = Math.round(scroll/96) + ':' + Math.round((scroll+viewH)/96);
                    if (keys.has(key)) continue;
                    const res = await recognizePage(c, R, null, {y0, y1, vy0: scroll, vy1: scroll+viewH, key});
                    keys.set(key, {lines: readingOrder(res.regions, true, true, R), res});
                    scans++;
                }
                const parts = Array.from(keys.entries()).sort((a,b) => (a[1].res.band?.y0 ?? 0) - (b[1].res.band?.y0 ?? 0));
                const lines = mergeBandLines(parts.map(([,p]) => p), c);
                return {scans, boxes: parts.reduce((a,[,p])=>a+p.res.boxes,0),
                        crops: parts.reduce((a,[,p])=>a+p.res.crops,0),
                        ms: Math.round(performance.now()-t0),
                        lines: lines.map(l => l.text)};
            }""", b64(IMG))
        except Exception as e:
            print('[%s] распознавание сломалось: %s' % (label, str(e)[:120])); br.close(); continue
        txt = ' | '.join(out['lines'])
        low = txt.lower()
        print('[%s] словарь %s (%s МБ) · полос %s · %s мс' % (label, load['size'], round(load['ms']/1000), out['scans'], out['ms']))
        print('   реплик:', len(out['lines']),
              '· титул:', 'тирана' in low, '· «будучи»:', 'будучи' in low,
              '· «уже пора»:', 'уже пора' in low, '· «не уверен»:', 'не уверен' in low)
        for i, t in enumerate(out['lines'], 1):
            print('   %d. %s' % (i, t[:110]))
        if errs: print('   ошибки:', errs[:2])
        br.close()
