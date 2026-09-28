#!/bin/sh
# LinFileCopy web installer: downloads a release from GitHub, verifies it, installs it.
#
#   curl -fsSL https://raw.githubusercontent.com/MensuraMedia/linfilecopy/main/get.sh | sh
#   curl -fsSL https://raw.githubusercontent.com/MensuraMedia/linfilecopy/main/get.sh | sh -s -- --user
#
#   (no option)   Debian/Ubuntu/Mint: install the .deb with apt (asks for sudo).
#                 Other distributions: same as --user.
#   --deb         Always use the .deb (fails where apt is missing).
#   --user        Install for this user only, no root, from the source tarball (~/.local).
#   --uninstall   Remove a --user install (use 'sudo apt remove linfilecopy' for the package).
#
# Environment: LFC_REF=<branch or tag> (default main), LFC_BASE_URL=<url of a releases/ folder>.
# Nothing is installed unless the download matches releases/SHA256SUMS.
set -eu

REF=${LFC_REF:-main}
BASE=${LFC_BASE_URL:-https://raw.githubusercontent.com/MensuraMedia/linfilecopy/$REF/releases}

say() { printf '%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

fetch() {   # fetch URL FILE
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 2 -o "$2" "$1"
    elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$2" "$1"
    else
        die "curl or wget is needed to download LinFileCopy"
    fi
}

sha256() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
    else die "sha256sum is needed to verify the download"; fi
}

MODE=auto
case "${1:-}" in
    "") ;;
    --deb) MODE=deb ;;
    --user) MODE=user ;;
    --uninstall) MODE=uninstall ;;
    -h|--help) sed -n '2,14p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//' || true; exit 0 ;;
    *) die "unknown option $1 (use --deb, --user or --uninstall)" ;;
esac

if [ "$MODE" = auto ]; then
    if command -v apt-get >/dev/null 2>&1 && command -v dpkg >/dev/null 2>&1; then MODE=deb; else MODE=user; fi
fi

TMP=$(mktemp -d "${TMPDIR:-/tmp}/linfilecopy-get.XXXXXX")
trap 'rm -rf "$TMP"' EXIT INT TERM

say "Downloading the release list from $BASE …"
fetch "$BASE/SHA256SUMS" "$TMP/SHA256SUMS" || die "could not download $BASE/SHA256SUMS"

# pick FILE-PATTERN -> newest matching file name listed in SHA256SUMS
pick() { awk '{print $2}' "$TMP/SHA256SUMS" | sed 's/^\*//' | grep -E "$1" | sort -V | tail -n1; }

get_verified() {   # get_verified NAME -> downloads $TMP/NAME and checks it
    name=$1
    expected=$(awk -v n="$name" '{f=$2; sub(/^\*/, "", f)} f==n {print $1}' "$TMP/SHA256SUMS")
    [ -n "$expected" ] || die "$name is not listed in SHA256SUMS"
    say "Downloading $name …"
    fetch "$BASE/$name" "$TMP/$name" || die "could not download $BASE/$name"
    actual=$(sha256 "$TMP/$name")
    [ "$actual" = "$expected" ] || die "checksum mismatch for $name (expected $expected, got $actual)"
    say "✓ checksum verified"
}

user_tree() {   # download and unpack the source tarball, print the unpacked folder
    tarball=$(pick '^linfilecopy-[0-9][0-9.]*\.tar\.gz$')
    [ -n "$tarball" ] || die "no source tarball in this release"
    get_verified "$tarball" >&2
    tar -xzf "$TMP/$tarball" -C "$TMP"
    printf '%s\n' "$TMP/${tarball%.tar.gz}"
}

case "$MODE" in
    deb)
        command -v apt-get >/dev/null 2>&1 || die "apt is not available here; run with --user instead"
        deb=$(pick '^linfilecopy_.*_all\.deb$')
        [ -n "$deb" ] || die "no .deb in this release"
        get_verified "$deb"
        # A development launcher from install.sh --dev would shadow the package in the menu.
        rm -f "$HOME/.local/bin/linfilecopy-dev" \
              "${XDG_DATA_HOME:-$HOME/.local/share}/applications/io.github.mensuramedia.LinFileCopy.Devel.desktop"
        SUDO=""
        [ "$(id -u)" -eq 0 ] || SUDO=sudo
        say "Installing $deb with apt (this may ask for your password)…"
        # apt needs to read the package as the _apt user; /tmp/… with mode 700 is not readable.
        chmod 755 "$TMP"; chmod 644 "$TMP/$deb"
        $SUDO apt-get install -y "$TMP/$deb"
        say "Done. Start LinFileCopy from the applications menu or run: linfilecopy"
        ;;
    user)
        tree=$(user_tree)
        sh "$tree/install.sh" --user
        ;;
    uninstall)
        tree=$(user_tree)
        sh "$tree/install.sh" --uninstall
        ;;
esac
