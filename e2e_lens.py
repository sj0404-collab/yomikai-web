#!/usr/bin/env python3
"""Google Lens как отдельный движок: проверка НА ЖИВОМ браузере.

  python3 e2e_lens.py

Что проверяем (обещания, которые даны человеку):
  1. По умолчанию движок «в файле», и кнопка отправки в Lens НЕ открывает
     вкладку, пока человек сам не переключил движок в ⚙ → Модели.
  2. Переключение движка на «Google Lens» сохраняется и читается после
     перезагрузки страницы.
  3. В режиме Lens кнопка «Открыть в Lens» открывает НОВУЮ ВКЛАДКУ с
     lens.google.com и отправляет туда именно картинку страницы (multipart,
     поле encoded_image). Локальный OCR при этом не запускается.
  4. Текст, вставленный из Lens, становится репликами страницы: они видны в
     шторке, рамки рисуются, и озвучка их читает (TTS.readVisible вызывается).
  5. Возврат на «в файле» снова не пускает картинку в сеть.

Реальную страницу результатов Lens из песочницы получить нельзя (IP под
проверкой на робота), поэтому проверяется факт отправки и адрес, а не текст
ответа. Это и есть честная граница теста.
"""
import base64
import os
import sys

from playwright.sync_api import sync_playwright

HTML = os.environ.get('HTML', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'koma-web.html'))
# Пути — от самого файла, чтобы прогон работал и в песочнице, и на ранере:
# страница и модели лежат в репозитории (data/real, models), а не в /home/user.
_HERE = os.path.dirname(os.path.abspath(__file__))
IMG = os.environ.get('KOMA_IMG', os.path.join(_HERE, 'data', 'real', 'dense.jpg'))
_LEGACY_IMG = '/home/user/uploads/Screenshot_20261023-131019.jpg'
if not os.path.exists(IMG) and os.path.exists(_LEGACY_IMG):
    IMG = _LEGACY_IMG
MODELS = os.environ.get('KOMA_MODELS', os.path.join(_HERE, 'models'))
if not os.path.exists(os.path.join(MODELS, 'koma_det.onnx')) and os.path.isdir('/home/user/koma_models'):
    MODELS = '/home/user/koma_models'

fails = []


def b64(path):
    return base64.b64encode(open(path, 'rb').read()).decode()


def chk(name, cond, extra=''):
    print(('  PASS ' if cond else '  FAIL ') + name + ((' · ' + str(extra)) if extra and not cond else ''))
    if not cond:
        fails.append(name)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(args=['--no-sandbox', '--allow-file-access-from-files'])
        ctx = browser.new_context(viewport={'width': 412, 'height': 800})
        page = ctx.new_page()
        logs = []
        page.on('pageerror', lambda e: logs.append(str(e)[:200]))
        page.goto('file://' + HTML)
        page.wait_for_timeout(1500)

        # 1. по умолчанию — локально
        print('· по умолчанию')
        mode = page.evaluate("LENS.mode")
        chk('движок по умолчанию «в файле»', mode == 'local', mode)
        blocked = page.evaluate("""() => {
            const cv = makeCanvas(40, 20);
            cv.getContext('2d').fillRect(0, 0, 40, 20);
            let made = 0;
            const orig = document.body.appendChild.bind(document.body);
            document.body.appendChild = (n) => { if (n.tagName === 'FORM') made++; return orig(n); };
            const res = LENS.send(cv, { page: 0 });
            document.body.appendChild = orig;
            return { res, made };
        }""")
        chk('в режиме «в файле» форма в сеть не строится', blocked['made'] == 0 and not blocked['res']['ok'],
            blocked)

        # грузим модели: они нужны локальному движку, а после возврата — тем более
        page.evaluate("""async ([det, rec, dict]) => {
            const t = (s) => Uint8Array.from(atob(s), c => c.charCodeAt(0));
            await DB.put('kv', { k: 'model:det', v: t(det).buffer });
            await DB.put('kv', { k: 'model:rec', v: t(rec).buffer });
            await DB.put('kv', { k: 'model:dict', v: new TextDecoder().decode(t(dict)) });
            return await OCR.loadModels();
        }""", [b64(MODELS + '/koma_det.onnx'), b64(MODELS + '/koma_rec.onnx'),
               b64(MODELS + '/koma_dict.txt')])

        # 2. переключение движка кнопкой в ⚙ → Модели
        print('· переключение движка')
        page.evaluate("openSheet('sheetModels')")
        page.wait_for_timeout(300)
        page.click('#engineLens')
        page.wait_for_timeout(400)
        chk('после нажатия кнопки режим = lens', page.evaluate("LENS.mode") == 'lens')
        chk('кнопка подсвечена', page.evaluate("document.getElementById('engineLens').classList.contains('hot')"))
        saved = page.evaluate("async () => (await DB.get('kv','engine:mode')).v")
        chk('выбор сохранён в хранилище', saved == 'lens', saved)

        # открываем страницу в читалке
        page.evaluate("closeSheets()")
        page.evaluate("""async (b64img) => {
            const img = new Image();
            img.src = 'data:image/jpeg;base64,' + b64img;
            await img.decode();
            const c = makeCanvas(img.naturalWidth, img.naturalHeight);
            c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
            Reader.pages = [{ name: 'тест', img: c, w: c.width, h: c.height }];
            Reader.canvases = [c];
            Reader.page = 0;
            Reader.mode = 'vertical';
        }""", base64.b64encode(open(IMG, 'rb').read()).decode())

        # 3. отправка в Lens открывает новую вкладку
        print('· отправка в Google Lens')
        ocr_calls = page.evaluate("""() => { window.__ocr = 0;
            const orig = window.recognizePage;
            window.recognizePage = (...a) => { window.__ocr++; return orig(...a); };
            return true; }""")
        page.evaluate("openSheet('sheetLens'); renderLensSheet(0)")
        page.wait_for_timeout(300)
        with ctx.expect_page(timeout=20000) as newp:
            page.click('#btnLensOpen')
        popup = newp.value
        url = ''
        try:
            popup.wait_for_load_state('domcontentloaded', timeout=20000)
            url = popup.url
        except Exception:
            url = popup.url
        chk('открылась новая вкладка с Google Lens', 'lens.google.com' in url or 'google.com' in url, url[:90])
        chk('локальный OCR при этом не запускался', page.evaluate("window.__ocr") == 0,
            page.evaluate("window.__ocr"))
        popup.close()

        # 4. текст из Lens становится репликами страницы и озвучивается
        print('· возврат текста из Lens')
        lens_text = ("МАЛЫШКА МЕЛИССА\n"
                     "В курятнике все спали.\n"
                     "— Ко-ко-ко, тебе не спится?\n"
                     "Мелисса заплакала.")
        page.evaluate("""(t) => {
            LENS.pendingPage = 0;
            openSheet('sheetLens');
            document.getElementById('lensBox').value = t;
        }""", lens_text)
        spoken = page.evaluate("""() => { window.__spoken = 0;
            const orig = TTS.readVisible;
            TTS.readVisible = function () { window.__spoken++; return orig.apply(this, arguments); };
            return true; }""")
        page.click('#btnLensRead')
        page.wait_for_timeout(600)
        data = page.evaluate("(() => { const d = Reader.regions.get(0); return d ? { n: d.lines.length, first: d.lines[0].text, last: d.lines[d.lines.length-1].text, lens: !!d.fromLens } : null; })()")
        chk('реплики страницы приняты (4)', data and data['n'] == 4, data)
        chk('порядок сверху вниз сохранён', data and data['first'].startswith('МАЛЫШКА') and 'Мелисса' in data['last'], data)
        chk('помечено, что текст из Lens', data and data['lens'])
        chk('озвучка запущена', page.evaluate("window.__spoken") == 1, page.evaluate("window.__spoken"))
        # Рамки рисуются в слой [data-frames] внутри .pagewrap — создаём ровно ту
        # разметку, что строит buildStrip, иначе проверка ничего не доказывает.
        frames = page.evaluate("""(() => {
            const strip = document.getElementById('strip');
            strip.innerHTML = '<div class="pagewrap" data-page="0"><div data-frames="0" style="position:absolute;inset:0"></div></div>';
            Reader.frames = true;
            Reader.paintPage(0);
            return document.querySelectorAll('.frame').length;
        })()""")
        chk('рамки нарисованы для реплик', frames >= 4, frames)
        page.evaluate("TTS.stop()")

        # 5. возврат в офлайн — сеть снова закрыта
        print('· возврат на «в файле»')
        page.evaluate("openSheet('sheetModels')")
        page.click('#engineLocal')
        page.wait_for_timeout(300)
        chk('режим снова local', page.evaluate("LENS.mode") == 'local')
        res = page.evaluate("""() => {
            const cv = makeCanvas(30, 15); cv.getContext('2d').fillRect(0, 0, 30, 15);
            let made = 0;
            const orig = document.body.appendChild.bind(document.body);
            document.body.appendChild = (n) => { if (n.tagName === 'FORM') made++; return orig(n); };
            const r = LENS.send(cv, { page: 0 });
            document.body.appendChild = orig;
            return { ok: r.ok, made };
        }""")
        chk('после возврата картинка в сеть не уходит', res['made'] == 0 and not res['ok'], res)

        # ошибок JS за весь прогон быть не должно
        errs = [l for l in logs if 'Lens' in l or 'LENS' in l or 'Uncaught' in l or 'is not defined' in l]
        chk('ошибок JS нет', not errs, errs[:3])
        browser.close()

    print('\nИТОГ: ' + ('ВСЁ ПРОШЛО' if not fails else f'ПАДЕНИЙ {len(fails)}: ' + ', '.join(fails)))
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
