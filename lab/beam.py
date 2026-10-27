import json, math, sys
import numpy as np

D = json.load(open('logits/dict.json', encoding='utf-8'))
ALPHABET = D['dict']                     # 519 классов
LOGS = {}

def load(name):
    rec = json.load(open('logits/%s.json' % name, encoding='utf-8'))
    lines = []
    for i in range(len(rec['lines'])):
        p = np.load('logits/%s_%d.npy' % (name, i))
        lines.append(p)
    return rec, lines

def greedy(p):
    idx = p.argmax(1); out = []; prev = 0
    for k in idx:
        if k != 0 and k != prev: out.append(ALPHABET[k])
        prev = k
    return ''.join(out)

def log_softmax(p):
    lp = np.log(np.maximum(p, 1e-9))
    return lp

def ctc_beam(lp, beam=25, trie=None, lm=None, lm_w=0.0, blank=0):
    """CTC prefix beam search. trie — множество префиксов слов (в верхнем регистре),
    ограничивает продолжение текущего слова; lm — {слово: logp} для бонуса."""
    T, C = lp.shape
    NEG = -1e30
    # beam: префикс -> (p_b, p_nb, last_char, word_started)
    beams = {(): (0.0, NEG)}
    for t in range(T):
        row = lp[t]
        # кандидаты: blank + топ-N классов (по вероятности) — полный перебор 519 дорог
        top = np.argpartition(-row, 20)[:21]
        nxt = {}
        for pref, (pb, pnb) in beams.items():
            p_tot = np.logaddexp(pb, pnb) if pnb > NEG else pb
            # blank
            b = nxt.get(pref)
            nb_pb = (b[0] if b else NEG)
            nxt[pref] = (np.logaddexp(nb_pb, p_tot + row[blank]), b[1] if b else NEG)
            last = pref[-1] if pref else None
            for c in top:
                c = int(c)
                if c == blank: continue
                ch = ALPHABET[c]
                if trie is not None and not allowed(pref, ch, trie): continue
                if last is not None and c == last:
                    # повтор символа: остаётся в том же префиксе (p_nb) или даёт новый (после blank)
                    cur = nxt.get(pref)
                    pb0, pnb0 = cur if cur else (NEG, NEG)
                    nxt[pref] = (pb0, np.logaddexp(pnb0, pnb + row[c]))
                    newp = pref + (c,)
                    c2 = nxt.get(newp)
                    pb2, pnb2 = c2 if c2 else (NEG, NEG)
                    nxt[newp] = (pb2, np.logaddexp(pnb2, pb + row[c]))
                else:
                    newp = pref + (c,)
                    c2 = nxt.get(newp)
                    pb2, pnb2 = c2 if c2 else (NEG, NEG)
                    nxt[newp] = (pb2, np.logaddexp(pnb2, p_tot + row[c]))
        # отбор
        items = sorted(nxt.items(), key=lambda kv: -(np.logaddexp(kv[1][0], kv[1][1]) if kv[1][1] > NEG else kv[1][0]))[:beam]
        beams = dict(items)
    best = max(beams.items(), key=lambda kv: (np.logaddexp(kv[1][0], kv[1][1]) if kv[1][1] > NEG else kv[1][0]))
    return ''.join(ALPHABET[c] for c in best[0])

def build_trie(words, maxlen=None):
    """префиксы слов в верхнем регистре + отметка «слово целиком»"""
    pre = set(); full = set()
    for w in words:
        u = ''.join(ch for ch in w.upper() if 'А' <= ch <= 'Я' or ch == 'Ё')
        if not u: continue
        for i in range(1, len(u) + 1):
            pre.add(u[:i])
            if i == len(u): full.add(u)
    return pre, full

def allowed(pref, ch, trie):
    pre, full = trie
    text = ''.join(ALPHABET[c] for c in pref)
    # текущее слово — хвост после последнего пробела
    word = text.split(' ')[-1] if text else ''
    u = ''.join(c for c in ch if True)
    if ch == ' ':
        return (word.upper() in full) or word == ''
    cu = ch.upper() if ch.isalpha() else ch
    if word == '':
        return cu in pre if cu.isalpha() else True
    cand = (word + ch).upper()
    if cu.isalpha():
        return cand in pre
    return True   # знаки препинания пропускаем без ограничений

def cer(a, b):
    norm = lambda s: ''.join(c for c in s.lower() if 'а' <= c <= 'я' or c == 'ё')
    s, t = norm(a), norm(b)
    if not t: return 0.0
    prev = list(range(len(t) + 1))
    for i in range(1, len(s) + 1):
        cur = [i] + [0] * len(t)
        for j in range(1, len(t) + 1):
            cur[j] = min(prev[j] + 1, cur[j-1] + 1, prev[j-1] + (s[i-1] != t[j-1]))
        prev = cur
    return 100.0 * prev[-1] / len(t)

if __name__ == '__main__':
    words = [l.split()[0].lower() for l in open('ru_250k.txt', encoding='utf-8') if l.strip()]
    trie = build_trie(words[:200000])
    for name in ['b1', 'b2', 'b3', 'b4']:
        rec, lines = load(name)
        print('=====', name, '·', rec['truth'])
        g = ' '.join(greedy(p) for p in lines)
        print('  жадный      CER %5.1f%%  %s' % (cer(g, rec['truth']), g[:90]))
        for beam in (10, 30):
            out = []
            for p in lines:
                lp = log_softmax(p)
                out.append(ctc_beam(lp, beam=beam, trie=trie))
            t = ' '.join(out)
            print('  луч+словарь(b=%d) CER %5.1f%%  %s' % (beam, cer(t, rec['truth']), t[:90]))
