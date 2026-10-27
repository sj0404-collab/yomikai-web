import base64, json, os
import numpy as np
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
TRUTH = {
 'b1': 'ЛУЧШЕ БЫТЬ БОЛЕЕ РАВНОДУШНЫМ.',
 'b2': 'Я ТОЖЕ ТАК СЧИТАЮ. ЖЕНЩИН БОЛЬШЕ ПРИВЛЕКАЮТ РАВНОДУШНЫЕ ПЛОХИЕ ПАРНИ.',
 'b3': 'НО РАЗВЕ НАШ ЛИДЕР УЖЕ НЕДОСТАТОЧНО ПЛОХ?',
 'b4': 'ГДЕ, ЧЁРТ ВОЗЬМИ, ТЫ БЫЛ ЧТО ТЫ МОЖЕШЬ ЗНАТЬ!',
}
with sync_playwright() as p:
    br = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = br.new_page(viewport={'width':412,'height':800})
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(900)
    info = pg.evaluate("""async ([det, rec, dict]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        await DB.put('kv',{k:'model:det',v:tb(det).buffer});
        await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
        await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
        await OCR.loadModels();
        // где в азбуке кириллица
        const idx = {}; for (let i=0;i<OCR.dict.length;i++){ const c=OCR.dict[i]; if (/[А-Яа-яЁё]/.test(c)) idx[c]=i; }
        return {dict: OCR.dict, len: OCR.dict.length, cyr: idx,
                recOut: OCR.rec.outputNames, det: OCR.engine};
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
           b64('/home/user/koma_models/koma_dict.txt')])
    json.dump(info, open('/home/user/lab/logits/dict.json','w',encoding='utf-8'), ensure_ascii=False)
    print('азбука', info['len'], '· кириллица с', min(info['cyr'].values()), '· движок', info['det'])
    for name in TRUTH:
        out = pg.evaluate("""async (imgb64) => {
            const img = new Image();
            await new Promise((r,j)=>{img.onload=r;img.onerror=j;img.src='data:image/png;base64,'+imgb64;});
            const c = document.createElement('canvas'); c.width=img.width; c.height=img.height;
            c.getContext('2d',{willReadFrequently:true}).drawImage(img,0,0);
            const det = await detectWithRetry(c, RULES);
            const lines=[]; for (const box of det.boxes) for (const ln of textLines(c, box, RULES)) lines.push(ln);
            const res=[];
            for (const ln of lines) {
              const crop = makeCanvas(Math.max(1,ln.right-ln.left), Math.max(1,ln.bottom-ln.top));
              crop.getContext('2d',{willReadFrequently:true})
                .drawImage(c,ln.left,ln.top,ln.right-ln.left,ln.bottom-ln.top,0,0,crop.width,crop.height);
              let w0=crop.width, h0=crop.height, src=crop;
              if (h0 > w0*1.8) { const rot=makeCanvas(h0,w0); const rc=rot.getContext('2d',{willReadFrequently:true});
                rc.translate(rot.width/2, rot.height/2); rc.rotate(Math.PI/2); rc.drawImage(crop,-w0/2,-h0/2); src=rot; w0=rot.width; h0=rot.height; }
              const width = clamp(Math.round(48*w0/h0), 8, 960), padded = Math.max(320, width);
              const cc = makeCanvas(padded, 48); const ctx = cc.getContext('2d',{willReadFrequently:true});
              ctx.imageSmoothingEnabled=true; ctx.imageSmoothingQuality='high';
              ctx.drawImage(src, 0, 0, width, 48);
              const px = ctx.getImageData(0,0,width,48).data;
              const data = new Float32Array(3*48*padded);
              for (let ch=0; ch<3; ch++) { const off=ch*48*padded;
                for (let y=0;y<48;y++) for (let x=0;x<width;x++)
                  data[off+y*padded+x] = ((px[(y*width+x)*4+ch]/255)-0.5)/0.5; }
              const t = new ort.Tensor('float32', data, [1,3,48,padded]);
              const logits = await runModel(OCR.rec, {[OCR.rec.inputNames[0]]: t}, 'rec');
              const T = logits.dims[1], C = logits.dims[2];
              const arr = Array.from(logits.data);
              const png = crop.toDataURL ? crop.toDataURL('image/png') : '';
              res.push({T, C, w0, h0, width, logits: arr, png,
                        greedy: (await decodeCrop(crop, OCR.rec))[0]});
            }
            return res;
        }""", b64('/tmp/%s.png' % name))
        rec = {'truth': TRUTH[name], 'lines': []}
        for r in out:
            a = np.array(r['logits'], dtype=np.float32).reshape(r['T'], r['C'])
            np.save('/home/user/lab/logits/%s_%d.npy' % (name, len(rec['lines'])), a)
            png = r.pop('png'); r.pop('logits')
            if png.startswith('data:image/png;base64,'):
                open('/home/user/lab/logits/%s_%d.png' % (name, len(rec['lines'])),'wb').write(
                    base64.b64decode(png.split(',',1)[1]))
            r['greedy'] = r['greedy']
            rec['lines'].append(r)
            print('  %s[%d] T=%d C=%d %dx%d greedy=«%s»' % (name, len(rec['lines'])-1, r['T'], r['C'], r['w0'], r['h0'], r['greedy'][:60]))
        json.dump(rec, open('/home/user/lab/logits/%s.json' % name,'w',encoding='utf-8'), ensure_ascii=False)
    br.close()
