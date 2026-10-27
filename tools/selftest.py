"""Быстрая самопроверка инструментов (без torch и без сети) — то, что гоняет CI.

  python3 tools/selftest.py

Проверяет: азбуку и раскладку классов, вшитый словарь (487 247 строк, md5),
синтетический рендер (форма, ширина кратна 8, буквы из азбуки), сборку html
(если рядом лежат части).
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

RAISE = []
CHECKS = [0]


def ck(name: str, cond: bool, detail: str = ""):
    CHECKS[0] += 1
    print(f"{'  ok ' if cond else '  ПАДЕНИЕ'} {name}{(' — ' + detail) if detail else ''}")
    if not cond:
        RAISE.append(name)


def main():
    print("── азбука ─────────────────────────────────────────────")
    from charset import char_to_class, classes_to_text, load_charset, num_classes
    cs = load_charset()
    ck("символов 517", len(cs) == 517, str(len(cs)))
    ck("классов 519 (blank + 517 + «неизвестно»)", num_classes(cs) == 519, str(num_classes(cs)))
    ck("«А» в классе 442", char_to_class(cs)["А"] == 442, str(char_to_class(cs)["А"]))
    ck("жадный разбор: повторы без blank схлопываются",
       classes_to_text(cs, [1, 1, 0, 2]) == cs[0] + cs[1])
    ck("жадный разбор: blank разделяет одинаковые буквы",
       classes_to_text(cs, [1, 0, 1]) == cs[0] * 2)
    ck("класс 518 — пробел", classes_to_text(cs, [1, 518, 2]) == cs[0] + " " + cs[1])

    print("── вшитый словарь ─────────────────────────────────────")
    js = os.path.join(REPO, "part0-dict.js")
    if os.path.exists(js):
        m = re.search(r"const DICT_GZ_B64 = '([^']+)'", open(js, encoding="utf-8").read())
        ck("DICT_GZ_B64 на месте", bool(m))
        if m:
            text = gzip.decompress(base64.b64decode(m.group(1))).decode("utf-8")
            md5 = hashlib.md5(text.encode("utf-8")).hexdigest()
            want = ""
            p = os.path.join(HERE, "dict_md5.txt")
            if os.path.exists(p):
                want = open(p).read().strip()
            ck("строк 487 247", text.count("\n") == 487247, str(text.count("\n")))
            ck("md5 совпал с tools/dict_md5.txt", md5 == want, md5)
            first = [line.split()[0] for line in text.split("\n")[:5]]
            ck("частотный блок впереди", first[:2] == ["я", "не"], str(first[:2]))
    else:
        ck("part0-dict.js на месте", False, "нет файла — словарь не проверить")

    print("── синтетический рендер ───────────────────────────────")
    try:
        import synth
        r = synth.LineRenderer(synth.load_words(2000), cs, hard=0.4, max_chars=12)
        rng = random.Random(7)
        ok_shape, ok_pad, ok_chars, texts = True, True, True, []
        for _ in range(12):
            x, t = r.render(rng)
            ok_shape &= (x.shape[0] == 3 and x.shape[1] == 48)
            ok_pad &= (x.shape[2] % 8 == 0 and 128 <= x.shape[2] <= 320)
            ok_chars &= all(c in cs for c in t)
            texts.append(t)
        ck("картинка 3×48×W, W кратно 8", ok_shape and ok_pad)
        ck("буквы эталона есть в азбуке", ok_chars)
        ck("серый хвост = 0 в нормировке", abs(float(x[0, 0, -1])) < 1e-6)
        print("     примеры:", ", ".join(texts[:4]))
    except SystemExit as e:                                   # нет шрифтов
        ck("шрифты с кириллицей", False, str(e))

    print("── сборка html ────────────────────────────────────────")
    parts = ["part1.html", "part0-ort.js", "part0-wasm.js", "part0-dict.js",
             "part2.js", "part3.js", "part4.js", "part5.js"]
    missing = [p for p in parts if not os.path.exists(os.path.join(REPO, p))]
    ck("все части сборки на месте", not missing, ", ".join(missing))

    print(f"\nвсего проверок {CHECKS[0]}, падений {len(RAISE)}")
    return 1 if RAISE else 0


if __name__ == "__main__":
    sys.exit(main())
