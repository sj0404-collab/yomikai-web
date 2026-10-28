#!/bin/bash
# Быстрая проверка Kotlin без Gradle и без Android SDK: только компилятор
# Kotlin и android.jar. Ловит опечатки и неразрешённые имена за секунды —
# полная сборка АПК идёт в GitHub Actions.
#
# Что нужно (скачивается один раз в /tmp, при перезапуске песочницы повторить):
#   /tmp/kotlinc                       — kotlin-compiler-1.9.24.zip
#   /tmp/plat/android.jar              — platform-34-ext12_r01.zip
#   /tmp/libs/webkit.jar               — androidx.webkit 1.11.0 (classes.jar из aar)
set -e
cd "$(dirname "$0")/.."     # каталог apk/
KC=${KC:-/tmp/kotlinc/bin/kotlinc}
AJ=${AJ:-/tmp/plat/android.jar}
WK=${WK:-/tmp/libs/webkit.jar}
ORT=${ORT:-/tmp/libs/onnx.jar}   # androidx.webkit + onnxruntime-android (classes.jar из aar)
for f in "$KC" "$AJ" "$WK" "$ORT"; do
  [ -e "$f" ] || { echo "нет $f — скачайте тулчейн (см. комментарий в этом скрипте)"; exit 2; }
done

VER=$(grep -o "VERSION = 'v[0-9.]*'" ../koma-web.html 2>/dev/null | head -1 | grep -o "v[0-9.]*" || echo unknown)
GEN=$(mktemp -d)
mkdir -p "$GEN/net/koma/reader"
cat > "$GEN/net/koma/reader/BuildConfig.kt" <<GENEOF
package net.koma.reader
// Заглушка: настоящий BuildConfig генерирует Gradle из версии читалки.
object BuildConfig { const val PAGE_VERSION = "$VER" }
GENEOF

"$KC" -cp "$AJ:$WK:$ORT" -d "$GEN/out" \
  app/src/main/java/net/koma/reader/*.kt "$GEN/net/koma/reader/BuildConfig.kt" 2>&1 \
  | grep -v "^warning:" || true
if "$KC" -cp "$AJ:$WK:$ORT" -d "$GEN/out" app/src/main/java/net/koma/reader/*.kt "$GEN/net/koma/reader/BuildConfig.kt" 2>/dev/null; then
  echo "TYPECHECK OK · версия читалки $VER"
else
  echo "TYPECHECK FAILED"; exit 1
fi
