#!/usr/bin/env python3
"""Сервер для ownocr-web: отдаёт файлы с правильными типами.

    python3 web-ocr/serve.py [порт]

Зачем свой, а не `python3 -m http.server`: для `.wasm` нужен тип
`application/wasm`, иначе браузер не даёт собрать модуль потоково, а
`onnxruntime-web` в части браузеров из-за этого падает. Кэш выключен, чтобы
правка `core.js` была видна сразу.
"""
import http.server
import os
import socketserver
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        '.wasm': 'application/wasm',
        '.onnx': 'application/octet-stream',
        '.mjs': 'text/javascript',
        '.js': 'text/javascript',
        '.txt': 'text/plain; charset=utf-8',
        '.json': 'application/json',
    }

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write('%s\n' % (fmt % args))


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    print(f'ownocr-web: http://0.0.0.0:{PORT}/  (папка {ROOT})', flush=True)
    Server(('0.0.0.0', PORT), Handler).serve_forever()
