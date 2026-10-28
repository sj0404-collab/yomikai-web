# ЭТАЛОН алгоритма, который повторяет OcrEngine.kt (Kotlin).
#
# Зачем: нативный движок пишется под Android, а Android в песочнице нет — но
# модели-то настоящие. Этот файл делает РОВНО те же шаги (детектор → компоненты
# → нарезка блока на строки → распознавание кропа → жадный CTC), поэтому по нему
# видно, что алгоритм верен, ещё до сборки АПК. Если правка в Kotlin меняет
# смысл шага, правьте и здесь — и прогоняйте:
#
#   pip install onnxruntime pillow numpy
#   python3 apk/tools/native_ocr_reference.py путь/к/странице.jpg
#
# Замер на странице из скриншота 28.10: реплики читаются как «УЖЕ ПОРА НА- /
# ЧИНАТЬ ВСТРЕЧУ, / ТАК ЧТО ЕЁ ВЫСО- / ЧЕСТВО, ДОЛЖНО / БЫТЬ, ПРИБЫЛА.» —
# то есть тот же текст, что давал WASM-путь, без потери строк.
import math, sys
import numpy as np
import onnxruntime as ort
from PIL import Image

MODELS='/home/user/koma_models'
det=ort.InferenceSession(MODELS+'/koma_det.onnx', providers=['CPUExecutionProvider'])
rec=ort.InferenceSession(MODELS+'/koma_rec.onnx', providers=['CPUExecutionProvider'])
chars=[l.rstrip('\r') for l in open(MODELS+'/koma_dict.txt', encoding='utf-8').read().split('\n')]
while chars and chars[-1]=='': chars.pop()
chars=['']+chars+[' ']
print('классов в азбуке:', len(chars))

def detect(img, side=1600, retry=True):
    w0,h0=img.size
    ratio=min(1.0, side/max(w0,h0))
    w=max(32, int(round(w0*ratio/32))*32); h=max(32, int(round(h0*ratio/32))*32)
    im=img.convert('RGB').resize((w,h), Image.BILINEAR)
    a=np.asarray(im).astype(np.float32)/255.0            # H,W,3
    def run(normalize):
        if normalize:
            mean=np.array([0.485,0.456,0.406],np.float32); std=np.array([0.229,0.224,0.225],np.float32)
            x=(a-mean)/std
        else:
            x=a
        x=np.transpose(x,(2,0,1))[None]                   # 1,3,H,W
        y=det.run(None, {det.get_inputs()[0].name: x})[0][0][0]
        return components(y, h, w)
    boxes=run(False)
    if not boxes and retry: boxes=run(True)
    out=[]
    for (l,t,r,b) in boxes[:400]:
        L=max(0,min(w0-1,int(round(l/w*w0)))); T=max(0,min(h0-1,int(round(t/h*h0))))
        R=max(0,min(w0,int(round(r/w*w0)))); B=max(0,min(h0,int(round(b/h*h0))))
        if R>L and B>T: out.append((L,T,R,B))
    return out

def components(m, h, w, thr=0.3):
    vis=np.zeros((h,w),bool); boxes=[]
    idx=np.argwhere(m>=thr)
    for (y,x) in idx:
        if vis[y,x]: continue
        stack=[(y,x)]; vis[y,x]=True
        minX=maxX=x; minY=maxY=y; score=0.0; cnt=0
        while stack:
            cy,cx=stack.pop(); cnt+=1; score+=m[cy,cx]
            minX=min(minX,cx); maxX=max(maxX,cx); minY=min(minY,cy); maxY=max(maxY,cy)
            for ny,nx in ((cy-1,cx),(cy+1,cx),(cy,cx-1),(cy,cx+1)):
                if 0<=ny<h and 0<=nx<w and not vis[ny,nx] and m[ny,nx]>thr:
                    vis[ny,nx]=True; stack.append((ny,nx))
        if cnt<6 or score/cnt<0.5 or maxX-minX<2 or maxY-minY<2: continue
        exp=max(2, int(round(((maxX-minX)*(maxY-minY)*1.5)/(2*(maxX-minX+maxY-minY+1)))))
        boxes.append((max(0,minX-exp), max(0,minY-exp), min(w,maxX+exp+1), min(h,maxY+exp+1)))
    return sorted(boxes, key=lambda b:b[1])

def ink_threshold(luma, lowp=0.02, highp=0.98, flats=10, coef=0.45, lo=40, hi=235):
    hist=np.bincount(luma.ravel(), minlength=256)
    def pct(p):
        target=max(1,int(luma.size*p)); acc=0
        for i in range(256):
            acc+=hist[i]
            if acc>=target: return i
        return 255
    low=pct(lowp); high=pct(highp)
    if high-low<flats: return -1
    return max(lo, min(hi, int(round(low+(high-low)*coef))))

def text_lines(img, box, tile_rows=4):
    l,t,r,b=box
    pad=max(2,int((b-t)*0.12))
    L=max(0,l-pad); R=min(img.width,r+pad); T=max(0,t-pad); B=min(img.height,b+pad)
    if R-L<4 or B-T<4: return []
    scale=min(1.0, 400.0/(R-L))
    w=max(4,int(round((R-L)*scale))); h=max(4,int(round((B-T)*scale)))
    crop=img.crop((L,T,R,B)).convert('L').resize((w,h), Image.BILINEAR)
    luma=np.asarray(crop).astype(np.int32)
    if ink_threshold(luma)<0: return []
    rows=max(1,min(16,tile_rows)); tile=max(1, math.ceil(h/rows))
    thr=[]
    for i in range(rows):
        y0=i*tile; y1=min(h,y0+tile)
        thr.append(-1 if y1<=y0 else ink_threshold(luma[y0:y1,:]))
    def thrAt(y): return thr[max(0,min(rows-1,y//tile))]
    need=max(1,w//60)
    def has(y):
        return int((luma[y] < thrAt(y)).sum())>=need
    runs=[]; y=0
    while y<h:
        if not has(y): y+=1; continue
        e=y
        while e<h and has(e): e+=1
        if e>y: runs.append([y,e])
        y=max(e,y+1)
    if not runs: return []
    hs=sorted([r[1]-r[0] for r in runs]); med=max(1,hs[len(hs)//2])
    merged=[]
    for r in runs:
        if merged and r[0]-merged[-1][1] <= max(1,int(med*0.35)): merged[-1][1]=r[1]
        else: merged.append(list(r))
    lines=[]
    for r in merged:
        if r[1]-r[0] < max(2,int(med*0.4)): continue
        seg=luma[r[0]:r[1],:]
        mask=seg < np.array([thrAt(y) for y in range(r[0],r[1])])[:,None]
        xs=np.where(mask.any(axis=0))[0]
        if not len(xs): continue
        x0,x1=xs[0],xs[-1]
        lines.append((int(L+x0/scale), int(T+r[0]/scale), int(L+(x1+1)/scale), int(T+(r[1]+1)/scale)))
    return lines

def decode(crop):
    if crop.height > crop.width*1.8: crop=crop.rotate(-90, expand=True)
    w0,h0=crop.size
    if w0<2 or h0<2: return '',0.0
    width=max(8,min(960,int(round(48*w0/h0)))); padded=max(320,width)
    im=crop.convert('RGB').resize((width,48), Image.BILINEAR)
    a=np.asarray(im).astype(np.float32)/255.0
    f=np.full((48,padded,3), -1.0, np.float32)
    f[:,:width,:]=(a-0.5)/0.5
    x=np.transpose(f,(2,0,1))[None]
    y=rec.run(None, {rec.get_inputs()[0].name: x})[0][0]     # T,C
    idx=y.argmax(axis=1)
    text=''; prev=0; score=0.0; count=0
    for ti,best in enumerate(idx):
        if best!=0 and best!=prev:
            if best < len(chars): text+=chars[best]
            score+=float(y[ti,best]); count+=1
        prev=best
    return text, (score/count if count else 0.0)

def recognize(path, max_side=1600):
    img=Image.open(path).convert('RGB')
    if max(img.size)>max_side:
        k=max_side/max(img.size); img=img.resize((int(img.width*k), int(img.height*k)), Image.BILINEAR)
    boxes=detect(img)
    out=[]
    for box in boxes:
        lines=text_lines(img, box) or [box]
        for ln in lines:
            crop=img.crop(ln)
            text,conf=decode(crop)
            if text.strip() and conf>0.25: out.append((text.strip(), round(conf,2), ln))
    return out

if __name__=='__main__':
    res=recognize(sys.argv[1])
    print(f'строк: {len(res)}')
    for t,c,ln in res: print(f'  [{c}] {t}')
