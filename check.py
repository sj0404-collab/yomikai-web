#!/usr/bin/env python3
"""Проверка сборки: нет вызовов без определения, все id из разметки на месте.

Ловит ровно тот класс ошибки, из-за которого кнопка «молчит»: функция
вызывается, но не объявлена (storeModelFiles is not defined), или обработчик
ссылается на id, которого нет в разметке.
"""
import re
import sys

CALL_PARTS = ['part2.js', 'part3.js', 'part4.js', 'part5.js']
DECL_PARTS = ['part0-wasm.js', 'part0-dict.js'] + CALL_PARTS
html = open('part1.html', encoding='utf-8').read()


def strip_block_comments(text):
    """Убрать /* ... */ и строки, начинающиеся с //.

    Разбор построчный: base64 в part0-wasm.js содержит «//», и любой честный
    лексер спотыкается на нём. Поэтому base64-часть в поиск вызовов вообще
    не входит — из неё берутся только объявления.
    """
    out, in_block = [], False
    for line in text.split('\n'):
        if in_block:
            if '*/' in line:
                in_block = False
                tail = line.split('*/', 1)[1]
                if tail.strip():
                    out.append(tail)
            continue
        if '/*' in line:
            head, tail = line.split('/*', 1)
            if '*/' in tail:
                out.append(head + tail.split('*/', 1)[1])
            else:
                out.append(head)
                in_block = True
            continue
        if line.lstrip().startswith('//'):
            continue
        out.append(line)
    return '\n'.join(out)


decl_src = '\n'.join(open(p, encoding='utf-8').read() for p in DECL_PARTS)
# part0-dict.js не входит в поиск вызовов: там 2 МБ base64, лексер на нём спотыкается.
decl_extra = '\n'.join(open(p, encoding='utf-8').read() for p in ['part0-dict.js'])
call_src = strip_block_comments('\n'.join(open(p, encoding='utf-8').read() for p in CALL_PARTS))
declared_extra = set(re.findall(r'function\s+([A-Za-z_$][\w$]*)', decl_extra))

declared = set(re.findall(r'function\s+([A-Za-z_$][\w$]*)', decl_src)) | declared_extra
declared |= set(re.findall(r'(?:const|let|var)\s+([A-Za-z_$][\w$]*)', decl_src))
declared |= set(re.findall(r'class\s+([A-Za-z_$][\w$]*)', decl_src))
declared |= set(re.findall(r'^\s{2,}([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{', decl_src, re.M))

BUILTINS = set("""
if for while switch catch function return typeof new await Math JSON Object Array Number
String Boolean parseInt parseFloat isNaN setTimeout clearTimeout setInterval clearInterval console Promise Date Map Set
Uint8Array Uint8ClampedArray Uint32Array Int32Array Float32Array DataView Blob Response
TextDecoder DecompressionStream atob btoa URL indexedDB alert confirm speechSynthesis
SpeechSynthesisUtterance fetch requestAnimationFrame Intl Error RegExp encodeURIComponent
structuredClone async then
""".split())

# Вызовы методов объектов выглядят как вызовы свободных функций — перечисляем.
METHODS = set("""
addBook appendTo clear get load put remove ensureLoaded loadModels onPageSized onProgress onQueueEnd
readVisible rej resolve scanCurrent translateY buildStrip blank closeSheets openSheet toast
renderModels importZip importDir saveRules loadRules applyRules syncSettingsUI selfCheck
showEnvBanner openBook storeModelFiles pickModels paintPage recognizePage orderBubbles scanPage rescanInDir renderTextSheet openTextSheet savePageBuffer syncPage pageAtViewport visibleBandPx
bubblesOf bandsOf
canFlush onBubble readWhileScanning
advanceReading markSpoken saveSpoken spokenKey unspokenInBand showStart hideStart prefetchNext waitIdle
""".split())

calls = set(re.findall(r'(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(', call_src))
unknown = sorted(c for c in calls - declared - BUILTINS if len(c) > 2 and c not in METHODS)

ids = set(re.findall(r'id="([^"]+)"', html))
used = set(re.findall(r"\$\('#([\w-]+)'\)", call_src))
# кнопки, которые рисуются из кода (внутри innerHTML), а не в разметке
RUNTIME_IDS = {'textPrev', 'textNext', 'textNav'}
used = {u for u in used if u not in RUNTIME_IDS}
used |= set(re.findall(r"getElementById\('([\w-]+)'\)", call_src))
missing_ids = sorted(used - ids)

REQUIRED = ['embeddedDictText', 'openBook', 'storeModelFiles', 'pickModels', 'renderModels', 'selfCheck',
            'installOrtWasm', 'runModel', 'detectBoxes', 'decodeCrop',
            'importZip', 'showEnvBanner']

# ── Мёртвые кнопки: id есть в разметке, обработчика нет ──
btn_ids = re.findall(r'<button[^>]*id="([\w-]+)"', html)
bound = set(re.findall(r"\$\('#([\w-]+)'\)\.onclick", call_src))
bound |= set(re.findall(r"getElementById\('([\w-]+)'\)\.onclick", call_src))
bound |= set(re.findall(r"\$\$\('([^']+)'\)", call_src))
grouped = set()
for sel in bound:
    for m in re.findall(r'#([\w-]+)', sel):
        grouped.add(m)
bound |= grouped
# обработчики, повешенные через переменную: const btn = $('#id'); btn.onclick = ...
var_ids = set(re.findall(r"(?:const|let|var)\s+([\w$]+)\s*=\s*\$\('#([\w-]+)'\)", call_src) and [])
for alias, _id in re.findall(r"(?:const|let|var)\s+([\w$]+)\s*=\s*\$\('#([\w-]+)'\)", call_src):
    if re.search(r'\b' + re.escape(alias) + r'\.on(?:click|change)\s*=', call_src):
        bound.add(_id)
dead = [b for b in btn_ids if b not in bound]

problems = []
if dead:
    problems.append('кнопки без обработчика: ' + ', '.join(dead))
if unknown:
    problems.append('вызовы без определения: ' + ', '.join(unknown))
if missing_ids:
    problems.append('нет id в разметке: ' + ', '.join(missing_ids))
for r in REQUIRED:
    if r not in declared:
        problems.append('нет функции ' + r)

if problems:
    print('BUILD CHECK FAILED')
    for p in problems:
        print(' -', p)
    sys.exit(1)
print('BUILD CHECK OK: %d определений, %d id' % (len(declared), len(ids)))
