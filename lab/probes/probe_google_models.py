import base64, json
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
M = {n: b64('/home/user/koma_models/extra/%s.onnx' % n) for n in
     ['best_finetuned_r4','best_base_r3','best_r28_final','manga_cbz_final']}
CH = open('/home/user/koma_models/extra/charset.txt',encoding='utf-8').read().rstrip('\n')
with sync_playwright() as p:
    b = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = b.new_page(viewport={'width':412,'height':800})
    errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)[:200]))
    pg.goto('file:///home/user/koma-web.html'); pg.wait_for_timeout(1200)
    io = pg.evaluate("""async ([models, charset]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        await installOrtWasm();
        ort.env.wasm.numThreads = 1; ort.env.wasm.simd = true; ort.env.logLevel = 'error';
        const out = {};
        window.__s = {};
        for (const [name, data] of Object.entries(models)) {
          const sess = await ort.InferenceSession.create(tb(data).buffer, { executionProviders: ['wasm'] });
          window.__s[name] = sess;
          const t = new ort.Tensor('float32', new Float32Array(1*1*32*256), [1,1,32,256]);
          let c = '?';
          try { const r = await sess.run({ [sess.inputNames[0]]: t });
                const k = Object.keys(r)[0]; c = r[k].dims.join('x'); } catch(e) { c = 'ERR ' + e.message.slice(0,60); }
          out[name] = { inputs: sess.inputNames, outputs: sess.outputNames, outDims: c };
        }
        out.charsetLen = charset.length;
        return out;
    }""", [M, CH])
    print(json.dumps(io, ensure_ascii=False, indent=1))
    print('ошибки:', errs[:2])
    b.close()
