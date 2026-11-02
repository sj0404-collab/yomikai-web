"""Что делать со спорными строками: подсказка «по словарю» внутри них."""
import sys
from collections import Counter
sys.path.insert(0,'/home/user/evalwork'); sys.path.insert(0,'/home/user/ownocr')
import gen
from ownocr.pair import CtcLineReader, cer, clean
from holdout import split
VOCAB=set(w.strip().upper() for w in open('/home/user/ownocr/ownocr/vocab-ru.txt',encoding='utf-8') if w.strip())
PUN='.,!?…—«»"():;%–-'
NAMES=('gentle','hard','webtoon')
PATHS=dict(gen.MODELS)
def lexw(t):
    return sum(len(w.strip(PUN)) for w in (t or '').split() if len(w.strip(PUN))>=3 and w.strip(PUN).upper() in VOCAB)
tr,te=split()
rd={n:CtcLineReader(PATHS[n]) for n in NAMES}
acc_a=acc_b=0.0; n_f=0; n_ok=0; nfix=0
for it in te:
    c=[rd[n].read(it['gray'])[0] for n in NAMES]
    sup=Counter(c)
    top, s = sup.most_common(1)[0]
    if s>=3:   # принято: чтецы сошлись
        acc_a+=cer(clean(it['text']),clean(top)); n_ok+=1
        continue
    n_f+=1
    # спорная строка: gentle против остальных — берём лучший по словарю
    alt=max(c, key=lexw)
    if alt!=c[0] and lexw(alt)>lexw(c[0]): nfix+=1
    acc_b+=cer(clean(it['text']),clean(alt))
print(f'принято (сошлись все три): {n_ok} строк · CER {100*acc_a/n_ok:.2f} %')
print(f'спорных: {n_f} строк · CER если ничего не делать — см. ниже')
print(f'  после выбора по словарю внутри спорных: CER {100*acc_b/n_f:.2f} % · подсказка изменила {nfix} строк')
