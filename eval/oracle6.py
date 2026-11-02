"""Потолок: лучшее прочтение каждой строки среди 6 чтецов (верхняя оценка выбора)."""
import sys
sys.path.insert(0,'/home/user/evalwork'); sys.path.insert(0,'/home/user/ownocr')
import gen
from ownocr.pair import CtcLineReader, cer, clean
from holdout import split
NAMES=('gentle','hard','webtoon','ftall','comic','ft')
PATHS=dict(gen.MODELS); PATHS['comic']='/home/user/web-ocr/models/eslav-comic.onnx'; PATHS['ft']='/home/user/web-ocr/models/eslav-ft.onnx'
tr,te=split()
rd={n:CtcLineReader(PATHS[n]) for n in NAMES}
per={n:0.0 for n in NAMES}; oracle=0.0; perfect=0
for it in te:
    best=1.0
    for n in NAMES:
        t=rd[n].read(it['gray'])[0]
        c=cer(clean(it['text']),clean(t)); per[n]+=c; best=min(best,c)
    oracle+=best; perfect+=(best==0)
n=len(te)
for k in NAMES: print(f'  {k:8s} {100*per[k]/n:5.2f} %')
print(f'потолок (лучшее из шести на каждой строке): {100*oracle/n:.2f} % · строк без ошибок {100*perfect/n:.0f} %')
