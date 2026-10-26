#!/bin/bash
# Сборка одного самодостаточного html из частей. Порядок важен.
# /home/user/koma-web.html в рабочей папке может быть обрезан при восстановлении
# окружения, поэтому собираем ВСЕГДА перед тестами и публикацией.
set -e
cd "$(dirname "$0")"
cat part1.html part0-ort.js part0-wasm.js part0-dict.js part2.js part3.js part4.js part5.js > ../koma-web.html
python3 check.py
ls -l ../koma-web.html
grep -o "VERSION = 'v[0-9.]*'" ../koma-web.html | head -1
