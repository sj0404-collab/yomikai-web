import base64, sys, time
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
TRUTH = {
 'b1': 'ЛУЧШЕ БЫТЬ БОЛЕЕ РАВНОДУШНЫМ.',
 'b2': 'Я ТОЖЕ ТАК СЧИТАЮ. ЖЕНЩИН БОЛЬШЕ ПРИВЛЕКАЮТ РАВНОДУШНЫЕ ПЛОХИЕ ПАРНИ.',
 'b3': 'НО РАЗВЕ НАШ ЛИДЕР УЖЕ НЕДОСТАТОЧНО ПЛОХ?',
 'b4': 'ГДЕ, ЧЁРТ ВОЗЬМИ, ТЫ БЫЛ ЧТО ТЫ МОЖЕШЬ ЗНАТЬ!',
}
HTML = sys.argv[1]
with sync_playwright() as p:
    br = p.chromium.launch(args=['--allow-file-access-from-files'])
    pg = br.new_page(viewport={'width':412,'height':800})
    errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)[:200]))
    pg.goto('file://' + HTML); pg.wait_for_timeout(1200)
    pg.evaluate("""async ([det, rec, dict]) => {
        const tb=(s)=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
        await DB.put('kv',{k:'model:det',v:tb(det).buffer});
        await DB.put('kv',{k:'model:rec',v:tb(rec).buffer});
        await DB.put('kv',{k:'model:dict',v:new TextDecoder().decode(tb(dict))});
        await OCR.loadModels();
        window.__cer=(a,b)=>{const norm=(s)=>(String(s).toLowerCase().match(/[а-яё]/g)||[]).join('');
          const s=Array.from(norm(a)),t=Array.from(norm(b));
          let prev=Array.from({length:t.length+1},(_,j)=>j),cur=new Array(t.length+1);
          for(let i=1;i<=s.length;i++){cur[0]=i;
            for(let j=1;j<=t.length;j++)cur[j]=Math.min(prev[j]+1,cur[j-1]+1,prev[j-1]+(s[i-1]===t[j-1]?0:1));
            [prev,cur]=[cur,prev];}
          return +(prev[t.length]/Math.max(1,t.length)*100).toFixed(1);};
    }""", [b64('/home/user/koma_models/koma_det.onnx'), b64('/home/user/koma_models/koma_rec.onnx'),
           b64('/home/user/koma_models/koma_dict.txt')])
    # словарь — ВШИТЫЙ (никакой подстановки): так, как у пользователя
    load = pg.evaluate("""async () => {
        const t0 = performance.now();
        const ok = await Words.load();
        return {ok, size: Words.size, ms: Math.round(performance.now()-t0), source: Words.source,
                ordered: Words.ordered};
    }""")
    print('словарь: %s слов · %d мс · «%s» · порядок %s' % (load['size'], load['ms'], load['source'], load['ordered']))
    total = 0
    for name in TRUTH:
        out = pg.evaluate("""async (imgb64) => {
            const img = new Image();
            await new Promise((r,j)=>{img.onload=r;img.onerror=j;img.src='data:image/png;base64,'+imgb64;});
            const c = document.createElement('canvas'); c.width=img.width; c.height=img.height;
            c.getContext('2d',{willReadFrequently:true}).drawImage(img,0,0);
            const R = sanitizeRules(RULES);
            const t0 = performance.now();
            const res = await recognizePage(c, R, null, null);
            const lines = res.regions.slice().sort((a,b)=>(a.top||0)-(b.top||0));
            return {ms: Math.round(performance.now()-t0),
                    text: lines.map(l => Words.ready ? Words.polish(l.text, R.junkRatio, l.confidence) : l.text)};
        }""", b64('/tmp/%s.png' % name))
        text = ' '.join(out['text'])
        c = pg.evaluate("([a,b]) => __cer(a,b)", [text, TRUTH[name]])
        total += c
        print('%s CER %5.1f%% · %4d мс · %s' % (name, c, out['ms'], text[:100]))
    print('СУММА CER: %.1f' % total)
    if errs: print('ошибки:', errs[:2])
    br.close()
