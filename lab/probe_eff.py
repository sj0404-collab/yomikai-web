"""Замер стоимости распознавания: сколько кропов, вызовов модели и времени на строку.

  LD_LIBRARY_PATH=~/libs/usr/lib/x86_64-linux-gnu CHROME_EXE=... \
  python3 lab/probe_eff.py /home/user/uploads/cover.jpg

Сравнивает режимы одних и тех же правил на одной и той же странице: сколько кропов
и миллисекунд стоит «перебирать варианты» (decodeVariants), «расширять кроп»
(extCrop: full / light / off) и словарный декодер (beam). Задача — найти, что
можно отключить без потери текста.
"""
import base64, json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
from playwright.sync_api import sync_playwright

HTML = '/home/user/koma-web.html'
MODELS = '/home/user/koma_models'
IMG = sys.argv[1] if len(sys.argv) > 1 else '/home/user/uploads/cover.jpg'


def b64(p):
    return base64.b64encode(open(p, 'rb').read()).decode()


def launch(p):
    exe = os.environ.get('CHROME_EXE') or ''
    kw = {'args': ['--no-sandbox', '--allow-file-access-from-files']}
    if exe and os.path.exists(exe):
        kw['executable_path'] = exe
    return p.chromium.launch(**kw)


def main():
    with sync_playwright() as p:
        b = launch(p)
        page = b.new_page(viewport={'width': 412, 'height': 800})
        page.goto('file://' + HTML)
        page.wait_for_timeout(1200)
        eng = page.evaluate("""async ([det, rec, dict]) => {
            const t = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
            await DB.put('kv', { k: 'model:det', v: t(det).buffer });
            await DB.put('kv', { k: 'model:rec', v: t(rec).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(t(dict)) });
            return await OCR.loadModels();
        }""", [b64(os.path.join(MODELS, 'koma_det.onnx')),
               b64(os.path.join(MODELS, 'koma_rec.onnx')),
               b64(os.path.join(MODELS, 'koma_dict.txt'))])
        print('движок:', eng)
        if not eng:
            return 1
        img_b64 = b64(IMG)
        variants = [
            ('как есть', {}),
            ('без перебора вариантов', {'decodeVariants': False}),
            ('расширение кропа: light', {'extCrop': 'light'}),
            ('расширение кропа: off', {'extCrop': False}),
            ('light + без перебора', {'extCrop': 'light', 'decodeVariants': False}),
        ]
        out = {}
        for name, rules in variants:
            r = page.evaluate("""async ([b64img, over]) => {
                const img = new Image();
                img.src = 'data:image/jpeg;base64,' + b64img;
                await img.decode();
                const c = makeCanvas(img.naturalWidth, img.naturalHeight);
                c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
                const R = sanitizeRules(Object.assign({}, RULES, over));
                const t0 = performance.now();
                const res = await recognizePage(c, R, null, null);
                const lines = readingOrder(res.regions, true, true, R);
                return { ms: Math.round(performance.now() - t0), crops: res.crops,
                         boxes: res.boxes, recMs: res.recMs, detMs: res.detMs,
                         n: lines.length,
                         text: lines.map(l => l.text).join(' | ') };
            }""", [img_b64, rules])
            out[name] = r
            print(f"{name:26s} {r['ms']:5d} мс · боксов {r['boxes']:3d} · кропов {r['crops']:3d} "
                  f"· строк {r['n']:2d}")
        base = out['как есть']['text']
        print('\nтекст:')
        for name, r in out.items():
            same = 'тот же' if r['text'] == base else 'ОТЛИЧАЕТСЯ'
            print(f"  {name:26s} {same}")
        print('\nэталон (как есть):', base[:300])
        for name in ('расширение кропа: light', 'light + без перебора'):
            print(f"\n{name}:", out[name]['text'][:300])
        json.dump(out, open('/home/user/koma-web/runs/probe_eff.json', 'w'), ensure_ascii=False, indent=1)
        b.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
