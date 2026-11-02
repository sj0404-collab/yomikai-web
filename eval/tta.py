"""Замер: несколько масштабов на чтеца + правила объединения гипотез.

Одна и та же строка на разной растяжке читается по-разному (на манге буквы
широкие, на маньхуа сжатые), поэтому масштабы дают разные ошибки. Вопрос —
сколько из них выжимается объединением и сколько стоит потолок набора.
"""
import sys
sys.path.insert(0, '/home/user/evalwork')
sys.path.insert(0, '/home/user/ownocr')
import gen
from ownocr.pair import CtcLineReader, cer, clean
from holdout import split

vocab = set(w.strip().upper() for w in
            open('/home/user/ownocr/ownocr/vocab-ru.txt', encoding='utf-8') if w.strip())
PUN = '.,!?…—«»"():;%'


def lex(t):
    s = 0
    for w in (t or '').split():
        k = w.strip(PUN).upper()
        if len(k) >= 3 and k in vocab:
            s += len(k)
    return s


tr, te = split()
readers = {n: CtcLineReader(p) for n, p in gen.MODELS.items() if n in ('hard', 'webtoon')}
SCALES = (0.8, 1.0, 1.25)
cands = {}
for it in te:
    key = str(it['i'])
    cands[key] = []
    for name, rd in readers.items():
        for s in SCALES:
            t, c = rd.read(it['gray'], stretch=s)
            cands[key].append({'m': f'{name}@{s}', 'text': t, 'conf': c})


def report(title, choose):
    acc = {k: [0, 0] for k in gen.CATS}
    for it in te:
        txt = choose(it, cands[str(it['i'])])
        c = cer(clean(it['text']), clean(txt))
        for k, f in gen.CATS.items():
            if f(it):
                acc[k][0] += c
                acc[k][1] += 1
    print(title.ljust(32) + ''.join(f'{100 * acc[k][0] / acc[k][1]:>11.1f}%' for k in gen.CATS))
    return acc


print('вариант'.ljust(32) + ''.join(f'{k:>11}' for k in gen.CATS))
report('hard @1.0 (как сейчас)', lambda it, cs: [c for c in cs if c['m'] == 'hard@1.0'][0]['text'])
report('hard: лучший масштаб', lambda it, cs: max(
    [c for c in cs if c['m'].startswith('hard')],
    key=lambda c: lex(c['text']) + 40 * c['conf'])['text'])
report('все 6 по словарю', lambda it, cs: max(cs, key=lambda c: lex(c['text']) + 40 * c['conf'])['text'])
report('все 6 по уверенности', lambda it, cs: max(cs, key=lambda c: c['conf'])['text'])
report('ПОТОЛОК из 6 (оракул)', lambda it, cs: min(
    cs, key=lambda c: cer(clean(it['text']), clean(c['text'])))['text'])
