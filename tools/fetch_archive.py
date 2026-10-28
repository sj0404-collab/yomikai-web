"""Настоящие страницы из открытых источников (archive.org) — для проверки читалки.

  python3 tools/fetch_archive.py crocodile_1936_30 --pages 8
  python3 tools/fetch_archive.py vesyolyie_kartinki_1990_09 --pages 10 --out data/real

Что берём и зачем. Нужны НЕ наши скриншоты, а чужие страницы, которых читалка
не видела: другой шрифт, другая печать, другой век. У archive.org (общественное
достояние) на каждый выпуск журнала лежит jp2.zip со сканами и djvu.txt с
готовым текстом — то есть страница и её эталонный текст в одном месте. Сканы
1988–2001 («Весёлые картинки») — это комиксы с облачками и рукописными
подписями, то есть самый близкий к манге материал, который можно брать
легально. Манга из онлайн-читален не скачивается: права, и в репозиторий такое
класть нельзя.

Кладём в data/real/<identifier>/: page-NN.jpg + ref.txt (текст выпуска) +
meta.json. Дальше эти страницы читает lab/eval_archive.py и сравнивает с текстом.
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.request
import zipfile

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def api(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def fetch(identifier: str, pages: int = 8, out_root: str | None = None) -> str:
    out_dir = os.path.join(out_root or os.path.join(REPO, 'data', 'real'), identifier)
    os.makedirs(out_dir, exist_ok=True)
    meta = json.loads(api(f'https://archive.org/metadata/{identifier}'))
    files = {f['name']: f for f in meta.get('files', [])}
    jp2 = next((n for n in files if n.endswith('_jp2.zip')), None)
    if not jp2:
        raise SystemExit(f'{identifier}: нет jp2.zip')
    size = int(files[jp2].get('size') or 0)
    print(f'{identifier}: {jp2} ({size / 1e6:.1f} МБ)')
    blob = api(f'https://archive.org/download/{identifier}/{jp2}', timeout=600)
    z = zipfile.ZipFile(io.BytesIO(blob))
    names = sorted(n for n in z.namelist() if n.lower().endswith('.jp2'))
    print(f'  страниц в выпуске: {len(names)}, берём {pages}')
    saved = []
    for i, n in enumerate(names[:pages]):
        im = Image.open(io.BytesIO(z.read(n)))
        if im.mode != 'RGB':
            im = im.convert('RGB')
        path = os.path.join(out_dir, f'page-{i:02d}.jpg')
        im.save(path, quality=88)
        saved.append({'file': os.path.basename(path), 'size': list(im.size),
                      'source': n.split('/')[-1]})
    # djvu.xml — эталон с координатами каждой строки. По нему можно честно
    # сравнивать не «текст страницы со всем подряд», а КОНКРЕТНУЮ строку с
    # конкретным местом на картинке.
    xml_name = next((n for n in files if n.endswith('_djvu.xml')), None)
    if xml_name:
        open(os.path.join(out_dir, 'ref.xml'), 'wb').write(
            api(f'https://archive.org/download/{identifier}/{xml_name}', timeout=180))
        print(f'  эталон с координатами: ref.xml')
    text = ''
    txt_name = next((n for n in files if n.endswith('_djvu.txt')), None)
    if txt_name:
        text = api(f'https://archive.org/download/{identifier}/{txt_name}',
                   timeout=120).decode('utf-8', 'replace')
        open(os.path.join(out_dir, 'ref.txt'), 'w', encoding='utf-8').write(text)
    json.dump({'identifier': identifier, 'title': meta['metadata'].get('title'),
               'year': meta['metadata'].get('year'), 'pages': saved,
               'ref_chars': len(text), 'license': 'archive.org, общественное достояние'},
              open(os.path.join(out_dir, 'meta.json'), 'w'), ensure_ascii=False, indent=1)
    print(f'  сохранено {len(saved)} страниц в {out_dir}')
    return out_dir


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    pages = 8
    out = None
    ids = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--pages':
            pages = int(argv[i + 1]); i += 2
        elif a == '--out':
            out = argv[i + 1]; i += 2
        else:
            ids.append(a); i += 1
    for ident in ids:
        fetch(ident, pages, out)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
