"""Стоп-кран: сколько ошибок остаётся в строках, которые приложение принимает само.

Идея. CER 0,1 % на ВСЕХ строках не бывает ни у одного чтеца: даже лучшие движки
на чистой печати дают 1–3 %. Но можно разделить поток на две части:
  * строки, в которых несколько чтецов сошлись и слова проходят словарь, —
    отдавать автоматически (там CER измеряется отдельно);
  * строки, где чтецы разошлись или слова не словарные, — помечать в приложении
    как «проверь» и не озвучивать, пока человек не подтвердил.
Тогда «автоматически принятая» часть может иметь CER в районе 0,1 %, а остальное
не портит точность молча, а честно помечено.

Скрипт считает: согласие чтецов, уверенность, словарную проверку ↔ настоящий CER.
"""
import json
import sys

sys.path.insert(0, '/home/user/evalwork')
sys.path.insert(0, '/home/user/ownocr')
import gen                                          # noqa: E402
from ownocr.pair import CtcLineReader, cer, clean          # noqa: E402
from holdout import split                           # noqa: E402

VOCAB = set(w.strip().upper() for w in
            open('/home/user/ownocr/ownocr/vocab-ru.txt', encoding='utf-8') if w.strip())
PUN = '.,!?…—«»"():;%–-'


def lex_ok(text):
    """Доля слов, которые есть в словаре (для строк из 2+ буквенных слов)."""
    ws = [w.strip(PUN).upper() for w in (text or '').split()]
    ws = [w for w in ws if len(w) >= 2 and any(ch.isalpha() for ch in w)]
    if not ws:
        return 1.0                                  # «ЫЫЫ—», «?!» — словарю не подчиняются
    return sum(1 for w in ws if w in VOCAB) / len(ws)


def main():
    tr, te = split()
    names = ('gentle', 'webtoon', 'hard')
    readers = {n: CtcLineReader(gen.MODELS[n]) for n in names}
    rows = []
    for it in te:
        cands = {n: readers[n].read(it['gray']) for n in names}
        texts = [cands[n][0] for n in names]
        confs = [cands[n][1] for n in names]
        agree = sum(1 for t in texts if t == texts[0]) / len(texts)
        best = cands['gentle'][0]
        c = cer(clean(it['text']), clean(best))
        rows.append({'ref': it['text'], 'hyp': best, 'cer': c,
                     'conf': float(confs[0]), 'minconf': float(getattr(readers['gentle'], 'last_min_conf', 0.0)),
                     'agree': agree,
                     'lex': lex_ok(best), 'kind': it['kind'],
                     'h': it['h'], 'page': it['page']})
    json.dump(rows, open('/home/user/evalwork/gate_rows.json', 'w'), ensure_ascii=False)
    n = len(rows)
    print(f'строк {n} · CER всего {100*sum(r["cer"] for r in rows)/n:.1f} %')

    # 1. отсечка по согласию чтецов
    print('\nсогласие всех трёх чтецов:')
    for need in (1.0, 0.66):
        sub = [r for r in rows if r['agree'] >= need]
        if sub:
            print(f'  согласие ≥ {need:.2f}: строк {len(sub):3d} ({100*len(sub)/n:3.0f} %) '
                  f'· CER {100*sum(r["cer"] for r in sub)/len(sub):.2f} % '
                  f'· идеальных {100*sum(1 for r in sub if r["cer"]==0)/len(sub):.0f} %')

    # 2. согласие + словарь
    print('\nсогласие всех трёх И словарь ≥ 90 %:')
    for need in (1.0, 0.66):
        sub = [r for r in rows if r['agree'] >= need and r['lex'] >= 0.9]
        if sub:
            print(f'  строк {len(sub):3d} ({100*len(sub)/n:3.0f} %) · '
                  f'CER {100*sum(r["cer"] for r in sub)/len(sub):.2f} %')

    # 3. отсечка по уверенности (кривая «принято / CER»)
    print('\nотсечка по уверенности чтеца:')
    for th in (0.99, 0.95, 0.9, 0.8, 0.6, 0.0):
        sub = [r for r in rows if r['conf'] >= th]
        if sub:
            print(f'  уверенность ≥ {th:.2f}: принято {len(sub):3d} ({100*len(sub)/n:3.0f} %) · '
                  f'CER принятых {100*sum(r["cer"] for r in sub)/len(sub):.2f} %')

    # 4. где ошибается «принятая» часть — по видам
    sub = [r for r in rows if r['agree'] >= 1.0 and r['lex'] >= 0.9]
    bad = sorted([r for r in sub if r['cer'] > 0], key=lambda r: -r['cer'])[:15]
    print(f'\nошибки внутри «принятых» ({len([r for r in sub if r["cer"]>0])} строк):')
    for r in bad:
        print(f'  {r["cer"]:.2f} {r["page"]:12s} {r["ref"][:38]!r} → {r["hyp"][:38]!r}')


if __name__ == '__main__':
    main()
