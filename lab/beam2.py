import json, math
import numpy as np
from beam import load, greedy, cer, ALPHABET

NEG = -1e30

def known_words(path, limit=1500000):
    ws = {}
    for i, line in enumerate(open(path, encoding='utf-8')):
        if i >= limit: break
        parts = line.split()
        if not parts: continue
        w = parts[0].lower()
        u = ''.join(c for c in w.upper() if 'А' <= c <= 'Я' or c == 'Ё')
        if not u: continue
        if u not in ws: ws[u] = i
    return ws

def make_trie(words):
    pre, full = set(), set()
    for u in words:
        full.add(u)
        for i in range(1, len(u)):
            pre.add(u[:i])
    return pre, full

def decode(lp, trie, beam=10, topk=8, b_bonus=0.6, p_pen=0.4, space_bonus=0.0,
           blank=0, max_word=24):
    T, C = lp.shape
    pre, full = trie
    # beam: (pref_tuple) -> [p_b, p_nb, bonus]
    beams = {(): (0.0, NEG, 0.0)}
    for t in range(T):
        row = lp[t]
        top = np.argpartition(-row, topk)[:topk + 1]
        nxt = {}
        def add(pref, pb, pnb, bonus):
            cur = nxt.get(pref)
            if cur is None: nxt[pref] = [pb, pnb, bonus]
            else:
                cur[0] = np.logaddexp(cur[0], pb) if pb > NEG else cur[0]
                cur[1] = np.logaddexp(cur[1], pnb) if pnb > NEG else cur[1]
                if bonus > cur[2]: cur[2] = bonus
        for pref, (pb, pnb, bonus) in beams.items():
            tot = np.logaddexp(pb, pnb) if pnb > NEG else pb
            add(pref, tot + row[blank], NEG, bonus)
            last = pref[-1] if pref else None
            text = ''.join(ALPHABET[c] for c in pref)
            word = text.split(' ')[-1]
            for c in top:
                c = int(c)
                if c == blank: continue
                ch = ALPHABET[c]
                # оценка «похоже на слово»
                if ch == ' ':
                    u = word.upper()
                    b = space_bonus if (u in full or u == '') else -p_pen * 2
                else:
                    cu = ch.upper()
                    cand = (word + ch).upper()
                    if cu.isalpha() and 'А' <= cu <= 'Я' or cu == 'Ё':
                        b = b_bonus if cand in pre else -p_pen
                    else:
                        b = 0.0
                newpref = pref + (c,)
                if last is not None and c == last:
                    add(pref, NEG, pnb + row[c] + b, bonus + b)
                    add(newpref, pb + row[c] + b, NEG, bonus + b)
                else:
                    add(newpref, tot + row[c] + b, NEG, bonus + b)
        items = sorted(nxt.items(), key=lambda kv: -(np.logaddexp(kv[1][0], kv[1][1]) if kv[1][1] > NEG else kv[1][0]))[:beam]
        beams = dict(items)
    best = max(beams.items(), key=lambda kv: (np.logaddexp(kv[1][0], kv[1][1]) if kv[1][1] > NEG else kv[1][0]))
    return ''.join(ALPHABET[c] for c in best[0])

if __name__ == '__main__':
    words = known_words('d1500.txt')
    trie = make_trie(words.keys())
    print('слов в словаре декодера:', len(words))
    for bb, pp in [(0.6, 0.4), (1.0, 0.6), (1.4, 0.8), (2.0, 1.2)]:
        print('--- бонус %.1f / штраф %.1f' % (bb, pp))
        tot = 0
        for name in ['b1','b2','b3','b4']:
            rec, lines = load(name)
            out = ' '.join(decode(np.log(1e-9 + p), trie, b_bonus=bb, p_pen=pp) for p in lines)
            c = cer(out, rec['truth']); tot += c
            print('  %s CER %5.1f%%  %s' % (name, c, out[:95]))
        print('  сумма CER: %.1f' % tot)
