"""Голосование шести чтецов + отсечка: сколько строк можно принять без правки.

Мерим то, что реально важно для приложения: не «средний CER по всем строкам», а
CER у той части, которую приложение отдаёт само, и долю таких строк.
Строки, где чтецы расходятся, помечаются «проверь» — их видно, но голосом не
читаются, пока человек не подтвердил.
"""
import json
import sys
from collections import Counter

sys.path.insert(0, '/home/user/evalwork')
sys.path.insert(0, '/home/user/ownocr')
import gen                                              # noqa: E402
from ownocr.pair import CtcLineReader, cer, clean       # noqa: E402
from holdout import split                               # noqa: E402

VOCAB = set(w.strip().upper() for w in
            open('/home/user/ownocr/ownocr/vocab-ru.txt', encoding='utf-8') if w.strip())
PUN = '.,!?…—«»"():;%–-'


def lex(text):
    ws = [w.strip(PUN).upper() for w in (text or '').split()]
    ws = [w for w in ws if len(w) >= 2 and any(ch.isalpha() for ch in w)]
    if not ws:
        return 1.0
    return sum(1 for w in ws if w in VOCAB) / len(ws)


NAMES = ('gentle', 'hard', 'webtoon', 'ftall', 'comic', 'ft')
PATHS = dict(gen.MODELS)
PATHS['comic'] = '/home/user/web-ocr/models/eslav-comic.onnx'
PATHS['ft'] = '/home/user/web-ocr/models/eslav-ft.onnx'


def main():
    tr, te = split()
    readers = {n: CtcLineReader(PATHS[n]) for n in NAMES}
    rows = []
    for it in te:
        cands = {}
        for n in NAMES:
            t, c = readers[n].read(it['gray'])
            cands[n] = (t, c, float(getattr(readers[n], 'last_min_conf', 0.0)))
        # голосование по точным совпадениям текстов
        cnt = Counter(cands[n][0] for n in NAMES)
        top, sup = cnt.most_common(1)[0]
        # при равенстве голосов берём прочтение gentle
        if list(cnt.values()).count(sup) > 1 and cands['gentle'][0] in cnt:
            top = cands['gentle'][0]
            sup = cnt[top]
        rows.append({
            'ref': it['text'], 'vote': top, 'sup': sup, 'n': len(NAMES),
            'cer': cer(clean(it['text']), clean(top)),
            'cer_gentle': cer(clean(it['text']), clean(cands['gentle'][0])),
            'lex': lex(top), 'kind': it['kind'], 'h': it['h'], 'page': it['page'],
            'conf': cands['gentle'][1], 'minconf': max(cands[n][2] for n in NAMES),
        })
    json.dump(rows, open('/home/user/evalwork/gate6_rows.json', 'w'), ensure_ascii=False)

    # другие правила выбора из тех же кандидатов (без повторного чтения)
    tr2 = []
    for it, r in zip(te, rows):
        pass


    n = len(rows)
    a = sum(r['cer'] for r in rows) / n
    ag = sum(r['cer_gentle'] for r in rows) / n
    print(f'строк {n}: CER только gentle {100*ag:.2f} % · после голосования 6 чтецов {100*a:.2f} %')

    print('\nпорог по числу согласных чтецов (из 6):')
    print('  порог  принято     CER принятых   из них без ошибок')
    for need in (6, 5, 4, 3):
        sub = [r for r in rows if r['sup'] >= need]
        if not sub:
            continue
        print(f'  {need}/6   {len(sub):3d} ({100*len(sub)/n:3.0f} %)   '
              f'{100*sum(r["cer"] for r in sub)/len(sub):6.2f} %          '
              f'{100*sum(1 for r in sub if r["cer"]==0)/len(sub):3.0f} %')

    print('\nсо словарём (все слова известны, если их 2+):')
    for need in (6, 5, 4, 3):
        sub = [r for r in rows if r['sup'] >= need and r['lex'] >= 1.0]
        if not sub:
            continue
        print(f'  {need}/6 + словарь  {len(sub):3d} ({100*len(sub)/n:3.0f} %)   '
              f'{100*sum(r["cer"] for r in sub)/len(sub):6.2f} %          '
              f'{100*sum(1 for r in sub if r["cer"]==0)/len(sub):3.0f} %')

    print('\nуверенность (мин. по буквам, максимум по чтецам):')
    for th in (0.9, 0.8, 0.6, 0.4):
        sub = [r for r in rows if r['minconf'] >= th]
        if sub:
            print(f'  ≥ {th:.1f}: {len(sub):3d} ({100*len(sub)/n:3.0f} %) · '
                  f'CER {100*sum(r["cer"] for r in sub)/len(sub):.2f} %')

    print('\nошибки внутри принятого 4/6 + словарь:')
    for r in sorted([r for r in rows if r['sup'] >= 4 and r['lex'] >= 1.0 and r['cer'] > 0],
                    key=lambda r: -r['cer'])[:10]:
        print(f'  {r["cer"]:.2f} {r["page"]:12s} {r["ref"][:40]!r} → {r["vote"][:40]!r}')


if __name__ == '__main__':
    main()
