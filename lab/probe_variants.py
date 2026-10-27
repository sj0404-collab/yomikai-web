"""Какой перебор подготовки кропа реально нужен: замер по 45 проверочным строкам.

  LD_LIBRARY_PATH=~/libs/usr/lib/x86_64-linux-gnu CHROME_EXE=... \
  python3 lab/probe_variants.py

Для каждой строки из data/lines/labels.tsv гоняем ВСЕ подготовки кропа штатной
моделью внутри приложения и считаем CER каждого варианта. Задача — увидеть,
какие варианты дают верный текст, а какие только съедают по 78 мс: перебор
(part3.js decodeAllVariants) идёт по порядку и обрывается, когда словарь
доволен, поэтому порядок и состав вариантов нужно выбирать по данным.
"""
import base64, json, os, sys

from playwright.sync_api import sync_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = '/home/user/koma-web.html'
MODELS = '/home/user/koma_models'
VARIANTS = ['orig', 'pad20', 'up2', 'contrast', 'pad20up2', 'bin0']


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
            rows.append((os.path.join(REPO, 'data', 'lines', p[0]), p[1]))
    cases = [[b64(f), ref] for f, ref in rows]
    print(f'строк {len(cases)}')

    with sync_playwright() as p:
        b = launch(p)
        page = b.new_page()
        page.goto('file://' + HTML)
        page.wait_for_timeout(1200)
        page.evaluate("""async ([det, rec, dict]) => {
            const t = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
            await DB.put('kv', { k: 'model:det', v: t(det).buffer });
            await DB.put('kv', { k: 'model:rec', v: t(rec).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(t(dict)) });
            return await OCR.loadModels();
        }""", [b64(os.path.join(MODELS, 'koma_det.onnx')),
               b64(os.path.join(MODELS, 'koma_rec.onnx')),
               b64(os.path.join(MODELS, 'koma_dict.txt'))])
        # словарь нужен, чтобы работал allWordsKnown — как в приложении
        try:
            rank = open('/home/user/lab/ru_250k.txt', encoding='utf-8').read()
        except FileNotFoundError:
            rank = ''
        page.evaluate("""(text) => {
            const rank = new Map(); let n = 0;
            for (const line of text.split('\\n')) {
              const w = (line.split(/\\s+/)[0] || '').toLowerCase();
              if (!w) continue;
              if (!rank.has(w)) rank.set(w, n);
              n++;
            }
            Words.rank = rank; Words.ready = rank.size > 0;
        }""", rank)

        out = page.evaluate("""async (cases) => {
            const R = sanitizeRules({});
            const res = [];
            for (const [png, ref] of cases) {
              const img = new Image();
              await new Promise((r, j) => { img.onload = r; img.onerror = j;
                img.src = 'data:image/png;base64,' + png; });
              const cv = makeCanvas(img.width, img.height);
              cv.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
              const pointed = padCanvas(cv, 0.2);
              const tries = [['orig', cv], ['pad20', pointed]];
              if (cv.height >= 12) tries.push(['up2', upscaleCanvas(cv, 2)]);
              tries.push(['contrast', contrastCanvas(cv)]);
              tries.push(['pad20up2', upscaleCanvas(pointed, 2)]);
              tries.push(['bin0', binarizeCanvas(cv, 0, R)]);
              const got = {};
              for (const [name, c2] of tries) {
                _probsCache = { canvas: null, res: null };
                const t0 = performance.now();
                let text = '';
                try { text = (await decodeCrop(c2))[0]; } catch (e) { text = ''; }
                got[name] = { text, ms: performance.now() - t0, known: allWordsKnown(text) };
              }
              res.push({ ref, got });
            }
            return res;
        }""", cases)
        b.close()

    stats = {v: {'cer': 0.0, 'den': 0, 'exact': 0, 'known': 0, 'ms': 0.0} for v in VARIANTS}
    wins = {v: 0 for v in VARIANTS}
    for r in out:
        ref = r['ref']
        n = max(1, len(ref))
        best, bestCer = None, None
        for v, d in r['got'].items():
            c = cer(ref, d['text'])
            s = stats.setdefault(v, {'cer': 0.0, 'den': 0, 'exact': 0, 'known': 0, 'ms': 0.0})
            s['cer'] += c * n; s['den'] += n; s['ms'] += d['ms']
            if ref == d['text']:
                s['exact'] += 1
            if d['known']:
                s['known'] += 1
            if bestCer is None or c < bestCer:
                best, bestCer = v, c
        if best:
            wins[best] += 1
    print(f"{'вариант':10s} {'CER':>6s} {'целиком':>8s} {'словарь дов.':>13s} {'мс/строка':>10s} {'лучший':>7s}")
    for v in VARIANTS:
        s = stats[v]
        print(f'{v:10s} {s["cer"]/max(1,s["den"])*100:5.1f}% {s["exact"]:5d}/{len(out):<3d} '
              f'{s["known"]:9d}/{len(out):<3d} {s["ms"]/len(out):9.1f} {wins[v]:6d}')
    json.dump({'stats': stats, 'wins': wins, 'rows': out},
              open(os.path.join(REPO, 'runs', 'probe_variants.json'), 'w'), ensure_ascii=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
