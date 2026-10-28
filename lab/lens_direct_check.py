#!/usr/bin/env python3
"""Проверка ПРЯМОГО Google Lens в читалке: без сайта и без новых вкладок.

Что проверяем (и почему именно так):
  A. Релей. Страница получает адрес своего релея (RULES.lensRelay), шлёт кадр
     multipart-ом, релей отвечает JSON {"lines": [...]} с CORS — реплики должны
     появиться в читалке, а новых вкладок открыться НЕ должно.
  B. Мост АПК. В страницу подставляется window.KomaLens.recognize (так его
     подставит WebView в АПК) — реплики появляются, сеть не трогается вообще.
  C. Ничего не настроено. Кнопка не должна молча открывать сайт: показываем
     честное сообщение и остаёмся на месте.

Запуск: python3 lab/lens_direct_check.py [--shot shots/lens-direct.png]
"""
import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HTML = os.environ.get('KOMA_HTML', os.path.join(ROOT, 'koma-web.html'))
PAGE = os.path.join(ROOT, 'data', 'real', 'prose-15.jpg')

RETURN_LINES = ['Матушка Медведица и Салли', 'Медвежонок как ни в чём не бывало',
                'Хрум-хрум-хрум!', 'С полным ведром и ведёрком']

fails = []
def ok(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        fails.append(msg)


class Relay(BaseHTTPRequestHandler):
    """Релей как в lab/lens_relay.js: принял multipart → отдал JSON с CORS."""
    seen = 0
    size = 0

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')

    def do_POST(self):
        n = int(self.headers.get('content-length') or 0)
        body = self.rfile.read(n) if n else b''
        Relay.seen += 1
        Relay.size = len(body)
        # Проверяем, что пришёл именно файл-картинка, а не пустышка.
        good = b'name="encoded_image"' in body and len(body) > 5000
        payload = json.dumps({'lines': RETURN_LINES if good else []}).encode()
        self.send_response(200 if good else 400)
        self._cors()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shot', default=os.path.join(ROOT, 'shots', 'lens-direct.png'))
    a = ap.parse_args()
    assert os.path.exists(HTML), 'нет сборки: ' + HTML
    from playwright.sync_api import sync_playwright

    srv = HTTPServer(('127.0.0.1', 0), Relay)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    relay_url = f'http://127.0.0.1:{port}/lens'

    with sync_playwright() as p:
        b = p.chromium.launch(args=['--no-sandbox', '--allow-file-access-from-files'])

        def open_reader(pg):
            pg.goto('file://' + os.path.abspath(HTML))
            pg.wait_for_timeout(1000)
            pg.evaluate("""async (url) => {
                const img = new Image(); img.src = url; await img.decode();
                const c = makeCanvas(img.naturalWidth, img.naturalHeight);
                c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
                Reader.pages = [{ name: 'p', img: c, w: c.width, h: c.height }];
                Reader.canvases = [c]; Reader.page = 0; Reader.mode = 'vertical';
                document.getElementById('library').classList.remove('on');
                document.getElementById('reader').classList.add('on');
                document.getElementById('strip').innerHTML =
                  '<div class="pagewrap" data-page="0" style="position:relative;height:900px">' +
                  '<img src="' + url + '" style="width:100%;display:block">' +
                  '<div data-frames="0" style="position:absolute;inset:0"></div></div>';
                Reader.paintPage(0);
            }""", 'file://' + os.path.abspath(PAGE))
            pg.wait_for_timeout(300)

        # ── A. Релей ────────────────────────────────────────────────────────
        ctx = b.new_context(viewport={'width': 412, 'height': 800}, device_scale_factor=2)
        pg = ctx.new_page()
        opened = []
        ctx.on('page', lambda q: opened.append(q))
        requests = []
        pg.on('request', lambda r: requests.append(r.url))
        open_reader(pg)
        pg.evaluate("""async (url) => {
            RULES = sanitizeRules({ ...RULES, lensRelay: url });
            await LENS.setMode('lens');
            syncEngineUI();
        }""", relay_url)
        ok(pg.evaluate("() => LENS.hasDirect() === true"), 'A: прямой путь распознан как доступный (релей)')
        ok(pg.evaluate("() => LENS.transports().includes('relay')"), 'A: транспорт — свой релей')
        res = pg.evaluate("""async () => {
            const i = Reader.page;
            const got = await LENS.recognizeDirect(Reader.canvases[i], { page: i });
            if (!got.ok) return { ok: false, reason: got.reason };
            const applied = await applyLensText(i, got.lines.join('\\n'), { fromDirect: true });
            const own = Reader.regions.get(i);
            return { ok: true, via: got.via, ms: got.ms, lines: applied.lines,
                     texts: (own && own.lines || []).map(l => l.text) };
        }""")
        ok(res.get('ok') is True, 'A: релей ответил и текст разобран (' + str(res.get('reason', '')) + ')')
        ok(res.get('via') == 'relay', 'A: ответ пришёл через релей, не через сайт')
        ok(res.get('lines') == len(RETURN_LINES), 'A: реплик ровно столько, сколько вернул релей')
        ok(all(t in RETURN_LINES for t in res.get('texts', [])), 'A: тексты реплик совпали с ответом релея')
        ok(len(opened) == 0, 'A: ни одной новой вкладки не открылось')
        ok(Relay.seen >= 1 and Relay.size > 5000, 'A: на релей ушёл именно кадр (' + str(Relay.size) + ' байт)')
        ok(not any('lens.google.com' in u for u in requests), 'A: к Google страница не обращалась')
        pg.evaluate("() => { openSheet('sheetLens'); renderLensSheet(Reader.page); }")
        pg.wait_for_timeout(300)
        pg.screenshot(path=a.shot)
        print('скриншот:', a.shot)
        ctx.close()

        # ── B. Мост АПК ─────────────────────────────────────────────────────
        ctx = b.new_context(viewport={'width': 412, 'height': 800})
        pg = ctx.new_page()
        opened = []
        ctx.on('page', lambda q: opened.append(q))
        requests = []
        pg.on('request', lambda r: requests.append(r.url))
        open_reader(pg)
        pg.add_script_tag(content="""
            window.KomaLens = { recognize: function (b64, opts) {
                window.__lensGotBytes = (b64 || '').length;
                return JSON.stringify({ lines: %s });
            } };
        """ % json.dumps(RETURN_LINES, ensure_ascii=False))
        pg.evaluate("""async () => { RULES = sanitizeRules({ ...RULES, lensRelay: '' }); await LENS.setMode('lens'); }""")
        ok(pg.evaluate("() => LENS.transports().includes('native')"), 'B: мост АПК найден (KomaLens)')
        res = pg.evaluate("""async () => {
            const i = Reader.page;
            const got = await LENS.recognizeDirect(Reader.canvases[i], { page: i });
            const applied = await applyLensText(i, got.lines.join('\\n'), { fromDirect: true });
            return { ok: got.ok, via: got.via, lines: applied.lines,
                     bytes: window.__lensGotBytes || 0 };
        }""")
        ok(res.get('ok') and res.get('via') == 'native', 'B: ответ пришёл от движка АПК')
        ok(res.get('lines') == len(RETURN_LINES), 'B: реплики разложены как обычно')
        ok(res.get('bytes') > 10000, 'B: в мост ушёл непустой JPEG (' + str(res.get('bytes')) + ' симв. base64)')
        ok(len(opened) == 0, 'B: новых вкладок нет')
        ok(not any('lens.google.com' in u or '127.0.0.1' in u for u in requests), 'B: сеть не трогали вообще')
        ctx.close()

        # ── C. Ничего не настроено: честно, без сайта ───────────────────────
        ctx = b.new_context(viewport={'width': 412, 'height': 800})
        pg = ctx.new_page()
        opened = []
        ctx.on('page', lambda q: opened.append(q))
        open_reader(pg)
        pg.evaluate("""async () => { RULES = sanitizeRules({ ...RULES, lensRelay: '' }); await LENS.setMode('lens'); }""")
        ok(pg.evaluate("() => LENS.hasDirect() === false"), 'C: прямого пути нет — так и считается')
        msg = pg.evaluate("""async () => {
            const i = Reader.page;
            const got = await LENS.recognizeDirect(Reader.canvases[i], { page: i });
            return got.reason;
        }""")
        ok('прямой путь недоступен' in str(msg), 'C: причина названа прямо, а не «не получилось»')
        ok(len(opened) == 0, 'C: сайт сам не открылся — решает человек')
        state = pg.evaluate("""async () => {
            openSheet('sheetLens'); renderLensSheet(Reader.page); await new Promise(r => setTimeout(r, 200));
            return document.getElementById('lensDirectWhy').innerText;
        }""")
        ok('не настроен' in state, 'C: в шторке написано, почему прямой путь недоступен')
        ctx.close()
        b.close()

    srv.shutdown()
    print('ИТОГ:', 'ВСЁ ПРОШЛО' if not fails else 'ЕСТЬ ПАДЕНИЯ (%d)' % len(fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
