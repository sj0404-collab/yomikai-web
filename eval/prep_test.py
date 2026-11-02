import sys; sys.path.insert(0,'/home/user/evalwork'); sys.path.insert(0,'/home/user/ownocr')
import numpy as np, cv2, gen
from ownocr.pair import CtcLineReader, cer, clean

def sauvola(g, k=0.2):
    h,w=g.shape; win=max(7,(h//2)|1); win+= (win%2==0)
    f=g.astype(np.float32)
    m=cv2.boxFilter(f,-1,(win,win)); m2=cv2.boxFilter(f*f,-1,(win,win))
    s=np.sqrt(np.maximum(m2-m*m,0)); t=m*(1+k*(s/128-1))
    return np.where(g<t,0,255).astype(np.uint8)

def fill_holes(bw):
    h,w=bw.shape; ff=bw.copy(); mask=np.zeros((h+2,w+2),np.uint8)
    cv2.floodFill(ff,mask,(0,0),0)
    holes=cv2.bitwise_not(ff)
    return cv2.bitwise_and(bw, cv2.bitwise_not(holes))

def thr_otsu(g): return cv2.threshold(g,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1]
K=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2,2))
V={'как есть':lambda g:g,
   'sauvola':lambda g:sauvola(g),
   'sauvola+заливка':lambda g:fill_holes(sauvola(g)),
   'sauvola+утолщ':lambda g:cv2.erode(fill_holes(sauvola(g)),K),
   'otsu+заливка':lambda g:fill_holes(thr_otsu(g))}
readers={k:CtcLineReader(v) for k,v in gen.MODELS.items() if k in ('webtoon','hard')}
rows=list(gen.items())
print('вариант'.ljust(26)+''.join(f'{k:>13}' for k in gen.CATS))
for vname,fn in V.items():
    for mname,rd in readers.items():
        acc={k:[0,0] for k in gen.CATS}
        for it in rows:
            try: got=rd.read(fn(it['gray']))[0]
            except Exception: got=''
            c=cer(clean(it['text']), clean(got))
            for k,f in gen.CATS.items():
                if f(it): acc[k][0]+=c; acc[k][1]+=1
        print(f'{mname}/{vname}'.ljust(26)+''.join(f'{100*acc[k][0]/acc[k][1]:>12.1f}%' for k in gen.CATS))
