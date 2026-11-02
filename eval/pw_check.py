"""Проверка собранного файла в настоящем браузере: реплики, звуки, ошибки JS, время.

Запуск: python3 evalwork/pw_check.py
"""
import asyncio
from playwright.async_api import async_playwright

PAGES = [('kuro-p1.png', 'manhwa-shots/pages/kuro-p1.png', 'manga'),
         ('manhua1-p1.png', 'manhwa-shots/pages/manhua1-p1.png', 'webtoon'),
         ('manhua2-p2.png', 'manhwa-shots/pages/manhua2-p2.png', 'webtoon'),
         ('manhua3x2-p1.png', 'manhwa-shots/pages/manhua3x2-p1.png', 'webtoon'),
         ('comic1x7-p1.png', 'manhwa-shots/pages/comic1x7-p1.png', 'comic')]


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=['--no-sandbox', '--disable-dev-shm-usage'])
        pg = await b.new_page(viewport={'width': 1500, 'height': 980})
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        await pg.goto('file:///home/user/web-ocr/ownocr-web-single.html')
        await pg.wait_for_function(
            "document.getElementById('chipModel').textContent.includes('модели готовы')",
            timeout=180000)
        print('модели:', await pg.inner_text('#chipModel'))
        for name, path, genre in PAGES:
            await pg.select_option('#genre', genre)
            await pg.set_input_files('#file', '/home/user/' + path)
            await pg.wait_for_timeout(600)
            await pg.wait_for_function("!document.getElementById('btnRun').disabled", timeout=60000)
            await pg.click('#btnRun')
            await pg.wait_for_function("document.getElementById('sAll').textContent!==''", timeout=180000)
            await pg.wait_for_timeout(700)
            items = await pg.eval_on_selector_all(
                '#replies li', "els=>els.map(e=>({cls:e.className, txt:e.innerText}))")
            sfx = [i for i in items if 'sfx' in i['cls']]
            print(f'=== {name} · {genre} · {await pg.inner_text("#sAll")} · '
                  f'реплик {len(items)} · звуков {len(sfx)}')
            for i, it in enumerate(items, 1):
                print(f'   {i}. [{"ЗВУК" if "sfx" in it["cls"] else "голос"}] {it["txt"][:78]}')
        await pg.screenshot(path='/home/user/evalwork/app-final.png')
        print('ошибок JS:', len(errors), errors[:2])
        await b.close()


asyncio.run(main())
