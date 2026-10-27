"""Штатный koma_rec на СВОЕЙ разметке, внутри приложения (Chromium + onnxruntime-web).

  LD_LIBRARY_PATH=~/libs/usr/lib/x86_64-linux-gnu CHROME_EXE=... \
  python3 lab/eval_in_app.py --split val

Печатает: CER жадного чтения и CER своего словарного декодера, плюс «целиком верных».
Это честная точка отсчёта «что умеет приложение сейчас» на настоящих строках манги.
"""
import argparse, base64, json, os, sys

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
    ap = argparse.ArgumentParser()
    ap.add_argument('--labels', default=os.path.join(REPO, 'data', 'lines', 'labels.tsv'))
    ap.add_argument('--root', default=os.path.join(REPO, 'data', 'lines'))
    ap.add_argument('--split', default='val')
    ap.add_argument('--onnx', default=None, help='своя модель вместо koma_rec')
    a = ap.parse_args()
    rows = []
    for line in open(a.labels, encoding='utf-8'):
        p = line.rstrip('\n').split('\t')
        if len(p) >= 4 and a.split and p[3] != a.split:
            continue
        if len(p) >= 2:
            rows.append((p[0], p[1]))
    print(f'строк {len(rows)} ({a.split or "всё"})')

    with sync_playwright() as p:
        b = launch(p)
        page = b.new_page()
        page.goto('file://' + HTML)
        page.wait_for_timeout(1200)
        rec_path = a.onnx or os.path.join(MODELS, 'koma_rec.onnx')
        print('распознаватель:', os.path.basename(rec_path))
        eng = page.evaluate("""async ([det, rec, dict]) => {
            const t = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
            await DB.put('kv', { k: 'model:det', v: t(det).buffer });
            await DB.put('kv', { k: 'model:rec', v: t(rec).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(t(dict)) });
            const ok = await OCR.loadModels();
            return { ok, engine: OCR.engine, reason: OCR.reason };
        }""", [b64(os.path.join(MODELS, 'koma_det.onnx')),
               b64(rec_path),
               b64(os.path.join(MODELS, 'koma_dict.txt'))])
        print('движок:', eng)
        if not eng.get('ok'):
            return 1
        cases = [(b64(os.path.join(a.root, f)), ref) for f, ref in rows]
        res = page.evaluate("""async (cases) => {
            const out = [];
            for (const [png, ref] of cases) {
                const img = new Image();
                await new Promise((ok, bad) => { img.onload = ok; img.onerror = bad;
                    img.src = 'data:image/png;base64,' + png; });
                const cv = makeCanvas(img.width, img.height);
                cv.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
                _probsCache = { canvas: null, res: null };
                const greedy = await decodeCrop(cv);
                _probsCache = { canvas: null, res: null };
                const pr = await recProbs(cv);
                const beam = pr ? beamDecode(pr) : ['', 0];
                out.push({ ref, greedy: greedy[0], beam: beam[0] });
            }
            return out;
        }""", cases)
        b.close()

    n = len(res)
    for key in ('greedy', 'beam'):
        tot = sum(cer(r['ref'], r[key]) * max(1, len(r['ref'])) for r in res)
        den = sum(max(1, len(r['ref'])) for r in res)
        exact = sum(1 for r in res if r['ref'] == r[key])
        print(f"{key:7s}: CER {tot/den*100:.1f} % · целиком верных {exact}/{n}")
    json.dump(res, open(os.path.join(REPO, 'runs', 'eval_in_app.json'), 'w'), ensure_ascii=False, indent=1)
    print('\nпримеры (эталон → жадно / декодер):')
    for r in res[:8]:
        print(f"  {r['ref']:24s} → {r['greedy']!r} / {r['beam']!r}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
