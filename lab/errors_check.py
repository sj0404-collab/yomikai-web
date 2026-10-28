#!/usr/bin/env python3
"""Ошибки, которые видит человек на телефоне: тост «Ошибка: …» и пустые места.

Появился после скриншота с Android 28.10: при нажатии «Распознать текст» без
моделей выскакивал тост «Ошибка: Cannot read properties of undefined (reading
'catch')», а шторка «Модели OCR» открывалась с пустым «СОСТОЯНИЕМ».

Проверяем в настоящем Chromium ровно этот сценарий:
  1. ошибок в консоли и всплывающих «Ошибка: …» нет;
  2. шторка «Модели» открылась САМА и в «СОСТОЯНИИ» есть строки (не пусто);
  3. в состоянии написано, что моделей нет, и что делать;
  4. тост объясняет причину словами («Сначала добавьте модели OCR»), а не стеком;
  5. повторное открытие «Моделей» кнопкой ⚙ тоже заполняет состояние.

Запуск: python3 lab/errors_check.py [--shot shots/models-sheet.png]
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HTML = os.environ.get('KOMA_HTML', os.path.join(ROOT, 'koma-web.html'))
PAGE = os.path.join(ROOT, 'data', 'real', 'prose-15.jpg')

fails = []
def ok(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        fails.append(msg)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--shot', default=os.path.join(ROOT, 'shots', 'models-sheet.png'))
    a = ap.parse_args()
    assert os.path.exists(HTML), 'нет сборки: ' + HTML
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(args=['--no-sandbox', '--allow-file-access-from-files'])
        pg = b.new_page(viewport={'width': 412, 'height': 800}, device_scale_factor=2)
        errors, toasts = [], []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' else None)
        pg.goto('file://' + os.path.abspath(HTML))
        pg.wait_for_timeout(900)

        # Ловим ВСЕ тосты: так видно, что именно увидел человек.
        pg.evaluate("""() => {
            window.__toasts = [];
            const orig = window.toast;
            window.toast = function (msg) {
                window.__toasts.push(String(msg));
                try { const el = document.getElementById('toast');
                      if (el) { el.textContent = String(msg); el.classList.add('on'); } } catch (e) {}
                return orig.apply(this, arguments);
            };
        }""")

        # Читалка без моделей — как на телефоне: страница есть, моделей нет.
        pg.evaluate("""async (url) => {
            const img = new Image(); img.src = url; await img.decode();
            const c = makeCanvas(img.naturalWidth, img.naturalHeight);
            c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
            Reader.pages = [{ name: 'cover', img: c, w: c.width, h: c.height }];
            Reader.canvases = [c]; Reader.page = 0;
            document.getElementById('library').classList.remove('on');
            document.getElementById('reader').classList.add('on');
            document.getElementById('strip').innerHTML =
              '<div class="pagewrap" data-page="0" style="position:relative;height:900px">' +
              '<img src="' + url + '" style="width:100%;display:block">' +
              '<div data-frames="0" style="position:absolute;inset:0"></div></div>';
            Reader.paintPage(0);
            Reader.showStart && Reader.showStart();
        }""", 'file://' + os.path.abspath(PAGE))
        pg.wait_for_timeout(300)

        # 1. Жмём «Распознать текст» — тот самый путь, что дал тост с ошибкой.
        if pg.locator('#btnStartScan').count():
            pg.click('#btnStartScan')
        else:
            pg.evaluate("() => Reader.scanCurrent(false)")
        pg.wait_for_timeout(1200)

        ok(not errors, 'ошибок в консоли нет' + (': ' + '; '.join(errors[:3]) if errors else ''))
        pg.evaluate("() => { const t = document.getElementById('toast'); }")
        bad = pg.evaluate("() => (window.__toasts || []).filter(t => /catch|undefined|null is not|Cannot read/.test(t))")
        ok(not bad, 'тостов с «reading catch»/undefined нет' + (': ' + str(bad) if bad else ''))
        said = pg.evaluate("() => (window.__toasts || []).join(' | ')")
        ok('добавьте модели' in said.lower(), 'человеку сказано, что делать: ' + said[:120])

        # 2. Шторка «Модели» открылась сама и не пустая
        opened = pg.evaluate("() => document.getElementById('sheetModels').classList.contains('on')")
        ok(opened, 'шторка «Модели OCR» открылась сама после «Распознать» без моделей')
        state = pg.evaluate("() => document.getElementById('modelsState').innerText.trim()")
        ok(bool(state), 'в «СОСТОЯНИИ» есть строки, а не пусто: ' + state.replace('\n', ' · ')[:120])
        ok('моделей нет' in state.lower(), 'написано прямо, что моделей нет')

        pg.screenshot(path=a.shot)
        print('скриншот:', a.shot)

        # 3. Повторное открытие кнопкой ⚙ тоже заполняет состояние
        pg.evaluate("() => { closeSheets(); document.getElementById('modelsState').innerHTML = ''; }")
        pg.evaluate("() => document.getElementById('btnModels').click()")
        pg.wait_for_timeout(600)
        state2 = pg.evaluate("() => document.getElementById('modelsState').innerText.trim()")
        ok(bool(state2), 'кнопка ⚙ в библиотеке тоже рисует состояние моделей')

        # 4. Ни одного необработанного промиса за всё время
        ok(not errors, 'падений за весь сценарий нет')
        b.close()

    print('ИТОГ:', 'ВСЁ ПРОШЛО' if not fails else 'ЕСТЬ ПАДЕНИЯ (%d)' % len(fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
