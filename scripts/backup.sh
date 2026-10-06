#!/usr/bin/env bash
# Local backup: a timestamped tarball of the project source (+ a SHA-256 sidecar),
# excluding git/venv/build artifacts. Keeps the most recent few.
#
# Usage:   scripts/backup.sh
# Env:     BACKUP_DIR=/path   destination (default: ~/backups/linfilecopy)
#          RETAIN=10          how many recent backups to keep (default: 10)
#
# Note: .git is excluded, so this is a working-tree snapshot, not git history —
# history lives on origin/main. Run `git push` as well for a full off-repo copy.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG=linfilecopy
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${BACKUP_DIR:-$HOME/backups/$PKG}"
RETAIN="${RETAIN:-10}"
mkdir -p "$DEST"
OUT="$DEST/${PKG}_${STAMP}.tar.gz"

tar -czf "$OUT" -C "$(dirname "$ROOT")" \
  --exclude="$PKG/.git" \
  --exclude="$PKG/.venv" \
  --exclude="$PKG/build" \
  --exclude="$PKG/dist" \
  --exclude="$PKG/__pycache__" \
  --exclude="*.pyc" \
  "$PKG"

( cd "$DEST" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )

echo "Backup written: $OUT ($(du -h "$OUT" | cut -f1))"
echo "Checksum:       $OUT.sha256"

# Retention: keep the $RETAIN most recent, dropping each old tarball and its sidecar.
ls -1t "$DEST"/${PKG}_*.tar.gz 2>/dev/null | tail -n +"$((RETAIN + 1))" | while read -r old; do
  rm -f "$old" "$old.sha256"
done
