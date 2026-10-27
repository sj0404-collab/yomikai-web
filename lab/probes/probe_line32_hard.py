import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
CH = open('/home/user/koma_models/extra/charset.txt',encoding='utf-8').read().rstrip('\n')
TRUTH = {
 'b1': 'ЛУЧШЕ БЫТЬ БОЛЕЕ РАВНОДУШНЫМ.',
 'b2': 'Я ТОЖЕ ТАК СЧИТАЮ. ЖЕНЩИН БОЛЬШЕ ПРИВЛЕКАЮТ РАВНОДУШНЫЕ ПЛОХИЕ ПАРНИ.',
 'b3': 'НО РАЗВЕ НАШ ЛИДЕР УЖЕ НЕДОСТАТОЧНО ПЛОХ?',
 'b4': 'ГДЕ, ЧЁРТ ВОЗЬМИ, ТЫ БЫЛ ЧТО ТЫ МОЖЕШЬ ЗНАТЬ!',
}
with sync_playwright() as p:
    b = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width':412,'height':800})
    errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)[:200]))
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(1200)
    info = pg.evaluate("""async ([det, rec, dict, txt, r28, charset]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        const mk=(n,by,t)=>new File([by],n,{type:t||'application/octet-stream'});
        await storeModelFiles([mk('detection.onnx',tb(det)), mk('cyrillic.onnx',tb(rec)),
          mk('cyrillic.txt', new Uint8Array(tb(dict)), 'text/plain'),
          mk('best_r28_final.onnx', tb(r28)),
          mk('charset.txt', new TextEncoder().encode(charset), 'text/plain')]);
        await OCR.loadModels();
        // словарь рангов — как в рабочей сборке
        const rank=new Map(); let n=0;
        for (const line of new TextDecoder().decode(tb(txt)).split('\\n')) {
          const w=(line.split(/\\s+/)[0]||'').toLowerCase(); if(!w) continue;
          if(!rank.has(w)) rank.set(w,n); n++;
        }
        Words.rank=rank; Words.size=n; Words.ready=true;
        return {engine: OCR.engine, kind: OCR.rec2Kind, dict: Words.size};
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
           b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt'),
           b64('/home/user/koma_models/extra/best_r28_final.onnx'), CH])
    print('движок:', info)
    tot = {}
    for name in ['b1','b2','b3','b4']:
        rows = pg.evaluate("""async (imgb64) => {
            const img=new Image();
            await new Promise((r,j)=>{img.onload=r;img.onerror=j;img.src='data:image/png;base64,'+imgb64;});
            const c=document.createElement('canvas'); c.width=img.width; c.height=img.height;
            c.getContext('2d',{willReadFrequently:true}).drawImage(img,0,0);
            const det=await detectWithRetry(c, RULES);
            const lines=[]; for (const box of det.boxes) for (const ln of textLines(c,box,RULES)) lines.push(ln);
            DECODE_STATS.hardLines = 0;
            const out=[];
            for (const ln of lines) {
              const crop=makeCanvas(Math.max(1,ln.right-ln.left), Math.max(1,ln.bottom-ln.top));
              crop.getContext('2d',{willReadFrequently:true})
                .drawImage(c,ln.left,ln.top,ln.right-ln.left,ln.bottom-ln.top,0,0,crop.width,crop.height);
              const base = await decodeBetter(crop, RULES, {wide:true});
              const t0=performance.now();
              const hard = await decodeHard(crop, RULES, base);
              out.push({base: base[0], hard: hard ? hard[0] : null, variant: hard ? hard[2] : null,
                        ms: Math.round(performance.now()-t0)});
            }
            return {rows: out, stats: {hard: DECODE_STATS.hardLines, picked: DECODE_STATS.variantsPicked, rec2: DECODE_STATS.rec2Picked}};
        }""", b64('/tmp/%s.png' % name))
        print('=====', name, '· перебор:', rows['stats'])
        for r in rows['rows']:
            flag = '' if r['hard'] is None else ('  ← ' + r['variant'])
            print('   %-40s | %s%s' % (r['base'][:40], (r['hard'] or '')[:60], flag))
        tot[name]=rows
    print('ошибки:', errs[:3])
    b.close()
