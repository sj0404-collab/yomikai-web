"""Честный замер читалки на ЧУЖИХ страницах из archive.org.

  LD_LIBRARY_PATH=~/libs/usr/lib/x86_64-linux-gnu CHROME_EXE=... \
  python3 lab/eval_archive.py [--pages 2] [--dir data/real/vesyolyie_kartinki_1988_12_djvu]

Что делает. Берёт страницы, скачанные tools/fetch_archive.py, читает их ТЕМ ЖЕ
путём, что телефон 412×800 (полосы, настройки по умолчанию), и сравнивает
каждую прочитанную строку с эталоном из ref.xml (текст выпуска, нарезанный по
строкам на том же скане). Эталон — машинный OCR archive.org, он тоже ошибается,
поэтому CER ниже ~5 % здесь не имеет смысла; важны порядок величин и грубые
провалы: строки, которых читалка не увидела вовсе, и строки, прочитанные мусором.

Печатает по странице: сколько строк в эталоне, сколько нашла читалка, сколько
совпало (CER ≤ 25 %), средний CER совпавших. В конце — худшие строки, чтобы
было видно, что именно лечить.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

from playwright.sync_api import sync_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = '/home/user/koma-web.html'
MODELS = '/home/user/koma_models'

PAGE_JS = """async ([b64img, speed]) => {
    const img = new Image();
    img.src = 'data:image/jpeg;base64,' + b64img;
    await img.decode();
    const c = makeCanvas(img.naturalWidth, img.naturalHeight);
    c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
    const viewH = 800, H = c.height;
    const R = sanitizeRules(speed ? { ...RULES, speed } : RULES);
    const pad = Math.min(H * R.bandOverlap, viewH * 0.25);
    const keys = new Map();
    const t0 = performance.now();
    for (let scroll = 0; scroll < H; scroll += viewH) {
        const y0 = Math.max(0, scroll - pad);
        const y1 = Math.min(H, scroll + viewH + pad);
        const key = Math.round(scroll / 96) + ':' + Math.round((scroll + viewH) / 96);
        if (keys.has(key)) continue;
        const res = await recognizePage(c, R, null, { y0, y1, vy0: scroll, vy1: scroll + viewH, key });
        keys.set(key, { lines: readingOrder(res.regions, true, true, R), res });
    }
    const parts = Array.from(keys.entries())
        .sort((a, b) => (a[1].res.band?.y0 ?? 0) - (b[1].res.band?.y0 ?? 0));
    const lines = mergeBandLines(parts.map(([, p]) => p), c);
    return { ms: Math.round(performance.now() - t0), size: [c.width, c.height],
             lines: lines.map(l => ({ text: l.text, top: +l.top.toFixed(3) })) };
}"""


def b64(path):
    return base64.b64encode(open(path, 'rb').read()).decode()


def launch(p):
    exe = os.environ.get('CHROME_EXE') or ''
    kw = {'args': ['--no-sandbox', '--allow-file-access-from-files']}
    if exe and os.path.exists(exe):
        kw['executable_path'] = exe
    return p.chromium.launch(**kw)


def norm(s: str) -> str:
    s = s.lower().replace('ё', 'е')
    return re.sub(r'[^а-я0-9]+', ' ', s).strip()


def cer(ref: str, hyp: str) -> float:
    ref, hyp = norm(ref), norm(hyp)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, a in enumerate(ref, 1):
        cur = [i]
        for j, b in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
        prev = cur
    return prev[-1] / len(ref)


def ref_pages(xml_path: str) -> list[list[str]]:
    """Строки эталона по страницам — в том же порядке, что скачанные jpg."""
    pages = []
    root = ET.parse(xml_path).getroot()
    for obj in root.iter('OBJECT'):
        lines = []
        for line in obj.iter('LINE'):
            words = [(w.text or '').strip() for w in line.iter('WORD')]
            text = ' '.join(w for w in words if w)
            if norm(text):
                lines.append(text)
        pages.append(lines)
    return pages


def main(argv: list[str]) -> int:
    pages_n = 2
    min_ref = 12
    folder = os.path.join(REPO, 'data', 'real', 'vesyolyie_kartinki_1988_12_djvu')
    speed = ''
    i = 0
    while i < len(argv):
        if argv[i] == '--pages':
            pages_n = int(argv[i + 1]); i += 2
        elif argv[i] == '--dir':
            folder = argv[i + 1]; i += 2
        elif argv[i] == '--min-ref':
            min_ref = int(argv[i + 1]); i += 2
        elif argv[i] == '--speed':
            speed = argv[i + 1]; i += 2
        else:
            i += 1
    ref = ref_pages(os.path.join(folder, 'ref.xml'))
    shots_all = sorted(f for f in os.listdir(folder) if f.startswith('page-') and f.endswith('.jpg'))
    # Страницы комиксов часто без текста вовсе — для замера берём те, где эталон
    # богат (иначе «покрытие 0 %» говорит о странице, а не о читалке).
    rich = [(int(re.findall(r'\d+', n)[0]), n) for n in shots_all]
    rich = [(i, n) for i, n in rich if i < len(ref) and len(ref[i]) >= min_ref]
    rich.sort(key=lambda x: -len(ref[x[0]]))
    shots = [n for _, n in rich[:pages_n]]
    print(f'{os.path.basename(folder)}: страниц {len(shots_all)} · с текстом ≥ {min_ref} строк: {len(rich)} · берём {len(shots)}')
    print('  ' + ', '.join(f'{n} ({len(ref[int(re.findall(r"\d+", n)[0])])} строк)' for n in shots))

    rows = []
    with sync_playwright() as p:
        b = launch(p)
        page = b.new_page(viewport={'width': 412, 'height': 800})
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
        page.evaluate("""(text) => {
            const rank = new Map(); let n = 0;
            for (const line of text.split('\\n')) {
              const w = (line.split(/\\s+/)[0] || '').toLowerCase();
              if (!w) continue;
              if (!rank.has(w)) rank.set(w, n);
              n++;
            }
            Words.rank = rank; Words.ready = rank.size > 0;
        }""", open('/home/user/lab/ru_250k.txt', encoding='utf-8').read())

        for idx, name in enumerate(shots):
            path = os.path.join(folder, name)
            page.evaluate("[_textHits = 0, _textMiss = 0, _textCache.clear()]")
            r = page.evaluate(PAGE_JS, [b64(path), speed])
            gt = ref[int(re.findall(r'\d+', name)[0])] if int(re.findall(r'\d+', name)[0]) < len(ref) else []
            got = [l['text'] for l in r['lines']]
            # каждая прочитанная строка ищет свою лучшую пару в эталоне; эталонная
            # строка считается найденной, если хоть одна прочитанная близка к ней
            pairs = []
            used = set()
            for g in got:
                best, best_c = None, 1.01
                for j, t in enumerate(gt):
                    c = cer(t, g) if len(norm(t)) >= 4 else 1.01
                    if c < best_c:
                        best, best_c = j, c
                if best is not None and best_c <= 0.25:
                    used.add(best)
                pairs.append({'got': g, 'ref': gt[best] if best is not None else '',
                              'cer': best_c if best is not None else None})
            matched = [x for x in pairs if x['cer'] is not None and x['cer'] <= 0.25]
            mean = sum(x['cer'] for x in matched) / len(matched) if matched else None
            rows.append({'page': name, 'size': r['size'], 'ms': r['ms'],
                         'gt_lines': len(gt), 'got_lines': len(got),
                         'found': len(used), 'exact_pairs': len(matched),
                         'mean_cer': mean, 'pairs': pairs})
            print(f"\n{idx + 1}. {name} {r['size'][0]}×{r['size'][1]} · {r['ms']} мс · "
                  f"эталонных строк {len(gt)} · читалка нашла {len(got)} · "
                  f"из эталона покрыто {len(used)} ({len(used) * 100 // max(1, len(gt))} %) · "
                  f"пар с CER ≤ 25 %: {len(matched)}")
            if mean is not None:
                print(f"   средний CER по совпавшим парам: {mean * 100:.1f} %")
            for x in sorted(matched, key=lambda z: -z['cer'])[:4]:
                print(f"   × {x['cer'] * 100:4.0f} %  {x['got'][:70]!r}")
            missed = 0
            for j, t in enumerate(gt):
                if j in used:
                    continue
                if len(norm(t)) >= 12:
                    missed += 1
                    if missed <= 3:
                        print(f"   потеряно: {t[:70]!r}")
        b.close()
    out = os.path.join(REPO, 'runs', 'eval_archive.json')
    json.dump(rows, open(out, 'w'), ensure_ascii=False, indent=1)
    print(f'\nсохранено: {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
