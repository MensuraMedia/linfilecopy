#!/bin/sh
# Build the Debian package from a clean export of HEAD and copy it to releases/.
#   tools/build_deb.sh
# Needs: debhelper dh-python pybuild-plugin-pyproject python3-all (and xvfb for the UI test).
set -eu
cd "$(dirname "$0")/.."
ROOT=$(pwd)
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/lfc-deb.XXXXXX")
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/linfilecopy-$VERSION"
git archive HEAD | tar -x -C "$WORK/linfilecopy-$VERSION"
cd "$WORK/linfilecopy-$VERSION"
cp -r packaging/debian debian
dpkg-checkbuilddeps
if command -v xvfb-run >/dev/null; then
  xvfb-run -a dpkg-buildpackage -us -uc -b
else
  dpkg-buildpackage -us -uc -b
fi
mkdir -p "$ROOT/releases"
cp "$WORK"/linfilecopy_*_all.deb "$ROOT/releases/"
cd "$ROOT/releases"
sha256sum linfilecopy_*_all.deb > SHA256SUMS
echo "built: $(ls "$ROOT"/releases/*.deb)"
