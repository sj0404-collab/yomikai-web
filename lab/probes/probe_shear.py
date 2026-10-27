import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
with sync_playwright() as p:
    br = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = br.new_page(viewport={'width':412,'height':800})
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(900)
    pg.evaluate("""async ([det, rec, dict]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        await DB.put('kv',{k:'model:det',v:tb(det).buffer});
        await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
        await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
        await OCR.loadModels();
        // Наклон: сдвиг строк по вертикали. tan>0 — буквы «падают» вправо.
        window.shear = (crop, tan) => {
            const extra = Math.ceil(Math.abs(tan) * crop.height);
            const out = makeCanvas(crop.width + extra, crop.height);
            const g = out.getContext('2d', {willReadFrequently:true});
            g.fillStyle = '#fff'; g.fillRect(0, 0, out.width, out.height);
            g.save();
            g.transform(1, 0, -tan, 1, tan > 0 ? extra : 0, 0);
            g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
            g.drawImage(crop, 0, 0);
            g.restore();
            return out;
        };
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
           b64('/home/user/koma_models/koma_dict.txt')])
    for name in ['b4', 'b3', 'b1']:
        rows = pg.evaluate("""async (imgb64) => {
            const img = new Image();
            await new Promise((r,j)=>{img.onload=r;img.onerror=j;img.src='data:image/png;base64,'+imgb64;});
            const c = document.createElement('canvas'); c.width=img.width; c.height=img.height;
            c.getContext('2d',{willReadFrequently:true}).drawImage(img,0,0);
            const det = await detectWithRetry(c, RULES);
            const lines=[]; for (const box of det.boxes) for (const ln of textLines(c, box, RULES)) lines.push(ln);
            const out = [];
            for (const ln of lines) {
              const crop = makeCanvas(Math.max(1,ln.right-ln.left), Math.max(1,ln.bottom-ln.top));
              crop.getContext('2d',{willReadFrequently:true})
                .drawImage(c,ln.left,ln.top,ln.right-ln.left,ln.bottom-ln.top,0,0,crop.width,crop.height);
              const variants = {};
              for (const tan of [-0.3,-0.2,-0.12,0,0.12,0.2,0.3]) {
                const t0 = performance.now();
                const [txt] = await decodeCrop(shear(crop, tan), OCR.rec);
                variants[tan] = {txt, ms: Math.round(performance.now()-t0)};
              }
              out.push(variants);
            }
            return out;
        }""", b64('/tmp/%s.png' % name))
        print('=====', name)
        for i, v in enumerate(rows):
            print('  строка %d:' % i)
            for tan, d in v.items():
                print('    tan %+0.2f: %s' % (float(tan), d['txt'][:80]))
    br.close()
