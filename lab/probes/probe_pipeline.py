import base64, json
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
    out = pg.evaluate("""async (b64img) => {
        const img=new Image(); img.src='data:image/jpeg;base64,'+b64img; await img.decode();
        const c=makeCanvas(img.naturalWidth,img.naturalHeight);
        c.getContext('2d',{willReadFrequently:true}).drawImage(img,0,0);
        const R=sanitizeRules(RULES);
        const H=c.height, viewH=800;
        const res=[];
        for (let scroll=0; scroll<H; scroll+=viewH) {
          const y0=scroll, y1=Math.min(H,scroll+viewH);
          const band=makeCanvas(c.width, y1-y0);
          band.getContext('2d',{willReadFrequently:true}).drawImage(c,0,y0,c.width,y1-y0,0,0,c.width,y1-y0);
          // 1) только детектор
          const t0=performance.now();
          const det=await detectWithRetry(band, R);
          const detMs=performance.now()-t0;
          // 2) первая реплика целиком (первая строка первого бокса)
          const t1=performance.now();
          let firstLine=null, firstMs=0, firstText='';
          const boxes=det.boxes.slice().sort((a,b)=>a.top-b.top);
          if (boxes.length) {
            const lines=textLines(band, boxes[0], R);
            if (lines.length) {
              const ln=lines[0];
              const crop=makeCanvas(Math.max(1,ln.right-ln.left), Math.max(1,ln.bottom-ln.top));
              crop.getContext('2d',{willReadFrequently:true}).drawImage(band,ln.left,ln.top,ln.right-ln.left,ln.bottom-ln.top,0,0,crop.width,crop.height);
              const [t] = await decodeBetter(crop, R, {wide:true});
              firstText=t; firstMs=performance.now()-t1;
            }
          }
          // 3) вся полоса как сейчас
          const t2=performance.now();
          await recognizePage(c, R, null, {y0, y1, vy0:scroll, vy1:scroll+viewH, key:'k'+scroll});
          const bandMs=performance.now()-t2;
          res.push({scroll, boxes:det.boxes.length, detMs:Math.round(detMs),
                    firstMs:Math.round(firstMs), first:firstText.slice(0,30), bandMs:Math.round(bandMs)});
        }
        return res;
    }""", b64('/home/user/uploads/cover.jpg'))
    print('полоса  боксов  детектор  первая реплика  вся полоса  (мс)')
    for r in out:
        print('y=%4d  %3d   %5d        %5d        %5d   · первая: %s' % (
            r['scroll'], r['boxes'], r['detMs'], r['firstMs'], r['bandMs'], r['first']))
    d=[r['detMs'] for r in out]; f=[r['firstMs'] for r in out]; t=[r['bandMs'] for r in out]
    print('\nсреднее: детектор %d мс · первая реплика %d мс · вся полоса %d мс' % (sum(d)/len(d), sum(f)/len(f), sum(t)/len(t)))
    print('до первого звука сейчас (вся полоса): %d мс' % (sum(t)/len(t)))
    print('до первого звука с конвейером (детектор + первая реплика): %d мс' % (sum(d)/len(d)+sum(f)/len(f)))
    b.close()
