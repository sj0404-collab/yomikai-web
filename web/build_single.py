#!/usr/bin/env python3
"""Собрать всё в ОДИН html-файл (как тот, что присылали, только настоящий).

    python3 web-ocr/build_single.py

Модели, wasm, словарь и примеры страниц зашиваются в файл base64 — страницу можно
носить одним файлом и открывать где угодно, без сервера и без сети.
"""
import base64, json, os

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'ownocr-web-single.html')


def b64(path):
    with open(path, 'rb') as f:
        return base64.b64encode(f.read()).decode()


html = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
core = open(os.path.join(ROOT, 'core.js'), encoding='utf-8').read()
ort_js = open(os.path.join(ROOT, 'vendor/ort.min.js'), encoding='utf-8').read()
wasm = b64(os.path.join(ROOT, 'vendor/ort-wasm-simd-threaded.wasm'))
mjs = b64(os.path.join(ROOT, 'vendor/ort-wasm-simd-threaded.mjs'))

inline = {
    'det': b64(os.path.join(ROOT, 'models/koma_det.onnx')),
    'rec': b64(os.path.join(ROOT, 'models/koma_rec.onnx')),
    'eslav': b64(os.path.join(ROOT, 'models/eslav-ft.onnx')),
    'eslavWebtoon': b64(os.path.join(ROOT, 'models/eslav-webtoon.onnx')),
    'eslavComic': b64(os.path.join(ROOT, 'models/eslav-comic.onnx')),
    'eslavHard': b64(os.path.join(ROOT, 'models/eslav-hard.onnx')),
    'charset': open(os.path.join(ROOT, 'models/charset.txt'), encoding='utf-8').read(),
    'dict': open(os.path.join(ROOT, 'models/koma_dict.txt'), encoding='utf-8').read(),
    'vocab': open(os.path.join(ROOT, 'data/vocab-ru.txt'), encoding='utf-8').read(),
    'examples': {name: b64(os.path.join(ROOT, 'data', name + '.jpg'))
                 for name in ('dense-a', 'dense-b', 'dense-page')},
    'sfx': {name: 'data:audio/wav;base64,' + b64(os.path.join(ROOT, 'data', 'sfx', name + '.wav'))
            for name in ('gong', 'hit', 'boom', 'whoosh', 'laugh', 'slap')},
    'wasmPaths': {
        'mjs': 'data:text/javascript;base64,' + mjs,
        'wasm': 'data:application/wasm;base64,' + wasm,
    },
}

html = html.replace('<script src="vendor/ort.min.js"></script>',
                    '<script>' + ort_js + '</script>')
html = html.replace('<script src="core.js"></script>',
                    '<script>' + core + '</script>')
html = html.replace('</head>',
                    '<script>window.__OWNOCR_INLINE__ = ' + json.dumps(inline) + ';</script>\n</head>')

open(OUT, 'w', encoding='utf-8').write(html)
print(f'{OUT} · {os.path.getsize(OUT)/1048576:.1f} МБ')
