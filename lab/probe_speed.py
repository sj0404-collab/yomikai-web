"""Скорость против качества: две модели распознавателя на одних и тех же кропах.

  LD_LIBRARY_PATH=~/libs/usr/lib/x86_64-linux-gnu CHROME_EXE=... \
  python3 lab/probe_speed.py

Берёт проверочные строки из data/lines/labels.tsv, читает их ВНУТРИ приложения
(Chromium + onnxruntime-web) штатной koma_rec и своей rec_manga, замеряет время
одного вызова модели и считает CER. Так видно цену замены модели, а не только
качество: своя модель в 8 раз меньше, но выигрывает ли она по времени — вопрос.
"""
import base64, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from playwright.sync_api import sync_playwright
from charset import load_charset

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = '/home/user/koma-web.html'
MODELS = '/home/user/koma_models'


def b64(p):
    return base64.b64encode(open(p, 'rb').read()).decode()


def launch(p):
    exe = os.environ.get('CHROME_EXE') or ''
    kw = {'args': ['--no-sandbox', '--allow-file-access-from-files']}
    if exe and os.path.exists(exe):
        kw['executable_path'] = exe
    return p.chromium.launch(**kw)


def cer(ref, hyp):
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, a in enumerate(ref, 1):
        cur = [i]
        for j, b in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1] / len(ref)


def main():
    rows = []
    for line in open(os.path.join(REPO, 'data', 'lines', 'labels.tsv'), encoding='utf-8'):
        p = line.rstrip('\n').split('\t')
        if len(p) >= 4 and p[3] == 'val':
            rows.append((p[0], p[1]))
    print(f'проверочных строк {len(rows)}')
    files = [(f, ref, b64(os.path.join(REPO, 'data', 'lines', f))) for f, ref in rows]

    with sync_playwright() as p:
        b = launch(p)
        page = b.new_page()
        page.goto('file://' + HTML)
        page.wait_for_timeout(1200)
        page.evaluate("""async ([det, dict]) => {
            const t = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
            await DB.put('kv', { k: 'model:det', v: t(det).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(t(dict)) });
        }""", [b64(os.path.join(MODELS, 'koma_det.onnx')),
               b64(os.path.join(MODELS, 'koma_dict.txt'))])

        results = {}
        for name, path in (('штатная koma_rec', os.path.join(MODELS, 'koma_rec.onnx')),
                           ('своя rec_manga', os.path.join(REPO, 'models', 'rec_manga.onnx'))):
            rec_b64 = b64(path)
            cases = [[data, ref] for _, ref, data in files]
            out = page.evaluate("""async ([rec, cases]) => {
                const t = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
                await DB.put('kv', { k: 'model:rec', v: t(rec).buffer });
                const ok = await OCR.loadModels();
                if (!ok) return { error: OCR.reason };
                const res = [];
                try {
                for (const [png, ref] of cases) {
                    const img = new Image();
                    await new Promise((r, j) => { img.onload = r; img.onerror = j;
                        img.src = 'data:image/png;base64,' + png; });
                    const cv = makeCanvas(img.width, img.height);
                    cv.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
                    _probsCache = { canvas: null, res: null };
                    const t0 = performance.now();
                    const pr = await recProbs(cv);
                    const t1 = performance.now();
                    const beam = pr ? beamDecode(pr) : ['', 0];
                    const t2 = performance.now();
                    _probsCache = { canvas: null, res: null };
                    const greedy = await decodeCrop(cv);
                    res.push({ ref, greedy: greedy[0], beam: beam[0],
                               recMs: t1 - t0, beamMs: t2 - t1 });
                }
                } catch (e) { return { error: 'в цикле: ' + String(e && e.message || e), done: res.length }; }
                return { res };
            }""", [rec_b64, cases])
            if out.get('error'):
                print(name, 'ОТКАЗ:', out['error'])
                continue
            res = out['res']
            n = len(res)
            rec = sum(r['recMs'] for r in res) / n
            beam = sum(r['beamMs'] for r in res) / n
            for key in ('greedy', 'beam'):
                tot = sum(cer(r['ref'], r[key]) * max(1, len(r['ref'])) for r in res)
                den = sum(max(1, len(r['ref'])) for r in res)
                exact = sum(1 for r in res if r['ref'] == r[key])
                results.setdefault(name, {})[key] = (tot / den * 100, exact)
            results[name]['recMs'] = rec
            results[name]['beamMs'] = beam
            print(f"{name}: вызов модели {rec:.1f} мс · словарный декодер {beam:.1f} мс · "
                  f"CER жадно {results[name]['greedy'][0]:.1f} % · декодер {results[name]['beam'][0]:.1f} %")
        b.close()
    json.dump(results, open(os.path.join(REPO, 'runs', 'probe_speed.json'), 'w'),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())
