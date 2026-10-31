#!/usr/bin/env python3
"""Скриншоты настоящих страниц манги и манхвы через Chromium.

Зачем браузер: сайт-читалка отдаёт страницы только после исполнения JS и
проверки Cloudflare, поэтому curl/urllib получают 403. Chromium проходит.

Что делает:
  1. по названию находит книгу в каталоге через открытый API читалки;
  2. берёт номер главы и список страниц (`pages[].url`) из API;
  3. открывает каждую страницу в Chromium и снимает её скриншотом в натуральную
     величину — это и есть «страница такой, какой её видит читатель».

    python3 scripts/19_shot_mangalib.py --book 'старшей сестрой тирана' \
        --chapter 5 --pages 3,4 --out ../manhwa-shots/pages

Картинки страниц — чужие и защищены авторским правом: они нужны только для
замера и в репозиторий не кладутся (в .gitignore).
"""
import argparse
import json
import os
import urllib.parse
import urllib.request

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')
API = 'https://api.mangalib.org'


def api(path):
    r = urllib.request.Request(API + path, headers={'User-Agent': UA, 'Accept': 'application/json'})
    return json.loads(urllib.request.urlopen(r, timeout=40).read())


def find_book(text: str) -> dict:
    """Ищем книгу по названию в каталоге: API фильтр по имени игнорирует."""
    needle = text.lower()
    for page in range(1, 41):
        for m in api(f'/api/manga?page={page}&limit=60&site_id[]=1').get('data') or []:
            name = (m.get('rus_name') or '').lower()
            if needle in name:
                return m
    raise SystemExit(f'книга «{text}» не нашлась')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--book', required=True, help='часть русского названия')
    ap.add_argument('--chapter', type=int, default=1)
    ap.add_argument('--volume', type=int, default=1)
    ap.add_argument('--pages', default='3,4', help='номера страниц через запятую, с 1')
    ap.add_argument('--out', default='../manhwa-shots/pages')
    ap.add_argument('--tag', default='', help='префикс имени файла')
    a = ap.parse_args()

    book = find_book(a.book)
    slug = book['slug_url']
    kind = (book.get('type') or {}).get('label')
    print(f"книга: {book.get('rus_name')} · {kind} · {slug}")
    ch = api(f'/api/manga/{slug}/chapter?number={a.chapter}&volume={a.volume}')['data']
    pages = ch['pages']
    print(f'глава {a.chapter}: страниц {len(pages)}, высоты {[p["height"] for p in pages][:8]}')
    os.makedirs(a.out, exist_ok=True)
    tag = a.tag or slug.split('--')[0]
    want = [int(x) for x in a.pages.split(',')]

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--no-sandbox'])
        ctx = b.new_context(user_agent=UA, locale='ru-RU',
                            viewport={'width': 760, 'height': 1200})
        pg = ctx.new_page()
        for k, num in enumerate(want, 1):
            if not 1 <= num <= len(pages):
                continue
            page = pages[num - 1]
            url = 'https://img3.cdnrulib.link/' + page['url']
            pg.goto(url, wait_until='load', timeout=90000)
            pg.wait_for_timeout(1200)
            # браузер показывает одиночную картинку «по размеру окна» — задаём
            # натуральную ширину, иначе снимок выходит полоской
            pg.evaluate('''(w) => { const im = document.querySelector('img');
                im.style.width = w + 'px'; im.style.height = 'auto';
                document.body.style.margin = 0; }''', page['width'])
            pg.set_viewport_size({'width': page['width'], 'height': 1200})
            pg.wait_for_timeout(800)
            im = pg.query_selector('img')
            dst = os.path.join(a.out, f'{tag}-p{k}.png')
            im.screenshot(path=dst)
            print(f'  {dst} · {page["width"]}×{page["height"]}')
        b.close()


if __name__ == '__main__':
    main()
