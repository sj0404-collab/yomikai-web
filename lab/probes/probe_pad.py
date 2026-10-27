import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
TRUTH = {
 'b1': 'ЛУЧШЕ БЫТЬ БОЛЕЕ РАВНОДУШНЫМ.',
 'b2': 'Я ТОЖЕ ТАК СЧИТАЮ. ЖЕНЩИН БОЛЬШЕ ПРИВЛЕКАЮТ РАВНОДУШНЫЕ ПЛОХИЕ ПАРНИ.',
 'b3': 'НО РАЗВЕ НАШ ЛИДЕР УЖЕ НЕДОСТАТОЧНО ПЛОХ?',
 'b4': 'ГДЕ, ЧЁРТ ВОЗЬМИ, ТЫ БЫЛ ЧТО ТЫ МОЖЕШЬ ЗНАТЬ!',
}
with sync_playwright() as p:
    b = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width':412,'height':800})
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(1200)
    pg.evaluate("""async ([det,rec,dict]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        await DB.put('kv',{k:'model:det',v:tb(det).buffer});
        await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
        await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
        await OCR.loadModels();
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
            b64('/home/user/koma_models/koma_dict.txt')])
    for name in ['b1','b2','b3','b4']:
        out = pg.evaluate("""async ([imgb64, truth]) => {
            const img = new Image();
            await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = 'data:image/png;base64,' + imgb64; });
            const c = document.createElement('canvas'); c.width = img.width; c.height = img.height;
            c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
            const R = RULES;
            const det = await detectWithRetry(c, R);
            const lines = [];
            for (const box of det.boxes) for (const ln of textLines(c, box, R)) lines.push(ln);
            const norm = (s) => (String(s).toLowerCase().match(/[а-яё]/g) || []).join('');
            const lev = (a, b) => {
              const s = Array.from(a), t = Array.from(b);
              let prev = Array.from({length: t.length+1}, (_, j) => j), cur = new Array(t.length+1);
              for (let i = 1; i <= s.length; i++) {
                cur[0] = i;
                for (let j = 1; j <= t.length; j++)
                  cur[j] = Math.min(prev[j]+1, cur[j-1]+1, prev[j-1] + (s[i-1] === t[j-1] ? 0 : 1));
                [prev, cur] = [cur, prev];
              }
              return prev[t.length];
            };
            const margins = [0, 0.1, 0.15, 0.2, 0.3, 0.4];
            const res = {};
            let msTotal = 0, calls = 0;
            for (const m of margins) {
              const texts = [];
              for (const ln of lines) {
                const crop = makeCanvas(Math.max(1, ln.right-ln.left), Math.max(1, ln.bottom-ln.top));
                crop.getContext('2d', { willReadFrequently: true })
                  .drawImage(c, ln.left, ln.top, ln.right-ln.left, ln.bottom-ln.top, 0, 0, crop.width, crop.height);
                const padded = m > 0 ? padCanvas(crop, m) : crop;
                const t0 = performance.now();
                const [txt] = await decodeCrop(padded);
                msTotal += performance.now() - t0; calls++;
                texts.push(txt);
              }
              res[m] = { cer: +(lev(norm(texts.join(' ')), norm(truth)) / Math.max(1, norm(truth).length) * 100).toFixed(1),
                         text: texts.join(' ') };
            }
            res.msPerLine = Math.round(msTotal / Math.max(1, calls));
            return res;
        }""", [b64('/tmp/%s.png' % name), TRUTH[name]])
        print('=====', name, '· наш распознаватель, мс на строку', out['msPerLine'])
        for m in ['0','0.1','0.15','0.2','0.3','0.4']:
            print('  поля %-5s CER %5s%%  %s' % (m, out[m]['cer'], out[m]['text'][:100]))
    b.close()
