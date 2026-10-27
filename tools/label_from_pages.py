"""Строгий автоэталон для настоящих кропов: берём только то, в чём не сомневаемся.

  python3 tools/label_from_pages.py --write

Правила (каждое отсекает свой класс грязи):
  1) уверенность штатной модели ≥ 0,93;
  2) в строке ≥ 6 русских букв (короткие обрывки ничего не учат);
  3) все слова ЕСТЬ В СЛОВАРЕ как есть — никакой «починки». Если слово требует
     правки на расстоянии 1, значит модель ошиблась в букве («ПРОЧИТАТЪ»), и
     такой кроп в эталон не годится;
  4) нет цифр, дробей, «//» и служебных слов интерфейса приложения;
  5) страница не из списка страниц приложения (списки распознанного, тест PaddleOCR).

Зачем так строго. Ошибка в эталоне хуже, чем мало эталона: модель выучит ошибку.
Замер на 1662 кропах: строгий фильтр оставляет несколько сотен строк, и каждое
слово в них словарное.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

CYR = re.compile(r"[А-Яа-яЁё]")
ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
UI_WORDS = set("""текст страницы распознавание детектор обновлено осталось читается настройки модели
проверить меню закрыть отмена сохранить поделиться библиотека каталог поиск загрузка глава
страница пауза играть дальше назад вперёд масштаб шторка правила сервис версия тест распознано
боксов кропов полос время секунд прочитать книгу открыть книгу нужен интернет авто онлайн
локальные обложка автор жанр главы том рейтинг статус перевод манга справа налево японский
вертикально чтение глава профиль уведомления подписка реклама скачать приложение версия сайт
популярное новое топ выбор редакции подборка продолжение добавить избранное история
область нажми задать задайте кнопка кнопку рамку рамка целиком заново черновик распознать
синтезатор фразы уходят подсказка инструкция настройка параметры областью область
не выбрана выбери выбрать ошибка повторить удалить копировать экспорт быстрая отправка
заданием сохранение отправить отмена применить готово далее продолжить """.split())
UI_PAGES = {
    "Screenshot_20261021-123537.jpg", "Screenshot_20261021-123543.jpg",
    "Screenshot_20261021-123555.jpg", "Screenshot_20261021-123559.jpg",
    "Screenshot_20261021-123627.jpg", "Screenshot_20261021-123709.jpg",
    "Screenshot_20261021-123654.jpg", "Screenshot_20261021-123712.jpg",
    "Screenshot_20261023-145640.jpg", "Screenshot_20261024-142111.jpg",
    "Screenshot_20261024-180653.jpg", "Screenshot_20261024-184010.jpg",
}


COMMON_RANK = 100000        # как в приложении: «частое» слово — из первых 100 000


def load_dict(ranked: bool = False):
    """Множество слов словаря или словарь «слово → номер строки».

    Ранги нужны, чтобы отделить частые слова от словоформ: «ханои» (Ханой)
    лежит в блоке словоформ за 250 000-й строкой, и модель, прочитавшая
    «с ХАНОИ» вместо «С ХАНОЙ», по одному только словарю не ловится. А по
    рангу — ловится: настоящее слово диалога почти всегда в первых 100 000.
    """
    src = open(os.path.join(REPO, "part0-dict.js"), encoding="utf-8").read()
    m = re.search(r"const DICT_GZ_B64 = '([^']+)'", src)
    words = [line.split()[0].lower()
             for line in gzip.decompress(base64.b64decode(m.group(1))).decode().split("\n")
             if line.strip()]
    if ranked:
        rank = {}
        for i, w in enumerate(words):
            rank.setdefault(w, i)
        return rank
    return set(words)


def one_edit_variants(w: str):
    """Все слова на расстоянии 1 (как в приложении: замена, вставка, удаление, перестановка)."""
    letters = ALPHABET
    for i in range(len(w) + 1):
        for c in letters:
            yield w[:i] + c + w[i:]
    for i in range(len(w)):
        yield w[:i] + w[i + 1:]
        for c in letters:
            yield w[:i] + c + w[i + 1:]
    for i in range(len(w) - 1):
        yield w[:i] + w[i + 1] + w[i] + w[i + 2:]


def word_needs_fix(w: str, known: set, cache: dict) -> bool:
    """True, если словарная правка захочет заменить слово (значит, модель ошиблась)."""
    if len(w) < 4:
        return False
    if w in known:
        return False
    if w in cache:
        return cache[w]
    found = len(w) > 6           # для длинных — сразу да: их правка почти наверняка тронет
    if not found:
        for v in one_edit_variants(w):
            if v in known:
                found = True
                break
    cache[w] = found
    return found


def check(text: str, conf: float, known: set, cache: dict, conf_min: float,
          rank: dict = None):
    t = (text or "").strip()
    if len(CYR.findall(t)) < 6:
        return None, "мало букв"
    if conf < conf_min:
        return None, "низкая уверенность"
    if re.search(r"\d", t) or "//" in t:
        return None, "цифры/код"
    words = [w for w in re.split(r"[^А-Яа-яЁё\-]+", t.lower()) if w]
    if not words:
        return None, "нет слов"
    if any(w.rstrip("-") in UI_WORDS for w in words):
        return None, "интерфейс"
    if "«" in t or "»" in t:            # подсказки приложения цитируют названия кнопок
        return None, "интерфейс"
    if t.endswith((",", "-")) is False and re.search(r"[.!?…]$", t) is None and len(words) > 6:
        return None, "похоже на абзац"   # длинные строки без конца фразы — это описания, не реплики
    for w in words:
        w2 = w.rstrip("-")
        if not w2:
            continue
        if rank is not None:
            # требуем не просто «слово есть в словаре», а «слово частое»:
            # иначе проходят опечатки, случайно совпавшие с редкой словоформой
            r = rank.get(w2)
            if r is None or r > COMMON_RANK:
                return None, "слово не из частых"
            continue
        if w2 in known:
            continue
        if w.endswith("-"):                 # перенос строки: часть слова
            continue
        if word_needs_fix(w2, known, cache):
            return None, "правка по словарю"
    return t.upper(), "ok"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=os.path.join(REPO, "data", "lines", "index.json"))
    ap.add_argument("--extra", default=os.path.join(REPO, "data", "lines", "labels.tsv"),
                    help="уже размеченное руками — сохраняем как есть")
    ap.add_argument("--out", default=os.path.join(REPO, "data", "lines", "labels.tsv"))
    ap.add_argument("--conf", type=float, default=0.93)
    ap.add_argument("--only-pages", default=None,
                    help="файл со списком страниц: авто-эталон берём только с них "
                         "(страницы-экраны приложения отсекаются целиком)")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)

    only_pages = set(open(a.only_pages).read().split()) if a.only_pages else None
    rank = load_dict(ranked=True)
    known = set(rank)
    cache = {}
    idx = json.load(open(a.index, encoding="utf-8"))

    # 1) что уже размечено (руками и консенсусом) — не трогаем
    manual, prev_auto = {}, set()
    if os.path.exists(a.extra):
        for line in open(a.extra, encoding="utf-8"):
            p = line.rstrip("\n").split("\t")
            if len(p) < 2 or not p[1]:
                continue
            src = p[4] if len(p) >= 5 else "manual"
            if src == "auto":
                prev_auto.add(p[0])      # авто-строки перепроверяем заново
            else:
                manual[p[0]] = p[1]

    stats = {}
    rows = []
    for r in idx:
        f = r["file"]
        if f in manual:
            rows.append((f, manual[f], r["page"], "manual"))
            stats["уже было"] = stats.get("уже было", 0) + 1
            continue
        if only_pages and r["page"] not in only_pages:
            stats["не та страница"] = stats.get("не та страница", 0) + 1
            continue
        if r["page"] in UI_PAGES:
            stats["страница приложения"] = stats.get("страница приложения", 0) + 1
            continue
        text, why = check(r.get("guess", ""), float(r.get("conf") or 0), known, cache,
                          a.conf, rank)
        if text is None:
            stats[why] = stats.get(why, 0) + 1
            continue
        rows.append((f, text, r["page"], "auto"))
        stats["авто"] = stats.get("авто", 0) + 1

    pages = sorted({p for *_, p, _ in rows})
    val_pages = set(pages[::5])
    out = []
    for f, text, page, src in sorted(rows):
        split = "val" if page in val_pages else "train"
        out.append(f"{f}\t{text}\t{page}\t{split}\t{src or 'manual'}")
    print(dict(sorted(stats.items(), key=lambda kv: -kv[1])))
    print(f"строк с эталоном {len(out)} · страниц {len(pages)} · "
          f"проверочных {sum(1 for x in out if x.endswith('val\tmanual') or '\tval\t' in x)}")
    if a.write:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out) + "\n")
        print("→", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
