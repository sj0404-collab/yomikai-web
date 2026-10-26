#!/bin/bash
# Библиотеки для headless Chromium: в песочнице нет root, поэтому deb-пакеты
# распаковываются в /tmp/libs/root и подключаются через LD_LIBRARY_PATH.
# Нужно один раз перед запуском e2e.py / probe-скриптов.
set -e
DEST=/tmp/libs
mkdir -p "$DEST"
cd "$DEST"
BIN=$(ls -d /home/user/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell 2>/dev/null | head -1)
[ -z "$BIN" ] && { echo "сначала: python3 -m playwright install chromium"; exit 1; }
PKGS="libnspr4 libnss3 libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 libcups2t64 \
libgbm1 libpango-1.0-0 libcairo2 libasound2t64 libxdamage1 libxfixes3 libxrandr2 libxcomposite1 \
libxkbcommon0 libdrm2 libdbus-1-3 libexpat1 libxext6 libxi6 libxtst6 libxrender1 \
libpixman-1-0 libpng16-16 libfontconfig1 libfreetype6 libharfbuzz0b libxcb1 libxau6 libxdmcp6 \
libglib2.0-0t64 libwayland-client0"
for p in $PKGS; do
  apt-get download "$p" >/dev/null 2>&1 || true
done
for f in *.deb; do dpkg-deb -x "$f" root 2>/dev/null || true; done
export LD_LIBRARY_PATH=$DEST/root/usr/lib/x86_64-linux-gnu:$DEST/root/lib/x86_64-linux-gnu
for i in $(seq 1 15); do
  out=$($BIN --version 2>&1) || true
  if ! grep -q "error while loading" <<<"$out"; then echo "OK: $out"; echo "export LD_LIBRARY_PATH=$LD_LIBRARY_PATH"; exit 0; fi
  lib=$(grep -o "lib[A-Za-z0-9_.+-]*\.so[.0-9]*" <<<"$out" | head -1)
  case "$lib" in
    libXdamage*) pkg=libxdamage1;; libXfixes*) pkg=libxfixes3;; libXrandr*) pkg=libxrandr2;;
    libXcomposite*) pkg=libxcomposite1;; libX11*) pkg=libx11-6;; libxcb*) pkg=libxcb1;;
    libgraphite2*) pkg=libgraphite2-3;; libdatrie*) pkg=libdatrie1;; libthai*) pkg=libthai0;;
    libbsd*) pkg=libbsd0;; libmd*) pkg=libmd0;; libpcre2*) pkg=libpcre2-8-0;;
    libbrotli*) pkg=libbrotli1;; libffi*) pkg=libffi8;; libuuid*) pkg=libuuid1;;
    libcap*) pkg=libcap2;; libgcrypt*) pkg=libgcrypt20;; libgpg-error*) pkg=libgpg-error0;;
    libsystemd*) pkg=libsystemd0;; libudev*) pkg=libudev1;; liblzma*) pkg=liblzma5;;
    libzstd*) pkg=libzstd1;; libselinux*) pkg=libselinux1;;
    *) echo "нет пакета для $lib"; exit 1;;
  esac
  apt-get download "$pkg" >/dev/null 2>&1 && dpkg-deb -x ${pkg}_*.deb root || { echo "не скачался $pkg"; exit 1; }
done
