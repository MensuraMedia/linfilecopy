#!/bin/sh
# Build every release file from a clean export of HEAD into releases/:
#   linfilecopy_<version>-1_all.deb   Debian/Ubuntu package (tools/build_deb.sh, runs the tests)
#   linfilecopy-<version>.tar.gz      universal tarball for ./install.sh --user on any distribution
#   SHA256SUMS                        checksums that install.sh and get.sh verify
#   tools/build_release.sh [--no-deb]
set -eu
cd "$(dirname "$0")/.."
ROOT=$(pwd)
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
[ -z "$(git status --porcelain -- linfilecopy packaging install.sh tools pyproject.toml)" ] ||
    echo "warning: uncommitted changes are not part of the release (it is built from HEAD)" >&2
[ "${1:-}" = "--no-deb" ] || tools/build_deb.sh
mkdir -p releases
# git archive is reproducible: file times come from the commit, gzip stores no name or date.
git archive --format=tar.gz --prefix="linfilecopy-$VERSION/" -o "releases/linfilecopy-$VERSION.tar.gz" HEAD \
    linfilecopy packaging install.sh tools/gen_gresource_xml.py pyproject.toml README.md changelog.md
cd releases
sha256sum linfilecopy_*_all.deb linfilecopy-*.tar.gz > SHA256SUMS
cat SHA256SUMS
