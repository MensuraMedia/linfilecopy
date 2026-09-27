#!/bin/sh
# Install the desktop entry, AppStream metainfo and application icons.
# The Python package itself is installed with pip or by the distribution package.
#   packaging/install-data.sh [PREFIX] [DESTDIR]
set -eu
PREFIX="${1:-/usr/local}"
DESTDIR="${2:-}"
cd "$(dirname "$0")/.."
APP=io.github.mensuramedia.LinFileCopy
SHARE="$DESTDIR$PREFIX/share"
install -Dm644 "packaging/$APP.desktop" "$SHARE/applications/$APP.desktop"
install -Dm644 "packaging/$APP.metainfo.xml" "$SHARE/metainfo/$APP.metainfo.xml"
install -Dm644 "linfilecopy/data/app-icon/$APP.svg" "$SHARE/icons/hicolor/scalable/apps/$APP.svg"
install -Dm644 "linfilecopy/data/app-icon/$APP-symbolic.svg" "$SHARE/icons/hicolor/symbolic/apps/$APP-symbolic.svg"
for dir in linfilecopy/data/app-icon/hicolor/*x*; do
    size=$(basename "$dir")
    install -Dm644 "$dir/apps/$APP.png" "$SHARE/icons/hicolor/$size/apps/$APP.png"
done
for mo in linfilecopy/data/locale/*/LC_MESSAGES/linfilecopy.mo; do
    [ -f "$mo" ] || continue
    install -Dm644 "$mo" "$SHARE/locale/${mo#linfilecopy/data/locale/}"
done
echo "installed data files under $SHARE"
