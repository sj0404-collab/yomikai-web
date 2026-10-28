#!/usr/bin/env python3
"""Проверка, что движок Google Lens виден и работает ИЗ ЧИТАЛКИ (не из настроек).

Причина появления: в сборке v1.9.29 движок Lens был, но добраться до него можно
было только «⚙ в библиотеке → Модели → Движок» или через прокрутку шторки
«Текст страницы». В читалке его не было видно вообще — так и сказал человек.
Теперь проверяем это тестом, а не глазами:

  1. в шапке читалки есть кнопка 🔍 (#btnLensHdr), и она нажимается;
  2. она открывает шторку Lens (#sheetLens) и показывает состояние движка;
  3. в шторке «Голос и чтение» есть блок движка (#engineChips2) с двумя
     вариантами, и «Google Lens» реально переключает режим;
  4. после переключения подсветка стоит на Lens, подпись страницы говорит
     «Google Lens», а кнопка «Открыть эту страницу в Lens» на месте;
  5. обратное переключение «В файле» возвращает офлайн-обещание.

Запуск: python3 lab/lens_ui_check.py [--shot shots/lens-in-reader.png]
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
    ap.add_argument('--shot', default=os.path.join(ROOT, 'shots', 'lens-in-reader.png'))
    a = ap.parse_args()
    assert os.path.exists(HTML), 'нет сборки: ' + HTML
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(args=['--no-sandbox', '--allow-file-access-from-files'])
        pg = b.new_page(viewport={'width': 412, 'height': 800}, device_scale_factor=2)
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.goto('file://' + os.path.abspath(HTML))
        pg.wait_for_timeout(1200)

        # Открываем читалку на настоящей странице (без моделей: интерфейс не
        # зависит от того, загружены ли веса).
        pg.evaluate("""async (url) => {
            const img = new Image(); img.src = url; await img.decode();
            const c = makeCanvas(img.naturalWidth, img.naturalHeight);
            c.getContext('2d', { willReadFrequently: true }).drawImage(img, 0, 0);
            Reader.pages = [{ name: 'p', img: c, w: c.width, h: c.height }];
            Reader.canvases = [c];
            Reader.page = 0; Reader.mode = 'vertical'; Reader.frames = true;
            document.getElementById('library').classList.remove('on');
            document.getElementById('reader').classList.add('on');
            document.getElementById('strip').innerHTML =
              '<div class="pagewrap" data-page="0" style="position:relative;height:900px">' +
              '<img src="' + url + '" style="width:100%;display:block">' +
              '<div data-frames="0" style="position:absolute;inset:0"></div></div>';
            Reader.paintPage(0);
        }""", 'file://' + os.path.abspath(PAGE))
        pg.wait_for_timeout(400)

        # 1. Кнопка в шапке читалки
        ok(pg.locator('#btnLensHdr').count() == 1, 'в шапке читалки есть кнопка 🔍 (Google Lens)')
        ok(pg.locator('#btnLensHdr').is_visible(), 'кнопка 🔍 видна, а не спрятана стилями')

        # 2. Она открывает шторку Lens
        pg.click('#btnLensHdr')
        pg.wait_for_timeout(400)
        ok(pg.locator('#sheetLens').evaluate("el => el.classList.contains('on')"),
           '🔍 открывает шторку Google Lens')
        state = pg.locator('#lensState').inner_text()
        ok('Google Lens' in state or 'в файле' in state, 'шторка показывает состояние движка')

        # 3. Блок движка в настройках чтения
        pg.evaluate("() => { closeSheets(); }")
        pg.wait_for_timeout(300)
        pg.click('#btnSettings')
        pg.wait_for_timeout(400)
        ok(pg.locator('#engineChips2').count() == 1, 'в «Голос и чтение» есть блок движка')
        ok(pg.locator('#engineLens2').is_visible(), 'вариант «Google Lens» виден')
        ok(pg.locator('#btnLensSend2').is_visible(), 'кнопка «Открыть страницу в Lens» видна в настройках')

        # 4. Переключение на Lens
        pg.click('#engineLens2')
        pg.wait_for_timeout(500)
        hot = pg.evaluate("() => document.getElementById('engineLens2').classList.contains('hot')")
        ok(hot, 'после нажатия «Google Lens» подсветка стоит на нём')
        ok(pg.evaluate("() => LENS.isLens() === true"), 'движок действительно переключился на Lens')
        sub = pg.locator('#rSub').inner_text()
        ok('Google Lens' in sub, 'подпись страницы говорит, что движок — Google Lens (сейчас: %r)' % sub)
        hint = pg.locator('#engineHint2').inner_text()
        ok('интернет' in hint.lower() or 'Google' in hint,
           'подсказка честно предупреждает, что страница уйдёт в Google')
        pg.screenshot(path=a.shot)
        print('скриншот:', a.shot)

        # 5. Обратно «в файле» — обещание офлайна возвращается
        pg.click('#engineLocal2')
        pg.wait_for_timeout(400)
        ok(pg.evaluate("() => LENS.isLens() === false"), 'возврат на «В файле» работает')
        ok(pg.evaluate("() => document.getElementById('btnLensHdr').classList.contains('hot') === false"),
           'значок 🔍 гаснет в офлайн-режиме')

        ok(not errors, 'ошибок в консоли страницы нет' + (': ' + '; '.join(errors[:3]) if errors else ''))
        b.close()

    print('ИТОГ:', 'ВСЁ ПРОШЛО' if not fails else 'ЕСТЬ ПАДЕНИЯ (%d)' % len(fails))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
