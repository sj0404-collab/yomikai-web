"""Собирает standalone.html: один файл, без бэкенда.

Внутрь вшивается koma.js (порт распознавания и порядка чтения), модели
подгружаются либо с сервера рядом, либо выбором файлов вручную.
"""
from pathlib import Path

root = Path(__file__).parent
template = (root / "standalone.template.html").read_text(encoding="utf-8")
engine = (root / "koma.js").read_text(encoding="utf-8")
(root / "standalone.html").write_text(template.replace("/*__KOMA_JS__*/", engine), encoding="utf-8")
print("standalone.html:", (root / "standalone.html").stat().st_size, "байт")
