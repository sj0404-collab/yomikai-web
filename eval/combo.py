"""Замер связки: новый чтец (gentle) + вебтун + прежний «трудный».

Считаем честно: страницы проверки целиком вне обучения, ничего из них в
обучении не участвовало.
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


MODELS = {
    'gentle': '/home/user/ownocr/out/eslav-gentle.onnx',
    'hard': '/home/user/ownocr/model/eslav/eslav-hard.onnx',
    'webtoon': '/home/user/ownocr/model/eslav/eslav-webtoon.onnx',
    'ftall': '/home/user/ownocr/model/eslav/eslav-ft-all.onnx',
}
tr, te = split()
rd = {k: CtcLineReader(v) for k, v in MODELS.items()}
hyp = {}
for it in te:
    hyp[str(it['i'])] = {k: r.read(it['gray']) for k, r in rd.items()}


def report(title, choose):
    acc = {k: [0, 0] for k in gen.CATS}
    for it in te:
        txt = choose(it)
        c = cer(clean(it['text']), clean(txt))
        for k, f in gen.CATS.items():
            if f(it):
                acc[k][0] += c
                acc[k][1] += 1
    print(title.ljust(36) + ''.join(f'{100 * acc[k][0] / acc[k][1]:>11.1f}%' for k in gen.CATS))
    return acc['всё'][0] / acc['всё'][1]


print('вариант'.ljust(36) + ''.join(f'{k:>11}' for k in gen.CATS))
for m in MODELS:
    report(m, lambda it, m=m: hyp[str(it['i'])][m][0])
report('выбор: gentle+webtoon', lambda it: max(
    ['gentle', 'webtoon'], key=lambda m: lex(hyp[str(it['i'])][m][0]) + 40 * hyp[str(it['i'])][m][1]
).__class__ and
    (lambda c: max(c, key=lambda m: lex(hyp[str(it['i'])][m][0]) + 40 * hyp[str(it['i'])][m][1])[0])(
        ['gentle', 'webtoon'])
    and hyp[str(it['i'])][max(['gentle', 'webtoon'],
           key=lambda m: lex(hyp[str(it['i'])][m][0]) + 40 * hyp[str(it['i'])][m][1])][0])


def pick(names):
    def f(it):
        h = hyp[str(it['i'])]
        return h[max(names, key=lambda m: lex(h[m][0]) + 40 * h[m][1])][0]
    return f


report('выбор: gentle+hard+webtoon', pick(['gentle', 'hard', 'webtoon']))
report('выбор: все четыре', pick(['gentle', 'hard', 'webtoon', 'ftall']))
report('ПОТОЛОК по строкам (4)', lambda it: min(
    (hyp[str(it['i'])][m][0] for m in MODELS),
    key=lambda t: cer(clean(it['text']), clean(t))))
