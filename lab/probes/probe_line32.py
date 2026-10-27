import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
CH = open('/home/user/koma_models/extra/charset.txt',encoding='utf-8').read().rstrip('\n')
with sync_playwright() as p:
    b = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width':412,'height':800})
    errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)[:200]))
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(1200)
    # Файлы кладём через ту же функцию, что вызывает шторка моделей: проверяем
    # разбор имён (best_r28_final.onnx + charset.txt) и определение вида.
    kind = pg.evaluate("""async ([det, rec, r28, charset]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        const mk=(name,bytes,type)=>new File([bytes], name, {type: type||'application/octet-stream'});
        await storeModelFiles([
          mk('detection.onnx', tb(det)),
          mk('cyrillic.onnx', tb(rec)),
          mk('cyrillic.txt', new TextEncoder().encode('слово\\n'), 'text/plain'),
          mk('best_r28_final.onnx', tb(r28)),
          mk('charset.txt', new TextEncoder().encode(charset), 'text/plain'),
        ]);
        await OCR.loadModels();
        return {kind: OCR.rec2Kind, note: OCR.rec2Note, has: !!OCR.rec2,
                charsetLen: OCR.rec2Charset.length, engine: OCR.engine,
                det: !!OCR.det, rec: !!OCR.rec};
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
           b64('/home/user/koma_models/extra/best_r28_final.onnx'), CH])
    print('после выбора файлов:', kind)
    out=[]
    for name in ['b1','b2','b3','b4']:
        r = pg.evaluate("""async (imgb64) => {
            const img = new Image();
            await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src='data:image/png;base64,'+imgb64; });
            const c = document.createElement('canvas'); c.width=img.width; c.height=img.height;
            c.getContext('2d',{willReadFrequently:true}).drawImage(img,0,0);
            const det = await detectWithRetry(c, RULES);
            const lines=[]; for (const box of det.boxes) for (const ln of textLines(c, box, RULES)) lines.push(ln);
            const rows=[];
            for (const ln of lines) {
              const crop = makeCanvas(Math.max(1,ln.right-ln.left), Math.max(1,ln.bottom-ln.top));
              crop.getContext('2d',{willReadFrequently:true})
                .drawImage(c,ln.left,ln.top,ln.right-ln.left,ln.bottom-ln.top,0,0,crop.width,crop.height);
              const ours = (await decodeBetter(crop, RULES, {wide:true}))[0];
              const t0=performance.now();
              const [t2] = await decodeLine32(crop, OCR.rec2, OCR.rec2Charset, RULES);
              rows.push({ours, second:t2, ms: Math.round(performance.now()-t0)});
            }
            return rows;
        }""", b64('/tmp/%s.png' % name))
        out.append((name, r))
    for name,r in out:
        print('=====', name, '· строк', len(r), '· мс второй:', [x['ms'] for x in r])
        for x in r:
            print('   наш   :', x['ours'][:100])
            print('   второй:', x['second'][:100])
    print('ошибки:', errs[:3])
    b.close()
