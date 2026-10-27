import base64, json
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
MODELS = {n: b64('/home/user/koma_models/extra/%s.onnx' % n) for n in
          ['best_finetuned_r4','best_base_r3','best_r28_final']}
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
    errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)[:160]))
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(1200)
    # наши модели OCR (детектор + наш распознаватель) — для сравнения
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
    pg.evaluate("""async ([models, charset]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        window.__s = {};
        for (const [name, data] of Object.entries(models))
          window.__s[name] = await ort.InferenceSession.create(tb(data).buffer, { executionProviders: ['wasm'] });
        window.__charset = charset;

        // Линейный распознаватель «чтеца шрифтов»: серый 32 px, поля 20 %, luma/255.
        window.decode32 = async (crop, sess, margin) => {
          const m = Math.max(2, Math.round(crop.height * (margin ?? 0.2)));
          const pad = makeCanvas(crop.width + 2*m, crop.height + 2*m);
          const pg2 = pad.getContext('2d', { willReadFrequently: true });
          pg2.fillStyle = '#fff'; pg2.fillRect(0, 0, pad.width, pad.height);
          pg2.drawImage(crop, m, m);
          const h = 32;
          const w32 = Math.max(8, Math.round(pad.width * h / pad.height));
          const W = Math.ceil((w32 + 4) / 8) * 8;
          const c = makeCanvas(W, h);
          const g = c.getContext('2d', { willReadFrequently: true });
          g.fillStyle = '#fff'; g.fillRect(0, 0, W, h);
          g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
          g.drawImage(pad, 4, 0, w32, h);
          const px = g.getImageData(0, 0, W, h).data;
          const data = new Float32Array(h * W);
          for (let i = 0; i < h * W; i++) {
            const o = i * 4;
            data[i] = (0.299*px[o] + 0.587*px[o+1] + 0.114*px[o+2]) / 255;
          }
          const t = new ort.Tensor('float32', data, [1, 1, h, W]);
          const out = await runModel(sess, { [sess.inputNames[0]]: t }, 'чтец');
          const d = out.dims, v = out.data;
          let T = 0, C = 0, stride = 0, at = null;
          if (d.length === 3 && d[2] > 10) { T = d[1]; C = d[2]; at = (ti, ci) => ti * C + ci; }
          else if (d.length === 3 && d[1] > 10) { T = d[0]; C = d[1]; at = (ti, ci) => ti * C + ci; }
          else return ['?', 0];
          const chars = window.__charset;
          let text = '', prev = 0, score = 0, cnt = 0;
          for (let ti = 0; ti < T; ti++) {
            let best = 0, bv = v[at(ti, 0)];
            for (let ci = 1; ci < C; ci++) { const x = v[at(ti, ci)]; if (x > bv) { bv = x; best = ci; } }
            if (best !== 0 && best !== prev) {
              if (best < chars.length) text += chars[best];
              else if (best === chars.length + 1) text += '¤';          // unknown
              else if (best >= chars.length + 2) {                        // латиница
                const k = best - chars.length - 2;
                text += k < 26 ? String.fromCharCode(65 + k) : String.fromCharCode(97 + (k - 26));
              }
              score += bv; cnt++;
            }
            prev = best;
          }
          return [text, cnt ? score / cnt : 0];
        };
    }""", [MODELS, CH])

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
            const rows = [];
            for (const ln of lines) {
              const crop = makeCanvas(Math.max(1, ln.right-ln.left), Math.max(1, ln.bottom-ln.top));
              crop.getContext('2d', { willReadFrequently: true })
                .drawImage(c, ln.left, ln.top, ln.right-ln.left, ln.bottom-ln.top, 0, 0, crop.width, crop.height);
              const row = { ours: (await decodeBetter(crop, R, { wide: true }))[0] };
              for (const m of ['best_finetuned_r4','best_base_r3','best_r28_final']) {
                const t0 = performance.now();
                row[m] = (await decode32(crop, window.__s[m], 0.2))[0];
                row[m + '_ms'] = Math.round(performance.now() - t0);
              }
              rows.push(row);
            }
            // CER по всей склейке (буквы, нижний регистр)
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
            const res = {};
            for (const key of ['ours','best_finetuned_r4','best_base_r3','best_r28_final']) {
              const got = rows.map(r => r[key]).join(' ');
              const d = lev(norm(got), norm(truth));
              res[key] = { text: got, cer: +(d / Math.max(1, norm(truth).length) * 100).toFixed(1) };
            }
            res.ms = { ft: rows.map(r=>r.best_finetuned_r4_ms), r28: rows.map(r=>r.best_r28_final_ms) };
            res.lines = rows.length;
            return res;
        }""", [b64('/tmp/%s.png' % name), TRUTH[name]])
        print('=====', name, '· строк', out['lines'], '· мс на строку (ft/r28):',
              out['ms']['ft'], out['ms']['r28'])
        for k in ['ours','best_finetuned_r4','best_base_r3','best_r28_final']:
            print('  %-18s CER %5s%%  %s' % (k, out[k]['cer'], out[k]['text'][:110]))
    print('ошибки:', errs[:2])
    b.close()
