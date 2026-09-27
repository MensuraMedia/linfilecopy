#!/bin/sh
# Compile icons and CSS into linfilecopy/data/linfilecopy.gresource.
# The app also runs without the bundle (it falls back to the source tree),
# but installed builds should always ship the compiled file.
set -eu
cd "$(dirname "$0")/.."
DATA=linfilecopy/data
python3 tools/gen_gresource_xml.py > "$DATA/linfilecopy.gresource.xml"
glib-compile-resources --sourcedir="$DATA" --target="$DATA/linfilecopy.gresource" "$DATA/linfilecopy.gresource.xml"
echo "wrote $DATA/linfilecopy.gresource"
