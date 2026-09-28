#!/bin/sh
# LinFileCopy installer.
#
#   ./install.sh              Debian/Ubuntu: install releases/*.deb with apt (asks for sudo).
#                             Other systems: same as --user.
#   ./install.sh --user       Install for this user only, no root: ~/.local/share/linfilecopy,
#                             launcher in ~/.local/bin, menu entry and icons in ~/.local/share.
#   ./install.sh --check      Only check the required system packages.
#   ./install.sh --uninstall  Remove a --user install (use 'sudo apt remove linfilecopy' for the package).
#
# LinFileCopy has no Python dependencies to download: it needs Python 3.10+,
# PyGObject with GTK 3, and rsync from your distribution.
set -eu

APP_ID=io.github.mensuramedia.LinFileCopy
SRC=$(cd "$(dirname "$0")" && pwd)
DATA_HOME=${XDG_DATA_HOME:-$HOME/.local/share}
BIN_DIR=$HOME/.local/bin
APP_DIR=$DATA_HOME/linfilecopy/app

say() { printf '%s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

hint_packages() {
    if command -v apt-get >/dev/null 2>&1; then
        say "  sudo apt install python3-gi gir1.2-gtk-3.0 rsync udisks2 gir1.2-ayatanaappindicator3-0.1 gir1.2-secret-1"
    elif command -v dnf >/dev/null 2>&1; then
        say "  sudo dnf install python3-gobject gtk3 rsync udisks2 libayatana-appindicator-gtk3 libsecret"
    elif command -v pacman >/dev/null 2>&1; then
        say "  sudo pacman -S python-gobject gtk3 rsync udisks2 libayatana-appindicator libsecret"
    elif command -v zypper >/dev/null 2>&1; then
        say "  sudo zypper install python3-gobject-Gdk typelib-1_0-Gtk-3_0 rsync udisks2"
    else
        say "  Install: Python 3.10+, PyGObject with GTK 3, rsync (and optionally udisks2)."
    fi
}

check() {
    missing=0
    if ! command -v python3 >/dev/null 2>&1; then
        say "✗ python3 not found"; missing=1
    elif ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
        say "✗ Python 3.10 or newer is required (found $(python3 --version 2>&1))"; missing=1
    else
        say "✓ $(python3 --version 2>&1)"
    fi
    if command -v python3 >/dev/null 2>&1 && python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' 2>/dev/null; then
        say "✓ PyGObject with GTK 3"
    else
        say "✗ PyGObject with GTK 3 not found"; missing=1
    fi
    if command -v rsync >/dev/null 2>&1; then
        say "✓ $(rsync --version | head -n1)"
    else
        say "✗ rsync not found"; missing=1
    fi
    command -v udisksctl >/dev/null 2>&1 && say "✓ udisks2" || say "• udisks2 not found (optional: mount, unlock and eject drives)"
    if [ "$missing" -ne 0 ]; then
        say ""
        say "Install the missing packages, for example:"
        hint_packages
        return 1
    fi
    return 0
}

install_deb() {
    deb=$(ls "$SRC"/releases/linfilecopy_*_all.deb 2>/dev/null | sort -V | tail -n1)
    [ -n "$deb" ] || die "no package in releases/. Build one with tools/build_deb.sh, or use --user."
    if [ -f "$SRC/releases/SHA256SUMS" ]; then
        (cd "$SRC/releases" && sha256sum -c --ignore-missing SHA256SUMS) || die "checksum mismatch for $deb"
    fi
    say "Installing $(basename "$deb") with apt (this asks for your password)…"
    sudo apt-get install -y "$deb"
    say "Done. Start LinFileCopy from the applications menu or run: linfilecopy"
}

install_user() {
    check || die "missing required packages (see above)"
    say "Installing for $(id -un) into $DATA_HOME/linfilecopy …"
    rm -rf "$APP_DIR"
    mkdir -p "$APP_DIR" "$BIN_DIR"
    cp -r "$SRC/linfilecopy" "$APP_DIR/"
    find "$APP_DIR" -name '__pycache__' -type d -prune -exec rm -rf {} +
    rm -f "$APP_DIR/linfilecopy/data/linfilecopy.gresource"   # never ship a stale bundle
    if command -v glib-compile-resources >/dev/null 2>&1; then
        (cd "$SRC" && python3 tools/gen_gresource_xml.py) > "$APP_DIR/linfilecopy/data/linfilecopy.gresource.xml"
        glib-compile-resources --sourcedir="$APP_DIR/linfilecopy/data" \
            --target="$APP_DIR/linfilecopy/data/linfilecopy.gresource" \
            "$APP_DIR/linfilecopy/data/linfilecopy.gresource.xml"
    fi
    cat > "$BIN_DIR/linfilecopy" <<EOF
#!/bin/sh
# LinFileCopy launcher (installed by install.sh --user)
PYTHONPATH="$APP_DIR\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m linfilecopy "\$@"
EOF
    chmod 755 "$BIN_DIR/linfilecopy"
    "$SRC/packaging/install-data.sh" "$HOME/.local" >/dev/null
    # Menu entry with an absolute path: ~/.local/bin is not always on the desktop's PATH.
    sed -i "s|^Exec=linfilecopy|Exec=$BIN_DIR/linfilecopy|" "$DATA_HOME/applications/$APP_ID.desktop"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$DATA_HOME/applications" || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" 2>/dev/null || true
    say "Done. Start LinFileCopy from the applications menu or run: $BIN_DIR/linfilecopy"
    case ":$PATH:" in *":$BIN_DIR:"*) ;; *) say "Tip: add $BIN_DIR to your PATH to run 'linfilecopy' directly." ;; esac
}

uninstall_user() {
    rm -rf "$DATA_HOME/linfilecopy/app"
    rm -f "$BIN_DIR/linfilecopy" "$DATA_HOME/applications/$APP_ID.desktop" "$DATA_HOME/metainfo/$APP_ID.metainfo.xml"
    find "$DATA_HOME/icons/hicolor" -name "$APP_ID*" -delete 2>/dev/null || true
    say "Removed the per-user install. Your jobs, history and logs were kept:"
    say "  ~/.config/linfilecopy  ~/.local/share/linfilecopy  ~/.local/state/linfilecopy"
    say "Timers or cron entries created by LinFileCopy remain until removed in its Scheduler."
}

case "${1:-}" in
    --check) check ;;
    --user) install_user ;;
    --uninstall) uninstall_user ;;
    "")
        if command -v apt-get >/dev/null 2>&1 && ls "$SRC"/releases/linfilecopy_*_all.deb >/dev/null 2>&1; then
            install_deb
        else
            install_user
        fi ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) die "unknown option $1 (see --help)" ;;
esac
