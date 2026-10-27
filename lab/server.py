#!/usr/bin/env python3
"""Лаборатория KOMA: страницы прогоняются через те же ONNX-модели, что в APK.

Запуск:  python3 lab/server.py [порт]
Открыть: http://<адрес>:8000

Зачем: проверять страницы и правки разбора без сборки APK. Пайплайн
(lab/pipeline.py) повторяет приложение v2.9.7 — последнюю версию, где текст
распознавался и порядок был верным, — и даёт тот же вывод слово в слово.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import pipeline  # noqa: E402

ROOT = Path(__file__).parent
PAGES = ROOT / "pages"
UPLOADS = ROOT / "uploads"
CACHE = ROOT / ".cache"
LOGS = ROOT / "logs"
RESULTS = LOGS / "results"
for folder in (PAGES, UPLOADS, CACHE, LOGS, RESULTS):
    folder.mkdir(exist_ok=True)

log_lock = threading.Lock()


def log(event: str, **fields) -> None:
    """Пишет строку в lab/logs/lab.log и в консоль процесса."""
    record = {"time": time.strftime("%H:%M:%S"), "event": event, **fields}
    line = json.dumps(record, ensure_ascii=False)
    with log_lock:
        with (LOGS / "lab.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    print(line, flush=True)

models: pipeline.Models | None = None
models_lock = threading.Lock()


def get_models() -> pipeline.Models:
    global models
    with models_lock:
        if models is None:
            models = pipeline.Models()
        return models


def analyze(path: Path, rtl: bool = True, variant: str = "2.9.7") -> dict:
    key = hashlib.sha1(path.read_bytes()).hexdigest()[:16]
    cache_file = CACHE / f"{key}_{'rtl' if rtl else 'ltr'}_{variant}.json"
    if cache_file.exists():
        payload = json.loads(cache_file.read_text())
        log("ocr_from_cache", page=path.name, variant=variant, rtl=rtl,
            regions=len(payload["regions"]), lines=len(payload["lines"]),
            texts=[line["text"] for line in payload["lines"]])
        return payload

    engine = get_models()
    regions = pipeline.recognize_page(engine, path, variant)
    lines = pipeline.reading_order(regions, rtl)
    width, height = Image.open(path).size
    payload = {
        "page": path.name,
        "variant": variant,
        "width": width,
        "height": height,
        "regions": [
            {"text": r.text, "l": r.left, "t": r.top, "r": r.right, "b": r.bottom, "score": r.score}
            for r in regions
        ],
        "lines": [
            {"text": line.text, "l": line.left, "t": line.top, "r": line.right, "b": line.bottom}
            for line in lines
        ],
    }
    cache_file.write_text(json.dumps(payload, ensure_ascii=False))

    # Полный результат — отдельным файлом, чтобы можно было вернуться к нему.
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (RESULTS / f"{stamp}_{path.stem}_{variant}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1))
    log("ocr", page=path.name, variant=variant, rtl=rtl, size=[width, height],
        regions=len(regions), lines=len(lines),
        texts=[line.text for line in lines])
    return payload


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # Каждый запрос — в lab/logs/lab.log: видно, что именно присылают.
        log("http", method=self.command, path=self.path, remote=self.client_address[0])

    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200):
        self._send(code, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/api/pages":
            names = sorted([p.name for p in PAGES.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
                           + [p.name for p in UPLOADS.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}])
            self._json({"pages": names})
            return
        # Файлы отдаём из папки лаборатории: index.html, standalone.html,
        # ort.min.js + ort-wasm…wasm (локальный рантайм), модели, страницы.
        relative = path.lstrip("/")
        if relative in ("", "index.html"):
            target = ROOT / "index.html"
        else:
            target = (ROOT / relative).resolve()
            # Никаких выходов из папки лаборатории и никакого кеша.
            if not str(target).startswith(str(ROOT.resolve())) or ".cache" in target.parts:
                self._json({"error": "не найдено"}, 404)
                return
        if not target.exists() or not target.is_file():
            self._json({"error": "не найдено"}, 404)
            return
        suffix = target.suffix.lower()
        types = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".wasm": "application/wasm",
            ".json": "application/json; charset=utf-8",
            ".md": "text/markdown; charset=utf-8",
            ".txt": "text/plain; charset=utf-8",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        if suffix in (".onnx",):
            self._send(200, target.read_bytes(), "application/octet-stream")
            return
        if suffix not in types:
            self._json({"error": "не найдено"}, 404)
            return
        self._send(200, target.read_bytes(), types[suffix])

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        try:
            if path == "/api/ocr":
                request = json.loads(body or b"{}")
                rtl = bool(request.get("rtl", True))
                variant = request.get("variant") or "2.9.7"
                note = (request.get("note") or "").strip()
                name = request.get("page")
                if request.get("image"):
                    raw = request["image"].split(",", 1)[-1]
                    data = base64.b64decode(raw)
                    digest = hashlib.sha1(data).hexdigest()[:10]
                    target = UPLOADS / f"upload_{digest}.png"
                    if not target.exists():
                        image = Image.open(io.BytesIO(data)).convert("RGB")
                        image.save(target)
                        log("upload", file=target.name, bytes=len(data), size=list(image.size))
                    name = target.name
                if not name:
                    self._json({"error": "не указана страница"}, 400)
                    return
                target = next((f / name for f in (PAGES, UPLOADS) if (f / name).exists()), None)
                if target is None:
                    self._json({"error": f"страница {name} не найдена"}, 404)
                    return
                result = analyze(target, rtl, variant)
                if note:
                    log("note", page=target.name, note=note)
                self._json(result)
                return
            self._json({"error": "неизвестный запрос"}, 404)
        except Exception as error:  # noqa: BLE001 — в лаборатории показываем всё
            traceback.print_exc()
            self._json({"error": str(error)}, 500)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"Лаборатория KOMA на http://0.0.0.0:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
