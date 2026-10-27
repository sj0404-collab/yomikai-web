import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
DICTS = [('250k','ru_250k.txt'), ('1.5M','d1500.txt'), ('3M','d3000.txt')]
with sync_playwright() as p:
    for label, fn in DICTS:
        br = p.chromium.launch(args=['--allow-file-access-from-files','--disable-web-security','--js-flags=--expose-gc'])
        pg = br.new_page(viewport={'width':412,'height':800})
        pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(600)
        pg.evaluate("""async ([det, rec, dict]) => {
            const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
            await DB.put('kv',{k:'model:det',v:tb(det).buffer});
            await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
            await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
            await OCR.loadModels();
        }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
               b64('/home/user/koma_models/koma_dict.txt')])
        out = pg.evaluate("""async (url) => {
            const mem = () => { if (window.gc) { gc(); gc(); } return performance.memory ? Math.round(performance.memory.usedJSHeapSize/1048576) : -1; };
            const before = mem();
            let text = await (await fetch(url)).text();
            const afterText = mem();
            await DB.put('kv', {k:'dict:ru250k', v: text});
            text = null;
            const t0 = performance.now();
            await Words.load();
            const ms = Math.round(performance.now() - t0);
            const afterMap = mem();
            return {before, afterText, afterMap, ms, size: Words.size};
        }""", 'http://127.0.0.1:8123/' + fn)
        print('[%s] до словаря %s МБ · +строка %s МБ · словарь+Map %s МБ (загрузка %s мс, слов %s)'
              % (label, out['before'], out['afterText'], out['afterMap'], out['ms'], out['size']))
        br.close()
