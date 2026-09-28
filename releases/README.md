# Releases

| File | What it is |
|---|---|
| `linfilecopy_0.1.0-1_all.deb` | Debian/Ubuntu package (architecture-independent), built with `tools/build_deb.sh` |
| `SHA256SUMS` | Checksum of the package |

Install (Debian, Ubuntu and derivatives):

```sh
sha256sum -c SHA256SUMS
sudo apt install ./linfilecopy_0.1.0-1_all.deb
```

or simply run `./install.sh` from the repository root, which verifies the checksum and
installs this package with apt. On other distributions, `./install.sh --user` installs
LinFileCopy for your user without root.

To rebuild after changing the code: `tools/build_deb.sh` (needs `debhelper dh-python
pybuild-plugin-pyproject python3-all`). The build runs the full test suite.
