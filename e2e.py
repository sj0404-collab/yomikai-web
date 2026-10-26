#!/usr/bin/env python3
"""Настоящий прогон сборки: Chromium + koma-web.html + настоящие модели ONNX.

Никаких заглушек движка: страница открывается как у пользователя, модели
кладятся в IndexedDB, картинка страницы декодируется браузером, распознавание
идёт через вшитый onnxruntime-web и вшитые wasm-бинари.

Запуск: python3 e2e.py [путь-к-jpg]
"""
import base64
import gzip
import json
import os
import sys

from playwright.sync_api import sync_playwright

HTML = '/home/user/koma-web.html'
MODELS = '/home/user/koma_models'
IMG = sys.argv[1] if len(sys.argv) > 1 else '/home/user/uploads/cover.jpg'


def read_dict():
    """Словарь 250k: сначала рабочая копия, потом версия внутри репозитория."""
    plain = '/home/user/lab/ru_250k.txt'
    if os.path.exists(plain):
        return open(plain, encoding='utf-8').read()
    packed = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'e2e', 'ru_250k.txt.gz')
    with gzip.open(packed, 'rt', encoding='utf-8') as f:
        return f.read()


def b64(path):
    return base64.b64encode(open(path, 'rb').read()).decode()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--allow-file-access-from-files'])
        page = browser.new_page(viewport={'width': 412, 'height': 800})
        logs = []
        page.on('console', lambda m: logs.append(m.text[:300]))
        page.on('pageerror', lambda e: logs.append('PAGEERROR ' + str(e)[:300]))
        page.goto('file://' + HTML)
        page.wait_for_timeout(1500)

        # 1. Модели — в IndexedDB, ровно как их кладёт пользователь через ⚙
        print('· кладу модели в IndexedDB и поднимаю движок…')
        res = page.evaluate("""async ([det, rec, dict]) => {
            const toBytes = (b64) => Uint8Array.from(atob(b64), c => c.charCodeAt(0));
            await DB.put('kv', { k: 'model:det', v: toBytes(det).buffer });
            await DB.put('kv', { k: 'model:rec', v: toBytes(rec).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(toBytes(dict)) });
            const ok = await OCR.loadModels();
            return { ok, engine: OCR.engine, reason: OCR.reason, dict: OCR.dict.length,
                     det: OCR.det && OCR.det.outputNames, rec: OCR.rec && OCR.rec.outputNames };
        }""", [b64(MODELS + '/koma_det.onnx'), b64(MODELS + '/koma_rec.onnx'), b64(MODELS + '/koma_dict.txt')])
        print('  движок:', res)
        if not res.get('ok'):
            print('ОТКАЗ: движок не поднялся — ' + str(res))
            print('\n'.join(logs[-5:]))
            browser.close()
            return 2

        # 2. Словарь русских слов
        print('· гружу словарь ru_250k…')
        page.evaluate("""async (text) => {
            const rank = new Map(); let n = 0;
            for (const line of text.split('\\n')) {
                const w = (line.split(/\\s+/)[0] || '').toLowerCase();
                if (!w) continue;
                if (!rank.has(w)) rank.set(w, n);
                n++;
            }
            Words.rank = rank; Words.size = n; Words.ready = true;
            return n;
        }""", read_dict())

        # 3. Страница целиком: детектор + распознавание + правила чтения
        print('· распознаю страницу целиком…')
        full = page.evaluate("""async (b64img) => {
            const img = new Image();
            img.src = 'data:image/jpeg;base64,' + b64img;
            await img.decode();
            const c = makeCanvas(img.naturalWidth, img.naturalHeight);
            c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
            const t0 = performance.now();
            const R = sanitizeRules(RULES);
            const res = await recognizePage(c, R, null, null);
            const lines = readingOrder(res.regions, true, true, R);
            return {
                size: [c.width, c.height], boxes: res.boxes, crops: res.crops,
                detMs: Math.round(res.detMs), recMs: Math.round(res.recMs),
                detPass: res.detPass, largePasses: res.largePasses,
                lines: lines.map(l => ({ text: l.text, top: +l.top.toFixed(3), large: !!l.large })),
                ms: Math.round(performance.now() - t0),
            };
        }""", b64(IMG))

        # 4. Как на телефоне: страница читается ПОЛОСАМИ по экрану 412×800
        print('· читаю полосами, как на экране 412×800…')
        bands = page.evaluate("""async (b64img) => {
            const img = new Image();
            img.src = 'data:image/jpeg;base64,' + b64img;
            await img.decode();
            const c = makeCanvas(img.naturalWidth, img.naturalHeight);
            c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
            const viewH = 800, H = c.height;
            // Запас полосы берём из правил — ровно как читалка (bandOverlap).
            // Шаг — один экран: пользователь пролистывает по экрану.
            const R = sanitizeRules(RULES);
            const pad = Math.min(H * R.bandOverlap, viewH * 0.25);
            const step = viewH;
            const keys = new Map();          // как Reader.bandCache
            const t0 = performance.now();
            let scans = 0;
            for (let scroll = 0; scroll < H; scroll += step) {
                const y0 = Math.max(0, scroll - pad);
                const y1 = Math.min(H, scroll + viewH + pad);
                const key = Math.round(scroll / 96) + ':' + Math.round((scroll + viewH) / 96);
                if (keys.has(key)) continue;
                const res = await recognizePage(c, R, null, { y0, y1, vy0: scroll, vy1: scroll + viewH, key });
                const lines = readingOrder(res.regions, true, true, R);
                keys.set(key, { lines, res });
                scans++;
            }
            const parts = Array.from(keys.entries())
                .sort((a, b) => (a[1].res.band?.y0 ?? 0) - (b[1].res.band?.y0 ?? 0));
            const lines = mergeBandLines(parts.map(([, p]) => p), c);
            return {
                scans, lines: lines.map(l => ({ text: l.text, top: +l.top.toFixed(3), large: !!l.large })),
                boxes: parts.reduce((a, [, p]) => a + p.res.boxes, 0),
                crops: parts.reduce((a, [, p]) => a + p.res.crops, 0),
                ms: Math.round(performance.now() - t0),
            };
        }""", b64(IMG))
        full = bands

        print(f"  полос {full['scans']} · боксов {full['boxes']} · кропов {full['crops']} · всего {full['ms']} мс")
        print('\nКАК ЧИТАЕТСЯ:')
        for i, l in enumerate(full['lines'], 1):
            mark = '  [крупный]' if l['large'] else ''
            print(f"  {i}. {l['text']}{mark}")

        want = [
            ('титул целиком (с «сестрой тирана»)', lambda t: 'тирана' in t.lower()),
            ('слово «будучи» прочитано верно', lambda t: 'будучи' in t.lower()),
            ('реплика 1 «УЖЕ ПОРА НАЧИНАТЬ ВСТРЕЧУ…»', lambda t: 'уже пора' in t.lower()),
            ('реплика 2 «НЕ УВЕРЕН, КАК СТОИТ СКАЗАТЬ ЭТО…»', lambda t: 'не уверен' in t.lower()),
            ('реплика 3 «В БУДУЩЕМ, КОГДА ВЫ БУДЕТЕ…»', lambda t: 'в будущем' in t.lower()),
        ]
        texts = [l['text'].lower() for l in full['lines']]
        joined = ' '.join(texts)
        bad = 0
        print('\nпроверки:')
        for name, test in want:
            hit = any(test(t) for t in texts)
            bad += 0 if hit else 1
            print(('  PASS ' if hit else '  FAIL ') + name)
        dup = ('встречу' in joined and joined.count('встречу') > 1) or joined.count('тирана') > 1
        bad += 1 if dup else 0
        print(('  FAIL ' if dup else '  PASS ') + 'дублей реплик нет')
        n = len(full['lines'])
        print(('  PASS ' if 4 <= n <= 6 else '  FAIL ') + f'реплик {n} (в оригинале 5)')

        if logs:
            print('\nконсоль страницы (последние строки):')
            for line in logs[-5:]:
                print('  ' + line)
        browser.close()
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
