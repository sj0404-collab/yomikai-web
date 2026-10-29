#!/usr/bin/env python3
"""Читалка в эмуляторе APKForge Studio — живой прогон, а не «на глаз».

Что делает: поднимает Studio (vite), ставит в её эмулятор РЕАЛЬНЫЙ АПК v1.9.40
(положенный туда как `assets/webapp/index.html` — это тот же файл, что
приложение грузит из assets, побайтово), импортирует страницу манги, три модели
OCR, распознаёт страницу и ЧИТАЕТ ВСЛУХ, замеряя:
  • сколько реплик и в каком порядке (жалоба «прочитал всего одну реплику»);
  • какие строки реально ушли в синтезатор и с какими паузами;
  • сколько раз лента меняла направление (жалоба «дёрнулся, потом ещё дважды»).

Голос: в headless-Chromium синтезатора нет, поэтому перед загрузкой страницы
старушка `speechSynthesis` подменяется мок-движком с такими же событиями
(onstart/onend, длительность ∝ длине текста) — иначе проверить чтение нельзя
вообще. Всё остальное — настоящее: WASM-распознавание, словарь, движок чтения,
прокрутка.

Запуск:  python3 forge-emu-test.py [--apk путь] [--keep]
Нужен работающий Studio:  cd /home/user/forge && npx vite --host 0.0.0.0 --port 5173
"""
import argparse
import asyncio
import json
import os
import statistics
import sys

from playwright.async_api import async_playwright

STUDIO = os.environ.get('STUDIO_URL', 'http://localhost:5173/')
PAGE = '/home/user/kw5/e2e/page.jpg'
MODELS = ['/tmp/mdl/detection.onnx', '/tmp/mdl/cyrillic.onnx', '/tmp/mdl/cyrillic.txt']
SHOTS = '/home/user/forge-shots'

# Мок-синтезатор: те же события, что у Web Speech, длительность ∝ длине реплики.
MOCK_VOICE = """
(() => {
  const mk = {
    speaking: false, pending: false, paused: false, _log: [], _t: 0,
    getVoices() { return [{ name: 'Русский (эмулятор Forge)', lang: 'ru-RU', voiceURI: 'mock:ru', localService: true, default: true }]; },
    speak(u) {
      this.speaking = true;
      const dur = Math.max(400, Math.min(3000, 300 + String(u.text || '').length * 45));
      this._log.push({ text: String(u.text || ''), t0: Date.now() });
      setTimeout(() => { try { u.onstart && u.onstart({}); } catch (e) {} }, 10);
      clearTimeout(this._t);
      this._t = setTimeout(() => {
        this.speaking = false;
        const last = this._log[this._log.length - 1];
        if (last) last.t1 = Date.now();
        try { u.onend && u.onend({}); } catch (e) {}
      }, dur);
    },
    cancel() { this.speaking = false; clearTimeout(this._t); },
    pause() {}, resume() {},
  };
  try { Object.defineProperty(window, 'speechSynthesis', { value: mk, configurable: true, writable: true }); } catch (e) {}
  window.SpeechSynthesisUtterance = class { constructor(t) { this.text = String(t || ''); this.rate = 1; this.lang = ''; this.voice = null; } };
  window.__emuSaid = () => mk._log.slice();
  // Проба прокрутки: каждый кадр запоминаем положение ленты — по ней видно
  // рывки (смены направления) во время чтения.
  window.__scrollLog = [];
  const sample = () => {
    const s = document.getElementById('strip');
    if (s) window.__scrollLog.push([Date.now(), Math.round(s.scrollTop)]);
    requestAnimationFrame(sample);
  };
  requestAnimationFrame(sample);
})();
"""

ok_all = True


def ok(cond, msg):
    global ok_all
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        ok_all = False


def jerks(log):
    """Сколько раз лента меняла направление (это и есть «дёргается»)."""
    moves = []
    prev = log[0][1] if log else 0
    for _, y in log:
        if abs(y - prev) >= 2:
            moves.append(1 if y > prev else -1)
            prev = y
    changes = sum(1 for a, b in zip(moves, moves[1:]) if a != b)
    return changes, len(moves)


async def run(apk):
    async with async_playwright() as p:
        # Памяти в песочнице ~0,6 ГБ: держим один процесс и не даём V8 расти
        # бесконечно (страница 11 МБ + 12 МБ моделей + WASM иначе роняют рендерер).
        b = await p.chromium.launch(args=[
            '--no-sandbox', '--mute-audio', '--disable-gpu', '--disable-dev-shm-usage',
            '--renderer-process-limit=1', '--process-per-site',
            '--js-flags=--max-old-space-size=1536'])
        ctx = await b.new_context(viewport={'width': 1500, 'height': 950})
        pg = await ctx.new_page()
        await pg.add_init_script(MOCK_VOICE)
        errors = []
        pg.on('console', lambda m: errors.append(m.text[:200]) if m.type == 'error' else None)
        pg.on('pageerror', lambda e: errors.append(str(e)[:200]))

        await pg.goto(STUDIO, wait_until='networkidle', timeout=180000)
        await pg.wait_for_timeout(2500)
        await pg.screenshot(path=f'{SHOTS}/01-studio.png')

        # ── 1. Ставим АПК в эмулятор студии ──────────────────────────────────
        await pg.locator('input[type=file][accept=".apk"]').set_input_files(apk)
        await pg.wait_for_timeout(7000)
        body = await pg.inner_text('body')
        ok('Installed net.koma.reader' in body, 'студия приняла АПК читалки: '
           + next((l for l in body.split('\n') if 'Installed' in l), '—'))
        fr = [f for f in pg.frames if f != pg.main_frame][0]
        ok(fr.url.startswith('blob:'), 'эмулятор показывает страницу из assets АПК')
        await pg.screenshot(path=f'{SHOTS}/02-apk-in-emulator.png')

        said = await fr.evaluate('() => speechSynthesis.getVoices().map(v => v.name).join(",")')
        ok('эмулятор Forge' in said, 'в эмуляторе есть синтезатор (мок с событиями Web Speech): ' + said)

        # ── 2. Страница манги и модели ───────────────────────────────────────
        await fr.locator('#imgPick').set_input_files(PAGE)
        await pg.wait_for_timeout(2500)
        await fr.locator('#modelPick').set_input_files(MODELS)
        ready = False
        for _ in range(24):
            await pg.wait_for_timeout(2500)
            if '"ready":true' in await fr.evaluate(
                    "() => { try { return JSON.stringify({ ready: OCR.ready }); } catch (e) { return '{}'; } }"):
                ready = True
                break
        ok(ready, 'ONNX-модели поднялись в эмуляторе (WASM-распознавание работает)')
        await pg.screenshot(path=f'{SHOTS}/03-library.png')

        # ── 3. Открываем книгу и распознаём страницу ─────────────────────────
        await fr.locator('.card').first.click()
        await pg.wait_for_timeout(3000)
        # Полное распознавание страницы (кнопка в шторке текста): одна полоса
        # дала бы только видимую часть, а проверяем всю страницу.
        await fr.evaluate("() => { const b = document.querySelector('#btnFullPage');"
                          " if (b) b.click(); else document.querySelector('#btnOcr2').click(); }")
        regions = None
        for _ in range(30):
            await pg.wait_for_timeout(2000)
            raw = await fr.evaluate(
                "() => { try { const d = Reader.regions.get(Reader.page);"
                " return d ? JSON.stringify(d.lines.map(l => ({ t: l.text, top: l.top }))) : ''; }"
                " catch (e) { return ''; } }")
            if raw:
                regions = json.loads(raw)
                break
        ok(bool(regions), 'страница распознана в эмуляторе')
        texts = [r['t'] for r in (regions or [])]
        for i, t in enumerate(texts, 1):
            print(f'     реплика {i}: {t}')
        ok(len(texts) == 3, f'реплик ровно 3 (а не 12 обрывков): {len(texts)}')
        joined = ' '.join(texts)
        ok('ВЫСОЧЕСТВО' in joined.replace('ВЫСО- ЧЕСТВО', 'ВЫСОЧЕСТВО').replace('ВЫСО-ЧЕСТВО', 'ВЫСОЧЕСТВО'),
           'склейка слов через перенос не потеряна')
        ok(all('ВЫСО-ЧЕСТВО' not in t for t in texts), 'реплика не разрезана на два текста')
        await pg.screenshot(path=f'{SHOTS}/04-recognized.png')

        # ── 4. Читаем вслух ──────────────────────────────────────────────────
        await fr.evaluate("() => { window.__scrollLog = []; }")
        await fr.evaluate("() => { const b = document.querySelector('#btnStartRead'); if (b) b.click();"
                          " else { const r = document.querySelector('#btnRead'); if (r) r.click(); } }")
        for _ in range(40):
            await pg.wait_for_timeout(1000)
            n = await fr.evaluate("() => (window.__emuSaid ? window.__emuSaid().length : 0)")
            if n >= 3:
                break
        await pg.wait_for_timeout(1500)
        log = await fr.evaluate("() => window.__emuSaid()")
        await pg.evaluate("() => 0")
        await pg.screenshot(path=f'{SHOTS}/05-reading.png')

        log = [x for x in log if str(x.get('text', '')).strip()]   # prime(' ') не считаем
        said_texts = [x['text'] for x in log]
        print('     в синтезатор ушло:')
        for i, t in enumerate(said_texts, 1):
            print(f'       {i}. {t}')
        ok(len(said_texts) >= 3, f'голос получил все реплики: {len(said_texts)} из 3')
        ok(said_texts[:3] == texts[:3], 'порядок чтения совпадает с порядком реплик на странице')
        ok(not any(said_texts[i] == said_texts[i + 1] for i in range(len(said_texts) - 1)),
           'ни одна реплика не прочитана дважды подряд')
        gaps = [log[i + 1]['t0'] - (log[i].get('t1') or log[i]['t0']) for i in range(len(log) - 1)]
        if gaps:
            print('     паузы между репликами, мс: ' + ', '.join(str(g) for g in gaps))
            ok(max(gaps) < 2500, f'между репликами нет долгих провалов (макс {max(gaps)} мс)')

        # ── 5. Прокрутка: рывки ──────────────────────────────────────────────
        scroll = await fr.evaluate("() => window.__scrollLog")
        ch, moves = jerks(scroll)
        print(f'     лента: {len(scroll)} замеров, {moves} движений, смен направления: {ch}')
        ok(ch <= 4, f'лента не дёргается: смен направления {ch} (было по три анимации на реплику)')

        # ── 6. Панель и состояние ────────────────────────────────────────────
        state = json.loads(await fr.evaluate(
            "() => JSON.stringify({ panel: getComputedStyle(document.querySelector('#playBar')).display,"
            " queue: (TTS.queue || []).length, stopped: TTS.stopped,"
            " mode: Reader.mode, page: Reader.page + 1 });"))
        print('     состояние: ' + json.dumps(state, ensure_ascii=False))
        ok(state['page'] == 1, 'читалка на той же странице (никуда не перескочила)')
        ok(errors == [], 'ошибок в консоли страницы нет' + ((' : ' + '; '.join(errors[:3])) if errors else ''))

        await pg.screenshot(path=f'{SHOTS}/06-final.png')
        await b.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--apk', default='/home/user/koma-probe-forge.apk')
    a = ap.parse_args()
    os.makedirs(SHOTS, exist_ok=True)
    asyncio.run(run(a.apk))
    print('ВСЁ ПРОШЛО' if ok_all else 'ЕСТЬ ПАДЕНИЯ')
    sys.exit(0 if ok_all else 1)
