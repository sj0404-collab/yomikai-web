"""Честный протокол замера: страницы целиком делятся на обучение и проверку.

183 размеченные строки собраны с 13 страниц, и все они были в обучении базовых
моделей — значит 11,9 % на них ЗАВЫШЕНЫ. Здесь проверочные страницы выведены
из обучения целиком, чтобы цифра была честной.
"""
import sys; sys.path.insert(0,'/home/user/evalwork'); sys.path.insert(0,'/home/user/ownocr')
import json, cv2, numpy as np
import gen
from ownocr.pair import cer, clean

# рукописные/рисованные страницы — в проверку; печатная манга — тоже, чтобы не подгонять
HOLDOUT = {'comic4','comic3','manhua2','manhua5','manhua1','comic2','kuro-p2'}

def split():
    rows=list(gen.items())
    test=[r for r in rows if r['page'] in HOLDOUT]
    train=[r for r in rows if r['page'] not in HOLDOUT]
    return train, test

def evaluate(reader, test):
    acc={k:[0,0] for k in gen.CATS}
    for it in test:
        got=reader.read(it['gray'])[0] if hasattr(reader,'read') else reader(it['gray'])
        c=cer(clean(it['text']), clean(got))
        for k,f in gen.CATS.items():
            if f(it): acc[k][0]+=c; acc[k][1]+=1
    return {k:(100*v[0]/v[1] if v[1] else float('nan')) for k,v in acc.items()}, acc['всё'][1]

if __name__=='__main__':
    from ownocr.pair import CtcLineReader
    gen.fetch = None
    tr, te = split()
    print(f'обучение {len(tr)} строк · проверка {len(te)} строк ({sorted(HOLDOUT)})')
    print('чтец'.ljust(18)+''.join(f'{k:>12}' for k in gen.CATS))
    for name,path in gen.MODELS.items():
        res,n=evaluate(CtcLineReader(path), te)
        print(name.ljust(18)+''.join(f'{res[k]:>11.1f}%' for k in gen.CATS)+f'  n={n}')
