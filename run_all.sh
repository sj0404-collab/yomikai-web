#!/bin/bash
# Полный прогон: проверка сборки + все тесты. Никаких зависимостей из /tmp.
cd "$(dirname "$0")" || exit 1
fail=0
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
