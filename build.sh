#!/bin/bash
# Сборка одного самодостаточного html из частей. Порядок важен.
# /home/user/koma-web.html в рабочей папке может быть обрезан при восстановлении
# окружения, поэтому собираем ВСЕГДА перед тестами и публикацией.
set -e
cd "$(dirname "$0")"
# Куда писать сборку: в рабочей папке — на уровень выше, в клоне репозитория —
# рядом с исходниками. Можно переопределить: OUT=путь ./build.sh
if [ -z "$OUT" ]; then
  if [ -d .git ] || [ "$(basename "$PWD")" != "koma-web" ]; then OUT=./koma-web.html; else OUT=../koma-web.html; fi
fi
cat part1.html part0-ort.js part0-wasm.js part0-dict.js part2.js part3.js part4.js part5.js > "$OUT"
python3 check.py
ls -l "$OUT"
grep -o "VERSION = 'v[0-9.]*'" "$OUT" | head -1
