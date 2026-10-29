#!/bin/bash
# Прогон ДВИЖКА ЧТЕНИЯ (Kotlin) без Android и без Gradle.
#
# Зачем: порядок реплик и склейка слов — то, из-за чего чтение «прыгало и
# путалось». Проверять это «на телефоне» дорого, а здесь тот же самый класс
# ReadEngine.kt компилируется с мини-заглушкой org.json и гоняется на
# синтетической странице: 12 строк → 3 реплики в порядке чтения манги.
#
#   bash apk/tools/readtest/run.sh
set -e
cd "$(dirname "$0")"
KC=${KC:-/tmp/kotlinc/bin/kotlinc}
[ -x "$KC" ] || { echo "нет $KC — нужен kotlin-compiler (см. apk/tools/typecheck.sh)"; exit 2; }
OUT=$(mktemp -d)
"$KC" -include-runtime -d "$OUT/rt.jar" JsonStub.kt \
  ../../app/src/main/java/net/koma/reader/ReadEngine.kt Main.kt 2>&1 | grep -E "^error" && exit 1
java -Dfile.encoding=UTF-8 -jar "$OUT/rt.jar"
