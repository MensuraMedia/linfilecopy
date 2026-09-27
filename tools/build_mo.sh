#!/bin/sh
# Compile po/<lang>.po into linfilecopy/data/locale/<lang>/LC_MESSAGES/linfilecopy.mo
set -eu
cd "$(dirname "$0")/.."
for po in po/*.po; do
  [ -f "$po" ] || continue
  lang=$(basename "$po" .po)
  mkdir -p "linfilecopy/data/locale/$lang/LC_MESSAGES"
  msgfmt --check -o "linfilecopy/data/locale/$lang/LC_MESSAGES/linfilecopy.mo" "$po"
  echo "compiled $lang"
done
