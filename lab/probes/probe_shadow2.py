import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
with sync_playwright() as p:
    b = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width':412,'height':800})
    errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)[:160]))
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
        window.__book = await Library.addBook('Тень', [{name:'p1.jpg', blob}], 'images');
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
            b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt'),
            b64('/home/user/uploads/cover.jpg')])
    pg.evaluate("async () => { await Reader.open(window.__book); }")
    pg.wait_for_timeout(600)
    pg.evaluate("""async () => {
        // Распознаём первую полосу, чтобы были рамки, и показываем плеер.
        await Reader.scanCurrent(false);
        $('#playBar').style.display = 'flex';
        Reader.current = { text: Reader.regions.get(0)?.lines?.[1]?.text || '', top: 0, bottom: 0 };
        Reader.paintAllFrames();
        SpeakCursor.start(Reader.current.text, 1.0);
        await new Promise(r => setTimeout(r, 2600));
        document.querySelectorAll('.toast').forEach(e => e.remove());
    }""")
    pg.screenshot(path='/home/user/koma-bench/shot-shadow-ok.png')
    n = pg.evaluate("""() => ({sc: $('#nowLine').scrollTop, sh: $('#nowLine').scrollHeight,
                                ch: $('#nowLine').clientHeight,
                                sp: document.querySelectorAll('#nowLine .ch.sp').length,
                                cur: document.querySelectorAll('#nowLine .ch.cur').length,
                                txt: (document.querySelector('#nowLine .ch.cur')||{}).textContent||''})""")
    print('подсвечено:', n, 'ошибки:', errs[:2])
    b.close()
