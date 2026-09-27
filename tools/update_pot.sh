#!/bin/sh
# Regenerate po/linfilecopy.pot from every Python module.
# Translators: copy it to po/<lang>.po, translate, then run tools/build_mo.sh.
set -eu
cd "$(dirname "$0")/.."
find linfilecopy -name '*.py' | sort > po/POTFILES.in
xgettext --language=Python --keyword=_ --keyword=ngettext:1,2 --from-code=UTF-8 \
  --package-name=linfilecopy --package-version=0.1.0 --msgid-bugs-address=https://github.com/MensuraMedia/linfilecopy/issues \
  --add-comments=Translators --files-from=po/POTFILES.in --output=po/linfilecopy.pot
echo "po/linfilecopy.pot: $(grep -c '^msgid ' po/linfilecopy.pot) strings"
