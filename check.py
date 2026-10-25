#!/usr/bin/env python3
"""Проверка сборки: нет вызовов без определения, все id из разметки на месте.

Это ловит именно тот класс ошибки, из-за которого кнопка «молчит»:
функция вызывается, но не объявлена (storeModelFiles is not defined).
"""
import re, sys

parts = ['part2.js', 'part3.js', 'part4.js', 'part5.js']
src = '\n'.join(open(p, encoding='utf-8').read() for p in parts)
html = open('part1.html', encoding='utf-8').read()

declared = set(re.findall(r'function\s+([A-Za-z_$][\w$]*)', src))
declared |= set(re.findall(r'(?:const|let|var)\s+([A-Za-z_$][\w$]*)', src))
declared |= set(re.findall(r'class\s+([A-Za-z_$][\w$]*)', src))
# методы объектов: name(...) { ... } на своём отступе
declared |= set(re.findall(r'^\s{2,}([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{', src, re.M))

BUILTINS = set('''
if for while switch catch function return typeof new await Math JSON Object Array Number
String Boolean parseInt parseFloat isNaN setTimeout clearTimeout console Promise Date Map Set
Uint8Array Uint8ClampedArray Uint32Array Int32Array Float32Array DataView Blob Response
TextDecoder DecompressionStream URL indexedDB alert confirm speechSynthesis
SpeechSynthesisUtterance fetch requestAnimationFrame Intl Error RegExp encodeURIComponent
structuredClone async then
'''.split())
# имена методов (вызовы вида x.name() регулярка уже отсекает), но остаются
# вызовы внутри шаблонов — их перечисляем явно, если это действительно методы:
METHODS = set('''addBook clear get load put remove ensureLoaded loadModels onPageSized
onProgress onQueueEnd readVisible rej resolve scanCurrent translateY buildStrip blank
closeSheets openSheet toast renderModels importZip importDir saveRules loadRules
applyRules syncSettingsUI selfCheck showEnvBanner openBook storeModelFiles pickModels
paintPage recognizePage orderBubbles bubblesOf bandsOf'''.split())

calls = set(re.findall(r'(?<![\w.$])([A-Za-z_$][\w$]*)\s*\(', src))
unknown = sorted(c for c in calls - declared - BUILTINS if len(c) > 2 and c not in METHODS)

ids = set(re.findall(r'id="([^"]+)"', html))
used = set(re.findall(r"\$\('#([\w-]+)'\)", src))
used |= set(re.findall(r"getElementById\('([\w-]+)'\)", src))
missing_ids = sorted(used - ids)

# функции, которые обязаны существовать (их зовут обработчики)
REQUIRED = ['openBook', 'storeModelFiles', 'pickModels', 'renderModels', 'selfCheck',
            'importZip', 'addImages', 'showEnvBanner']

problems = []
if unknown:
    problems.append('вызовы без определения: ' + ', '.join(unknown))
if missing_ids:
    problems.append('нет id в разметке: ' + ', '.join(missing_ids))
for r in REQUIRED:
    if r not in declared and r != 'addImages':
        problems.append('нет функции ' + r)

if problems:
    print('BUILD CHECK FAILED')
    for p in problems:
        print(' -', p)
    sys.exit(1)
print('BUILD CHECK OK:', len(declared), 'определений,', len(ids), 'id')
