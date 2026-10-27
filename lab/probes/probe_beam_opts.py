import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
TRUTH = {'b3': 'НО РАЗВЕ НАШ ЛИДЕР УЖЕ НЕДОСТАТОЧНО ПЛОХ?',
         'b4': 'ГДЕ, ЧЁРТ ВОЗЬМИ, ТЫ БЫЛ ЧТО ТЫ МОЖЕШЬ ЗНАТЬ!'}
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
        window.__cer=(a,b)=>{const norm=(s)=>(String(s).toLowerCase().match(/[а-яё]/g)||[]).join('');
          const s=Array.from(norm(a)),t=Array.from(norm(b));
          let prev=Array.from({length:t.length+1},(_,j)=>j),cur=new Array(t.length+1);
          for(let i=1;i<=s.length;i++){cur[0]=i;
            for(let j=1;j<=t.length;j++)cur[j]=Math.min(prev[j]+1,cur[j-1]+1,prev[j-1]+(s[i-1]===t[j-1]?0:1));
            [prev,cur]=[cur,prev];}
          return +(prev[t.length]/Math.max(1,t.length)*100).toFixed(1);};
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
           b64('/home/user/koma_models/koma_dict.txt'), b64('/home/user/lab/ru_250k.txt')])
    for name, truth in TRUTH.items():
        res = pg.evaluate("""async ([imgb64, truth]) => {
            const img = new Image();
            await new Promise((r,j)=>{img.onload=r;img.onerror=j;img.src='data:image/png;base64,'+imgb64;});
            const c = document.createElement('canvas'); c.width=img.width; c.height=img.height;
            c.getContext('2d',{willReadFrequently:true}).drawImage(img,0,0);
            const R = sanitizeRules(RULES);
            const det = await detectWithRetry(c, R);
            const lines=[]; for (const box of det.boxes) for (const ln of textLines(c, box, R)) lines.push(ln);
            const probs = [];
            for (const ln of lines) {
              const crop = makeCanvas(Math.max(1,ln.right-ln.left), Math.max(1,ln.bottom-ln.top));
              crop.getContext('2d',{willReadFrequently:true})
                .drawImage(c,ln.left,ln.top,ln.right-ln.left,ln.bottom-ln.top,0,0,crop.width,crop.height);
              probs.push({plain: await recProbs(crop, null), sheared: await recProbs(shearCanvas(crop, -0.28), null)});
            }
            const out = {};
            for (const opt of [{beam:10},{beam:16},{beam:24},{beam:16,pen:1.0},{beam:16,bonus:1.6},{beam:16,wordW:0.5}]) {
              const key = JSON.stringify(opt);
              let best = [];
              let ms = 0;
              for (const pr of probs) {
                const t0 = performance.now();
                const a = beamDecode(pr.plain, opt)[0];
                const b = beamDecode(pr.sheared, opt)[0];
                ms += (performance.now() - t0) / 2;
                best.push(variantBetter(b, a) ? b : a);
              }
              out[key] = {text: best.join(' '), ms: Math.round(ms / probs.length)};
            }
            return out;
        }""", [b64('/tmp/%s.png' % name), truth])
        print('=====', name)
        for k, v in res.items():
            cer = pg.evaluate("([a,b]) => __cer(a,b)", [v['text'], truth])
            print('  %-28s CER %5.1f%% · beam %2d мс/строку · %s' % (k, cer, v['ms'], v['text'][:90]))
    br.close()
