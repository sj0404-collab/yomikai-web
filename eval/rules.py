"""Правила выбора гипотезы из 6 чтецов — считается один раз, сравниваются правила."""
import sys, json
from collections import Counter
sys.path.insert(0,'/home/user/evalwork'); sys.path.insert(0,'/home/user/ownocr')
import gen
from ownocr.pair import CtcLineReader, cer, clean
from holdout import split
VOCAB=set(w.strip().upper() for w in open('/home/user/ownocr/ownocr/vocab-ru.txt',encoding='utf-8') if w.strip())
PUN='.,!?…—«»"():;%–-'
NAMES=('gentle','hard','webtoon','ftall','comic','ft')
PATHS=dict(gen.MODELS); PATHS['comic']='/home/user/web-ocr/models/eslav-comic.onnx'; PATHS['ft']='/home/user/web-ocr/models/eslav-ft.onnx'
def lexw(t):
    s=0
    for w in (t or '').split():
        k=w.strip(PUN).upper()
        if len(k)>=3 and k in VOCAB: s+=len(k)
    return s
tr,te=split()
readers={n:CtcLineReader(PATHS[n]) for n in NAMES}
data=[]
for it in te:
    cands=[(n,)+readers[n].read(it['gray'])+(float(getattr(readers[n],'last_min_conf',0.0)),) for n in NAMES]
    data.append((it,cands))
def report(title,f):
    tot=0.0; perfect=0
    for it,c in data:
        got=f(c)
        v=cer(clean(it['text']),clean(got)); tot+=v; perfect+= (v==0)
    print(f'{title:38s} CER {100*tot/len(data):5.2f} %  · без ошибок {100*perfect/len(data):3.0f} %')
report('gentle',lambda c:c[0][1])
report('большинство, при равенстве gentle',lambda c:Counter(x[1] for x in c).most_common(1)[0][0])
def lexfirst(c):
    best={}
    for n,t,cf,mc in c:
        best.setdefault(t,[]).append(lexw(t))
    return max(best, key=lambda t:(max(best[t]), Counter(x[1] for x in c)[t])) 
report('словарь, при равенстве большинство',lexfirst)
def lex_sup(c):
    sup=Counter(x[1] for x in c)
    return max(sup, key=lambda t:(sup[t], lexw(t), len(t)))
report('большинство, при равенстве словарь',lex_sup)
def lex_sup_len(c):
    sup=Counter(x[1] for x in c)
    return max(sup, key=lambda t:(sup[t], lexw(t)/max(1,len(t)), len(t)))
report('большинство, затем доля словарных',lex_sup_len)
