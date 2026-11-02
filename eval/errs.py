import sys
sys.path.insert(0,'/home/user/evalwork'); sys.path.insert(0,'/home/user/ownocr')
import gen
from ownocr.pair import CtcLineReader, cer, clean
from holdout import split
tr,te=split()
rd=CtcLineReader(gen.MODELS['hard'])
rows=[]
for it in te:
    got=rd.read(it['gray'])[0]
    c=cer(clean(it['text']), clean(got))
    rows.append((c, it, got))
rows.sort(key=lambda r:-r[0])
print(f'{"CER":>5} {"страница":10} {"выс":>4}  эталон / прочтение')
for c,it,got in rows[:26]:
    print(f'{100*c:5.0f} {it["page"]:10} {it["h"]:4}  {it["text"][:46]!r} → {got[:46]!r}')
print()
import statistics
print('медиана CER:', round(100*statistics.median(r[0] for r in rows),1),'%',
      '· доля строк с CER>0.5:', round(100*sum(1 for r in rows if r[0]>0.5)/len(rows)),'%')
print('доля идеальных:', round(100*sum(1 for r in rows if r[0]==0)/len(rows)),'%')
