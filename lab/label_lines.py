# Скрипт разметки: собирает data/lines/labels.tsv из index.json.
#   text  — эталон (взят у консенсуса «жадное чтение = словарный декодер = правка»,
#           либо вписан руками после просмотра листов sheet-*.png)
#   split — train/val (делим ПО СТРАНИЦАМ, чтобы проверка была на невиданных страницах)
import json, re, sys
from collections import defaultdict

IDX = 'data/lines/index.json'
OUT = 'data/lines/labels.tsv'
DROP_PAGES = {           # скриншоты самого приложения (списки текста, тест PaddleOCR)
    'Screenshot_20261021-123654.jpg', 'Screenshot_20261021-123712.jpg',
    'Screenshot_20261021-123537.jpg', 'Screenshot_20261021-123543.jpg',
    'Screenshot_20261021-123555.jpg', 'Screenshot_20261021-123559.jpg',
    'Screenshot_20261021-123627.jpg', 'Screenshot_20261021-123709.jpg',
    'Screenshot_20261023-145640.jpg', 'Screenshot_20261024-142111.jpg',
    'Screenshot_20261024-180653.jpg', 'Screenshot_20261024-184010.jpg',
}
UI = re.compile(r'(Текст стран|Манга|Справа налево|PaddleOCR|Кириллица|Латиница|^\d+ из \d+|\d+/\d+)', re.I)
CYR = re.compile(r'[А-Яа-яЁё]')

# Ручные эталоны: то, что написано на кропе (проверено по листам /tmp/rev_*.png).
# Ключ — файл кропа. Если кроп обрезан сверху/снизу и буквы не читаются — файла тут нет.
MANUAL = {
 'Screenshot_20261022-220215__17.png': 'ВЕЛИКО-',
 'Screenshot_20261022-220215__18.png': 'ЛЕПНОЕ',
 'Screenshot_20261022-220215__23.png': 'МИКО,',
 'Screenshot_20261022-220215__24.png': 'НАМ ТОЧНО',
 'Screenshot_20261022-220215__25.png': 'НИКОГО',
 'Screenshot_20261022-220215__32.png': 'НАВИГАТОРУ,',
 'Screenshot_20261022-220215__34.png': 'ЛАДНО,',
 'Screenshot_20261022-220215__36.png': 'ПОЙДУ',
 'Screenshot_20261022-220215__37.png': 'ПРОВЕ-',
 'Screenshot_20261022-220232__23.png': 'С ХАНОЙ.',
 'Screenshot_20261022-220232__30.png': 'ОТ ХАНЫ.',
 'Screenshot_20261022-220232__35.png': 'ГОТОВО.',
 'Screenshot_20261022-220232__37.png': 'Я РАССЧИ-',
 'Screenshot_20261022-225820__04.png': 'ДЛЯ ПОД-',
 'Screenshot_20261022-225820__18.png': 'ПОЕСТЬ',
 'Screenshot_20261022-225820__19.png': 'С ХАНОЙ.',
 'Screenshot_20261022-225820__31.png': 'ГОТОВО.',
 'Screenshot_20261022-225820__33.png': 'Я РАССЧИ-',
 'Screenshot_20261022-225820__39.png': 'пауза',
 'Screenshot_20261022-225916__07.png': 'У ЭТОГО',
 'Screenshot_20261022-225916__13.png': 'ПРИЯТНАЯ',
 'Screenshot_20261022-225916__14.png': 'В ФИЛЬМЕ',
 'Screenshot_20261022-225916__17.png': 'МИБЛИ,',
 'Screenshot_20261022-225916__18.png': 'ТОЛЬКО',
 'Screenshot_20261022-225916__19.png': 'ФЕРА',
 'Screenshot_20261022-225916__25.png': 'ТРЕТЬ',
 'Screenshot_20261022-225916__29.png': 'ПЕПЕЛЬНЫЕ',
 'Screenshot_20261022-225916__30.png': 'ГРЕМЛИНЫ,',
 'Screenshot_20261022-225916__35.png': 'пауза',
 'Screenshot_20261023-105117__07.png': 'ЗАЧЕМ',
 'Screenshot_20261023-105117__11.png': 'СЕЙЧАС.',
 'Screenshot_20261023-105117__16.png': 'ЧТО БЫЛО БЫ',
 'Screenshot_20261023-105117__18.png': 'НЕПЛОХО ПРО-',
 'Screenshot_20261023-105117__21.png': 'ГУЛЯТЬСЯ В',
 'Screenshot_20261023-120751__23.png': 'С ХАНОЙ.',
 'Screenshot_20261023-120751__30.png': 'ОТ ХАНЫ.',
 'Screenshot_20261023-120751__35.png': 'ГОТОВО.',
 'Screenshot_20261023-120751__37.png': 'Я РАССЧИ-',
 'Screenshot_20261023-214715__08.png': 'СЕБЯ,',
 'Screenshot_20261023-214715__09.png': 'СЛОВНО',
 'Screenshot_20261023-214715__16.png': 'СЕГОДНЯ',
 'Screenshot_20261023-214715__18.png': 'ПРИШЛА!',
 'Screenshot_20261023-214715__20.png': 'ЧТО-ТО',
 'Screenshot_20261023-214715__22.png': 'СО МНОЙ,',
 'Screenshot_20261023-214715__23.png': 'НО ВРОДЕ',
 'Screenshot_20261024-115522__12.png': 'СЕГОДНЯ',
 'Screenshot_20261024-115522__14.png': 'ПРИШЛА!',
 'Screenshot_20261024-115522__16.png': 'ЧТО-ТО',
 'Screenshot_20261024-115522__18.png': 'СО МНОЙ,',
 'Screenshot_20261024-115522__19.png': 'НО ВРОДЕ',
 'Screenshot_20261024-184015__11.png': 'ПРИШЛОСЬ',
 'Screenshot_20261024-184015__15.png': 'ЗНАЧИТ.',
 'Screenshot_20261024-184015__17.png': 'НОШЕНИЕ',
 'Screenshot_20261024-184015__19.png': 'КАЧЕСТВА',
 'Screenshot_20261024-184015__25.png': 'ТОЧНО',
 'Screenshot_20261024-184015__28.png': 'СХОДИТЬ',
}
# Явно выброшенные кропы (обрезаны так, что букв не видно, или это картинка, не текст)
DROP_FILES = {
 'Screenshot_20261022-220215__15.png',   # вертикальная японская подпись, не русский текст
 'Screenshot_20261022-220232__40.png', 'Screenshot_20261022-220232__42.png',
 'Screenshot_20261022-220215__14.png',
 'Screenshot_20261023-105117__08.png',
 'Screenshot_20261024-184015__03.png', 'Screenshot_20261024-184015__04.png',
 'Screenshot_20261024-184015__05.png', 'Screenshot_20261024-184015__14.png',
 'Screenshot_20261024-184015__16.png',
}

def main():
    idx = json.load(open(IDX, encoding='utf-8'))
    rows, stats = [], defaultdict(int)
    for r in idx:
        f, page = r['file'], r['page']
        if page in DROP_PAGES:
            stats['страница приложения'] += 1; continue
        if f in DROP_FILES:
            stats['выброшено'] += 1; continue
        if f in MANUAL:
            text = MANUAL[f]; stats['руками'] += 1
        else:
            g = (r.get('guess') or '').strip()
            if len(CYR.findall(g)) < 4 or UI.search(g) or r.get('conf', 0) < 0.85:
                stats['нет эталона'] += 1; continue
            text = g; stats['консенсус'] += 1
        if len(CYR.findall(text)) < 4:
            stats['коротко'] += 1; continue
        rows.append((f, text.upper(), page))
    pages = sorted({p for _, _, p in rows})
    val_pages = set(pages[::5])                      # каждая пятая страница — проверка
    with open(OUT, 'w', encoding='utf-8') as fh:
        for f, text, page in sorted(rows):
            fh.write(f"{f}\t{text}\t{page}\t{'val' if page in val_pages else 'train'}\n")
    print(dict(stats))
    print(f"строк с эталоном {len(rows)} · страниц {len(pages)} · проверочных {len(val_pages)}")
    print(f"→ {OUT}")

if __name__ == '__main__':
    sys.exit(main())
