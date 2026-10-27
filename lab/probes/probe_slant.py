import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
with sync_playwright() as p:
    br = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = br.new_page(viewport={'width':412,'height':800})
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(900)
    pg.evaluate("""async ([det, rec, dict, words]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        await DB.put('kv',{k:'model:det',v:tb(det).buffer});
        await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
        await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
        await OCR.loadModels();
        const text = new TextDecoder().decode(tb(words));
        const rank = new Map(); let n = 0;
        for (const line of text.split('\\n')) { const w=(line.split(/\\s+/)[0]||'').toLowerCase();
          if(!w) continue; if(!rank.has(w)) rank.set(w,n); n++; }
        Words.rank=rank; Words.size=n; Words.ready=true; Words.ordered=true;
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
           b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt')])
    for name in ['b4','b3','b1']:
        out = pg.evaluate("""async (imgb64) => {
            const img = new Image();
            await new Promise((r,j)=>{img.onload=r;img.onerror=j;img.src='data:image/png;base64,'+imgb64;});
            const c = document.createElement('canvas'); c.width=img.width; c.height=img.height;
            c.getContext('2d',{willReadFrequently:true}).drawImage(img,0,0);
            const R = sanitizeRules(RULES);
            const det = await detectWithRetry(c, R);
            const lines=[]; for (const box of det.boxes) for (const ln of textLines(c, box, R)) lines.push(ln);
            const rows=[];
            for (const ln of lines) {
              const crop = makeCanvas(Math.max(1,ln.right-ln.left), Math.max(1,ln.bottom-ln.top));
              crop.getContext('2d',{willReadFrequently:true})
                .drawImage(c,ln.left,ln.top,ln.right-ln.left,ln.bottom-ln.top,0,0,crop.width,crop.height);
              const tan = estimateSlant(crop, R);
              const base = (await decodeBetter(crop, R, {}))[0];
              const orig = beamDecode(await recProbs(crop, null))[0];
              const sh = beamDecode(await recProbs(shearCanvas(crop, tan), null))[0];
              rows.push({tan, base, orig, sh, statOrig: lineStat(orig), statSh: lineStat(sh)});
            }
            return rows;
        }""", b64('/tmp/%s.png' % name))
        print('=====', name)
        for i, r in enumerate(out):
            print('  строка %d · наклон %+0.2f' % (i, r['tan']))
            print('     база:        %s' % r['base'][:70])
            print('     beam:        %s   %s' % (r['orig'][:70], r['statOrig']))
            print('     beam+наклон: %s   %s' % (r['sh'][:70], r['statSh']))
    br.close()
