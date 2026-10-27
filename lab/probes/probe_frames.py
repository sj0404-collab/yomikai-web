import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
with sync_playwright() as p:
    b = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width':412,'height':800}, device_scale_factor=2)
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(1500)
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
        window.__book = await Library.addBook('Рамки', [{name:'p1.jpg', blob}], 'images');
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
            b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt'),
            b64('/home/user/uploads/cover.jpg')])
    pg.evaluate("async () => { await Reader.open(window.__book); }")
    pg.wait_for_timeout(600)
    # распознаём как человек: кнопкой в карточке старта
    pg.click('#btnStartScan'); pg.wait_for_timeout(9000)
    st = pg.evaluate("""() => ({
        lines: (Reader.regions.get(0)||{lines:[]}).lines.length,
        frames: document.querySelectorAll('#strip .frame').length,
        spoken: Reader.spoken.size,
    })""")
    print('после распознавания:', st)
    # «читаем»: подменяем голос мгновенным, отмечаем как настоящий onstart
    pg.evaluate("""() => {
        TTS.speakLine = (line, then) => {
            Reader.markSpoken(Reader.page, line.text);
            setTimeout(() => { if (!TTS.stopped) then && then(); }, 40);
        };
        TTS.stopped = false; TTS.idx = 0; TTS.queue = [];
        TTS.readVisible();
    }""")
    pg.wait_for_timeout(3000)
    pg.evaluate("() => { TTS.stop(); Reader.frames = true; Reader.paintAllFrames(); }")
    pg.wait_for_timeout(500)
    st2 = pg.evaluate("""() => ({
        lines: (Reader.regions.get(0)||{lines:[]}).lines.length,
        frames: document.querySelectorAll('#strip .frame').length,
        done: document.querySelectorAll('#strip .frame.done').length,
        cur: document.querySelectorAll('#strip .frame.cur').length,
        spoken: Reader.spoken.size,
    })""")
    print('после чтения и включения рамок:', st2)
    pg.screenshot(path='/home/user/koma-bench/shot-frames.png')
    # шторка «Текст страницы»: все ли строки видны и помечены
    pg.evaluate("() => { Reader.page = 0; renderTextSheet(0); openSheet('sheetText'); }")
    pg.wait_for_timeout(600)
    sheet = pg.evaluate("""() => ({
        items: document.querySelectorAll('#textOrdered .lineitem').length,
        doneMarks: document.querySelectorAll('#textOrdered .done').length,
        first: (document.querySelector('#textOrdered .lineitem')||{}).textContent,
    })""")
    print('в «Тексте страницы»:', sheet)
    pg.screenshot(path='/home/user/koma-bench/shot-textsheet.png')
    b.close()
