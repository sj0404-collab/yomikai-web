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
    print(pg.evaluate("""async (imgb64) => {
        const img = new Image();
        await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = 'data:image/png;base64,' + imgb64; });
        const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
        c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
        const R = RULES;
        const det = await detectWithRetry(c, R);
        const info = [];
        const all = [];
        for (const box of det.boxes) {
            const lines = textLines(c, box, R);
            const items = [];
            for (const ln of lines) {
                const crop = makeCanvas(Math.max(1, ln.right-ln.left), Math.max(1, ln.bottom-ln.top));
                crop.getContext('2d').drawImage(c, ln.left, ln.top, ln.right-ln.left, ln.bottom-ln.top, 0, 0, crop.width, crop.height);
                const [t, conf] = await decodeBetter(crop, R, { wide: true });
                items.push({t, conf: +conf.toFixed(2)});
                all.push({t, conf, ln, box, crop});
            }
            const own = items.map(i => 1);
            info.push({ boxH: Math.round(box.bottom-box.top), boxWpx: Math.round(box.right-box.left),
                        boxW: +((box.right-box.left)/c.width).toFixed(2), items });
        }
        // крупный проход по первому боксу
        let large = null;
        if (det.boxes.length) {
            const alt = await recognizeLargeBox(c, det.boxes[0], R, { visible: () => true, y0: 0, pageH: c.height, W: c.width });
            large = { items: alt.items.map(i=>i.text), crops: alt.crops };
        }
        // перебор масштаба на первой строке
        const scales = [];
        const first = all[0];
        for (const k of [1.5, 2, 3]) {
            const up = makeCanvas(Math.round(first.crop.width*k), Math.round(first.crop.height*k));
            const g = up.getContext('2d'); g.imageSmoothingQuality='high';
            g.drawImage(first.crop, 0, 0, up.width, up.height);
            const [t, conf] = await decodeBetter(up, R, { wide: true });
            scales.push({k, t, conf: +conf.toFixed(2)});
        }
        return { boxes: info, large, scales, pageMedian: medianLineHeight([]) };
    }""", b64('/tmp/b4.png')))
    b.close()
