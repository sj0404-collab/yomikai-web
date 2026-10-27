import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
with sync_playwright() as p:
    b = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width':412,'height':800})
    logs=[]; pg.on('pageerror', lambda e: logs.append(str(e)[:200]))
    pg.on('console', lambda m: logs.append(m.text[:160]))
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(1200)
    pg.evaluate("""async ([det,rec,dict,txt,imgb64]) => {
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
        const blob = await (await fetch('data:image/jpeg;base64,'+imgb64)).blob();
        window.__book = await Library.addBook('Конвейер', [{name:'p1.jpg', blob}], 'images');
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
            b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt'),
            b64('/home/user/uploads/cover.jpg')])
    pg.evaluate("async () => { await Reader.open(window.__book); }")
    pg.wait_for_timeout(500)
    out = pg.evaluate("""async () => {
        const t0 = performance.now();
        const said = [];
        TTS.speakLine = (line, then) => {
            said.push({ t: Math.round(performance.now()-t0), text: line.text });
            Reader.markSpoken(Reader.page, line.text);
            setTimeout(() => { if (!TTS.stopped) then && then(); }, 60);
        };
        TTS.stopped = false; TTS.idx = 0; TTS.queue = [];
        const p = TTS.readVisible();
        await p;
        // ждём, пока конвейер отдаст всё (сканирование кончилось и очередь пуста)
        const t1 = performance.now();
        while (performance.now() - t1 < 30000) {
            if (TTS.scanDone && TTS.idx >= TTS.queue.length && State.scanning === false) {
                if (performance.now() - t1 > 1500) break;
            }
            await new Promise(r => setTimeout(r, 100));
        }
        return { said, total: Math.round(performance.now()-t0) };
    }""")
    print('первый звук: %d мс' % out['said'][0]['t'] if out['said'] else 'ничего не сказано')
    for x in out['said']: print('  %5d мс · %s' % (x['t'], x['text'][:52]))
    print('ошибки:', [l for l in logs if 'ERR' in l or 'конвейер' in l][:3])
    b.close()
