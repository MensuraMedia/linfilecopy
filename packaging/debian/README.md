# Debian packaging

Copy this directory to `debian/` at the project root, then build:

```sh
cp -r packaging/debian debian
dpkg-buildpackage -us -uc -b
```
