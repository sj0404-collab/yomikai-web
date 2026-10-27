import base64
from playwright.sync_api import sync_playwright
def b64(p): return base64.b64encode(open(p,'rb').read()).decode()
CASES = [('250k', '/home/user/koma-web.html'), ('1.5M', '/tmp/koma-web-1.5M.html'), ('3M', '/tmp/koma-web-3M.html')]
for label, html in CASES:
    with sync_playwright() as p:
        br = p.chromium.launch(args=['--allow-file-access-from-files'])
        pg = br.new_page(viewport={'width':412,'height':800})
        errs=[]; pg.on('pageerror', lambda e: errs.append(str(e)[:150]))
        try:
            pg.goto('file://' + html, wait_until='load', timeout=120000)
        except Exception as e:
            print('[%s] страница не открылась: %s' % (label, str(e)[:100])); br.close(); continue
        pg.wait_for_timeout(1500)
        out = pg.evaluate("""async () => {
            const t0 = performance.now();
            const ok = await Words.load();
            const ms = Math.round(performance.now() - t0);
            return {ok, size: Words.size, ms, source: Words.source};
        }""")
        print('[%s] вшитый словарь: слов %s · разжатие+разбор %s мс · источник «%s» · ошибки %s'
              % (label, out['size'], out['ms'], out['source'], errs[:1]))
        br.close()
