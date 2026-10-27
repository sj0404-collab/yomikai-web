#!/bin/bash
# Полный прогон: проверка сборки + все тесты. Никаких зависимостей из /tmp.
cd "$(dirname "$0")" || exit 1
fail=0
# Сборка ПЕРЕД проверками: иначе тесты гоняют тот koma-web.html, что лежит в
# репозитории, а он может быть старше исходников (27.10 в чистом клоне так и
# вышло: собранный файл отставал от part3.js на кэш текста).
OUT=./koma-web.html bash build.sh >/dev/null || fail=1
python3 check.py || fail=1
# инструменты репозитория: азбука, словарь (md5), синтетика, наличие частей сборки
if [ -f tools/selftest.py ]; then
  python3 tools/selftest.py | tail -1
  python3 tools/selftest.py >/dev/null 2>&1 || fail=1
fi
for t in test-*.cjs; do
  out=$(timeout 900 node "$t" 2>&1 | tail -1)
  printf '%-24s %s\n' "$t" "$out"
  case "$out" in *"ALL PASSED"*) ;; *) fail=1;; esac
done
[ $fail -eq 0 ] && echo "ВСЁ ПРОШЛО" || echo "ЕСТЬ ПАДЕНИЯ"
exit $fail
