"""СБОРКА СЛОВАРЯ, который вшит в приложение (part0-dict.js) — воспроизводимо.

Словарь = 250 000 частотных слов + словоформы лемм первых 60 000 слов
(склонения и спряжения, которых в частотном списке нет). Итог — 487 247 строк,
11,1 МБ готового part0-dict.js, старт словаря в браузере ~490 мс.

  # собрать текст словаря и сверить с тем, что уже лежит в репозитории
  python3 tools/build_dict.py --check

  # пересобрать part0-dict.js (и заодно текст)
  python3 tools/build_dict.py --write

Почему именно так (замеры 27.10, /tmp/probe_ab_embed.py на настоящих строках):

  | словарь | CER b1–b4 | part0-dict.js | старт | память |
  |---|---|---|---|---|
  | 250k | 13,4 % | 10,1 МБ | 259 мс | +21 МБ |
  | 487k (этот) | 11,7 % | 11,1 МБ | 490 мс | +42 МБ |
  | 841k | 11,7 % | 12,5 МБ | 996 мс | +76 МБ |
  | 1,5 млн | 11,7 % | 15,0 МБ | 1923 мс | +210 МБ |

То есть словоформы дают −1,7 п.п. бесплатно, а всё, что больше 487k, — те же
11,7 % за втрое более долгий старт. Словоформы стоят ПОСЛЕ частотного списка:
пороги сравнивают номер строки, и «частых» слов из них не получается.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

DEFAULT_FREQ = os.path.join(REPO, "data", "ru_250k.txt")
CYR = re.compile(r"^[а-яё-]+$")


def read_freq(path: str, top: int) -> list:
    """Первые top строк частотного списка, слово — первый столбец.

    ВАЖНО: фильтра по «только кириллица» здесь нет — частотный блок вшитого
    словаря повторяет исходный список побайтово (это проверяет
    test-dict-embed.cjs), поэтому отбрасывать ничего нельзя. На замере 27.10
    такой фильтр срезал 16 613 строк (250 000 → 233 387) и весь md5 разъезжался.
    """
    words = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            words.append(line.split()[0].strip())
            if len(words) >= top:
                break
    if not words:
        raise SystemExit(f"{path}: пусто")
    return words


def build_forms(freq: list, lemma_top: int) -> list:
    """Словоформы лемм первых lemma_top слов; отсортированы, без дублей."""
    try:
        import pymorphy3
    except ImportError:
        raise SystemExit("нужен pymorphy3: pip install pymorphy3 (см. tools/requirements.txt)")
    morph = pymorphy3.MorphAnalyzer()
    have = set(freq)
    lemmas, seen = [], set()
    for w in freq[:lemma_top]:
        lem = morph.parse(w)[0].normal_form
        if lem not in seen:
            seen.add(lem)
            lemmas.append(lem)
    forms = set()
    for lem in lemmas:
        # Только ПЕРВЫЙ разбор леммы: с «всеми разборами» словоформ выходит
        # 288 591 вместо 237 247 — лишние 51 344 строки стоили бы +0,9 МБ
        # файла и ничего не дали на замере.
        for f in morph.parse(lem)[0].lexeme:
            forms.add(f.word)
    new = [w for w in forms if w not in have and CYR.match(w) and len(w) >= 2]
    new.sort()
    return new


def dict_text(freq: list, forms: list, freq_path: str) -> str:
    """Текст словаря: «слово частота» для частотных, просто «слово» для словоформ."""
    out = []
    with open(freq_path, encoding="utf-8") as f:
        rows = [line.rstrip("\n") for line in f if line.strip()]
    for line in rows[:len(freq)]:
        out.append(line)
    out.extend(forms)
    return "\n".join(out) + "\n"


def embed(text: str, mtime: int = 0, level: int = 9) -> str:
    """gzip (с заданным mtime — чтобы файл получался байт в байт) + base64."""
    comp = gzip.compress(text.encode("utf-8"), compresslevel=level, mtime=mtime)
    return base64.b64encode(comp).decode("ascii")


def read_js(path: str):
    s = open(path, encoding="utf-8").read()
    m = re.search(r"const DICT_GZ_B64 = '", s)
    if not m:
        raise SystemExit(f"{path}: нет DICT_GZ_B64")
    head = s[:m.start()]
    rest = s[m.end():]
    end = rest.index("'\n")
    return head, rest[:end], rest[end + 2:]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Сборка вшитого словаря (487 247 слов)")
    ap.add_argument("--freq", default=DEFAULT_FREQ, help="частотный список «слово частота»")
    ap.add_argument("--top", type=int, default=250000)
    ap.add_argument("--lemma-top", type=int, default=60000)
    ap.add_argument("--text-out", default=os.path.join(REPO, "data", "dict_ru.txt"))
    ap.add_argument("--js-out", default=os.path.join(REPO, "part0-dict.js"))
    ap.add_argument("--check", action="store_true", help="только сверить, ничего не писать")
    ap.add_argument("--write", action="store_true", help="перезаписать словарь и part0-dict.js")
    a = ap.parse_args(argv)

    if not os.path.exists(a.freq):
        raise SystemExit(f"нет частотного списка {a.freq}\n"
                         f"Он лежит в репозитории: data/ru_250k.txt "
                         f"(hermitdave/FrequencyWords, ru 2018, MIT)")
    freq = read_freq(a.freq, a.top)
    forms = build_forms(freq, a.lemma_top)
    text = dict_text(freq, forms, a.freq)
    md5 = hashlib.md5(text.encode("utf-8")).hexdigest()
    lines = text.count("\n")
    print(f"частотных {len(freq)} · словоформ {len(forms)} · всего строк {lines}")
    print(f"текст словаря: {len(text.encode('utf-8'))/1e6:.2f} МБ · md5 {md5}")

    if os.path.exists(a.js_out):
        _, b64, _ = read_js(a.js_out)
        cur = gzip.decompress(base64.b64decode(b64)).decode("utf-8")
        cur_md5 = hashlib.md5(cur.encode("utf-8")).hexdigest()
        same = cur_md5 == md5
        print(f"во вшитом part0-dict.js: {cur.count(chr(10))} строк · md5 {cur_md5} · "
              f"{'СОВПАЛО' if same else 'РАСХОЖДЕНИЕ'}")
        if not same and a.check:
            return 1

    if not a.write:
        print("(ничего не записано; для перезаписи — --write)")
        return 0

    head, _, tail = read_js(a.js_out)
    # mtime берём из текущего файла — иначе gzip-заголовок отличается и файл
    # получается «как бы другой», хотя текст тот же
    mtime = 0
    if os.path.exists(a.js_out):
        try:
            mtime = int.from_bytes(base64.b64decode(read_js(a.js_out)[1])[4:8], "little")
        except Exception:                                            # noqa: BLE001
            mtime = 0
    b64 = embed(text, mtime=mtime)
    os.makedirs(os.path.dirname(os.path.abspath(a.text_out)) or ".", exist_ok=True)
    with open(a.text_out, "w", encoding="utf-8") as f:
        f.write(text)
    with open(a.js_out, "w", encoding="utf-8") as f:
        f.write(head + "const DICT_GZ_B64 = '" + b64 + "'\n" + tail)
    new_md5 = hashlib.md5(open(a.js_out, "rb").read()).hexdigest()
    print(f"записано: {a.text_out} и {a.js_out} ({os.path.getsize(a.js_out)/1e6:.2f} МБ, "
          f"md5 файла {new_md5})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
