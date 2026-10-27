import base64, sys
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
HTML = sys.argv[1]
IMGS = ['/home/user/uploads/Screenshot_20261021-123537.jpg', '/home/user/uploads/Screenshot_20261021-123627.jpg']
with sync_playwright() as p:
    br = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = br.new_page(viewport={'width':412,'height':800})
    pg.goto('file://' + HTML); pg.wait_for_timeout(1000)
    pg.evaluate("""async ([det, rec, dict]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        await DB.put('kv',{k:'model:det',v:tb(det).buffer});
        await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
        await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
        await OCR.loadModels();
        await Words.load();
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
           b64('/home/user/koma_models/koma_dict.txt')])
    for img in IMGS:
        out = pg.evaluate("""async (b64img) => {
            const im = new Image(); im.src = 'data:image/jpeg;base64,' + b64img; await im.decode();
            const c = makeCanvas(im.naturalWidth, im.naturalHeight);
            c.getContext('2d',{willReadFrequently:true}).drawImage(im,0,0);
            const R = sanitizeRules(RULES);
            const res = await recognizePage(c, R, null, null);
            const lines = readingOrder(res.regions, true, true, R);
            return lines.map(l => Words.polish(l.text, R.junkRatio, l.confidence));
        }""", b64(img))
        print('=====', img.split('/')[-1], '· строк', len(out))
        for i, t in enumerate(out, 1): print('  %d. %s' % (i, t[:95]))
    br.close()
