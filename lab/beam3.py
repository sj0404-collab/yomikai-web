import json, math
import numpy as np
from beam import load, greedy, cer, ALPHABET

NEG = -1e30

def build(path, limit=1500000):
    rank = {}
    for i, line in enumerate(open(path, encoding='utf-8')):
        if i >= limit: break
        parts = line.split()
        if not parts: continue
        u = ''.join(c for c in parts[0].upper() if 'А' <= c <= 'Я' or c == 'Ё')
        if not u or u in rank: continue
        rank[u] = i
    pre = set()
    for u in rank:
        for i in range(1, len(u)):
            pre.add(u[:i])
    return pre, rank

def decode(lp, trie, beam=10, topk=8, b_bonus=1.2, p_pen=0.7, w_word=1.6, blank=0):
    T, C = lp.shape
    pre, rank = trie
    beams = {(): (0.0, NEG)}
    for t in range(T):
        row = lp[t]
        top = np.argpartition(-row, topk)[:topk + 1]
        nxt = {}
        def add(pref, pb, pnb):
            cur = nxt.get(pref)
            if cur is None: nxt[pref] = [pb, pnb]
            else:
                cur[0] = np.logaddexp(cur[0], pb) if pb > NEG else cur[0]
                cur[1] = np.logaddexp(cur[1], pnb) if pnb > NEG else cur[1]
        for pref, (pb, pnb) in beams.items():
            tot = np.logaddexp(pb, pnb) if pnb > NEG else pb
            add(pref, tot + row[blank], NEG)
            last = pref[-1] if pref else None
            text = ''.join(ALPHABET[c] for c in pref)
            word = text.split(' ')[-1]
            for c in top:
                c = int(c)
                if c == blank: continue
                ch = ALPHABET[c]
                if ch == ' ':
                    if not word: continue                       # без двойных пробелов
                    u = word.upper()
                    if u in rank:
                        b = w_word * (1.0 - min(1.0, math.log10(rank[u] + 1) / 6.0))
                    else:
                        b = -p_pen * 2
                else:
                    cu = ch.upper()
                    cand = (word + ch).upper()
                    if 'А' <= cu <= 'Я' or cu == 'Ё':
                        b = b_bonus if cand in pre else -p_pen
                    else:
                        b = 0.0
                newpref = pref + (c,)
                if last is not None and c == last:
                    add(pref, NEG, pnb + row[c] + b)
                    add(newpref, pb + row[c] + b, NEG)
                else:
                    add(newpref, tot + row[c] + b, NEG)
        items = sorted(nxt.items(), key=lambda kv: -(np.logaddexp(kv[1][0], kv[1][1]) if kv[1][1] > NEG else kv[1][0]))[:beam]
        beams = dict(items)
    best = max(beams.items(), key=lambda kv: (np.logaddexp(kv[1][0], kv[1][1]) if kv[1][1] > NEG else kv[1][0]))
    return ''.join(ALPHABET[c] for c in best[0]).replace('  ', ' ').strip()

if __name__ == '__main__':
    trie = build('d1500.txt')
    print('слов в словаре декодера:', len(trie[1]))
    import sys
    for w_word in (0.0, 1.0, 1.6, 2.4):
        print('--- вес частоты слова %.1f' % w_word)
        tot = 0
        for name in ['b1','b2','b3','b4']:
            rec, lines = load(name)
            out = ' '.join(decode(np.log(1e-9 + p), trie, w_word=w_word) for p in lines)
            c = cer(out, rec['truth']); tot += c
            print('  %s CER %5.1f%%  %s' % (name, c, out[:95]))
        print('  сумма CER: %.1f' % tot)
